from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource


class SignerDocumentResource(BaseResource):
    """Signer-facing document endpoints (all signer-access-code authenticated).

    Every method here requires a valid ``signer_access_code`` obtained through
    the signer verification flow; an invalid/expired code returns 401.
    """

    def current(
        self,
        signer_id: str,
        signer_access_code: str,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/document?signer-access-code=...``.

        Returns the document the signer is currently expected to act on
        (``data`` envelope unwrapped). Shape mirrors the document object returned
        by the signer ``GET /sign`` view.
        """
        sid = self._require_id(signer_id, "Signer ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._call(
            "Failed to fetch current signer document",
            lambda: self._http.get(
                f"signers/{sid}/document",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
            ),
        )

    def list(
        self,
        signer_id: str,
        signer_access_code: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/documents?signer-access-code=...``.

        ``params`` accepts ``page``, ``per_page``, ``status``, ``method``
        (``virtual``/``collect``), ``search``, and ``sort`` (``name``,
        ``updated_at``). The signer-access-code is appended as a query parameter.
        Returns ``{"data": [...], "meta": {...}}``.
        """
        sid = self._require_id(signer_id, "Signer ID")
        query = dict(params or {})
        if signer_access_code is not None:
            query["signer_access_code"] = self._require_id(
                signer_access_code,
                "Signer access code",
            )
        cleaned = clean_params(query, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list signer documents",
            lambda: self._http.get(f"signers/{sid}/documents", params=cleaned),
        )

    def sign_multiple(
        self,
        document_ids: list[str],
        signer_access_code: str,
    ) -> None:
        """``PUT /signers/documents/sign-multiple?signer-access-code=...``.

        Signs several documents in one call (each must be ready for this signer).

        Example request body (JSON)::

            {"document_ids": ["doc-1", "doc-2"]}
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        _assert_document_ids(document_ids)
        self._call_void(
            "Failed to sign multiple documents",
            lambda: self._http.put(
                "signers/documents/sign-multiple",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json={"document_ids": document_ids},
            ),
        )

    def decline_multiple(
        self,
        document_ids: list[str],
        decline_reason: str,
        signer_access_code: str,
    ) -> None:
        """``PUT /signers/documents/decline-multiple?signer-access-code=...``.

        Declines several documents in one call with a shared reason.

        Example request body (JSON)::

            {"document_ids": ["doc-1", "doc-2"],
             "decline_reason": "Unfavorable terms."}
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        reason = self._require_id(decline_reason, "Decline reason")
        _assert_document_ids(document_ids)
        self._call_void(
            "Failed to decline multiple documents",
            lambda: self._http.put(
                "signers/documents/decline-multiple",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json={"document_ids": document_ids, "decline_reason": reason},
            ),
        )

    def download(
        self,
        signer_id: str,
        document_id: str,
        signer_access_code: str,
        artifact_name: str = "certificated",
    ) -> bytes:
        """``GET /signers/{signer_id}/documents/{document_id}/download/{artifact}``.

        Returns the raw artifact bytes. Valid artifacts: ``original``,
        ``certificated``, ``certificate-page``, ``bundle``.
        """
        sid = self._require_id(signer_id, "Signer ID")
        doc_id = self._require_id(document_id, "Document ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        artifact = self._require_id(artifact_name, "Artifact name")
        return self._call_binary(
            "Failed to download signer document",
            lambda: self._http.get(
                f"signers/{sid}/documents/{doc_id}/download/{artifact}",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
            ),
        )


def _assert_document_ids(document_ids: list[str]) -> None:
    if not document_ids or any(not document_id for document_id in document_ids):
        raise ValidationError("At least one document ID is required")
