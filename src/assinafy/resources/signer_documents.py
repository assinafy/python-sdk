from __future__ import annotations

import builtins
from typing import Any

from ..errors import ValidationError
from ..types import DOCUMENT_ARTIFACT_NAMES, DocumentArtifactName
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource


class SignerDocumentResource(BaseResource):
    """Signer-facing document endpoints.

    Listing and mutation methods require a ``signer-access-code`` query
    parameter. Artifact download is public in the current contract and still
    accepts an optional code for compatibility with earlier deployments.
    """

    def current(
        self,
        signer_id: str,
        signer_access_code: str,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/document?signer-access-code=...``.

        Returns the complete unwrapped
        :class:`~assinafy.resources.documents.DocumentResource` payload for the
        document the signer is currently expected to act on.
        """
        sid = self._path_id(signer_id, "Signer ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._call_dict(
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
        signer_access_code: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/documents?signer-access-code=...``.

        ``params`` accepts the published ``page`` and ``per_page`` keys. Other
        keys are forwarded for compatibility with older deployments. This
        endpoint requires the signer access code (the
        documented security scheme for every signer-facing endpoint); an
        omitted/invalid code always returns 401.
        Returns ``{"data": [Document, ...], "meta": {...}}`` where each item
        has the complete :class:`~assinafy.resources.documents.DocumentResource`
        shape and ``meta`` contains the four documented pagination integers.
        """
        sid = self._path_id(signer_id, "Signer ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        query = {**(params or {}), "signer_access_code": access_code}
        cleaned = clean_params(query, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list signer documents",
            lambda: self._http.get(f"signers/{sid}/documents", params=cleaned),
        )

    def search(
        self,
        signer_id: str,
        signer_access_code: str,
        search: str | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/documents/search?signer-access-code=...``.

        Lightweight, compact counterpart to :meth:`list` (no pagination
        parameters are documented for this endpoint). ``search`` is an optional
        partial-match term. Returns ``{"data": [Document, ...]}`` where every
        item has the complete
        :class:`~assinafy.resources.documents.DocumentResource` shape.
        """
        sid = self._path_id(signer_id, "Signer ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        cleaned = clean_params(
            {"search": search, "signer_access_code": access_code},
            QUERY_PARAM_ALIASES,
        )
        return self._call_list(
            "Failed to search signer documents",
            lambda: self._http.get(f"signers/{sid}/documents/search", params=cleaned),
        )

    def sign_multiple(
        self,
        document_ids: builtins.list[str],
        signer_access_code: str,
    ) -> None:
        """``PUT /signers/documents/sign-multiple?signer-access-code=...``.

        Signs several documents in one call (each must be ready for this signer).

        Example request body (JSON)::

            {"document_ids": ["doc-1", "doc-2"]}

        Success returns ``None``; the API response has no ``data`` payload.
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
        document_ids: builtins.list[str],
        decline_reason: str,
        signer_access_code: str,
    ) -> None:
        """``PUT /signers/documents/decline-multiple?signer-access-code=...``.

        Declines several documents in one call with a shared reason.

        Example request body (JSON)::

            {"document_ids": ["doc-1", "doc-2"],
             "decline_reason": "Unfavorable terms."}

        Success returns ``None``; the API response has no ``data`` payload.
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
        signer_access_code: str | None = None,
        artifact_name: DocumentArtifactName = "certificated",
    ) -> bytes:
        """``GET /signers/{signer_id}/documents/{document_id}/download/{artifact}``.

        This is a public signer-link endpoint; ``signer_access_code`` is accepted
        for backward compatibility but is not required by the current API.
        Returns raw artifact bytes. Valid artifacts: ``original``,
        ``certificated``, ``certificate-page``, ``pades``, and ``bundle``.
        ``pades`` exists only for documents signed with an ICP-Brasil certificate.
        """
        sid = self._path_id(signer_id, "Signer ID")
        doc_id = self._path_id(document_id, "Document ID")
        artifact = self._require_id(artifact_name, "Artifact name")
        if artifact not in DOCUMENT_ARTIFACT_NAMES:
            raise ValidationError(f"Unknown document artifact: {artifact}")
        return self._call_binary(
            "Failed to download signer document",
            lambda: self._http.get(
                f"signers/{sid}/documents/{doc_id}/download/{artifact}",
                params=clean_params(
                    {"signer_access_code": signer_access_code},
                    QUERY_PARAM_ALIASES,
                ),
            ),
        )


def _assert_document_ids(document_ids: list[str]) -> None:
    if (
        not isinstance(document_ids, list)
        or not document_ids
        or any(not isinstance(document_id, str) or not document_id for document_id in document_ids)
    ):
        raise ValidationError("At least one document ID is required")
