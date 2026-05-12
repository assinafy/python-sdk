from __future__ import annotations

import os
import time
from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_READY_STATUSES = frozenset({"metadata_ready", "pending_signature", "certificated"})
_FAILED_STATUSES = frozenset(
    {"failed", "rejected_by_signer", "rejected_by_user", "expired"}
)


class DocumentResource(BaseResource):
    """Document endpoints — upload, list, download, certify, verify."""

    def upload(
        self,
        source: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/documents`` — upload a PDF.

        ``source`` is either ``{"file_path": "..."}`` or
        ``{"buffer": b"...", "file_name": "name.pdf"}``. The uploader sends
        ``multipart/form-data`` with the documented ``file`` part. Local
        validation enforces ``.pdf`` extension and the 25 MB API limit.

        ``options`` may contain ``account_id`` to override the client default.
        """
        options = options or {}
        buffer, file_name = _load_source(source)
        _validate_upload(buffer, file_name)

        account_id = self._account_id(options.get("account_id"))
        self._logger.info(
            "Uploading document", {"file_name": file_name, "size": len(buffer)}
        )

        document: dict[str, Any] = self._call(
            "Document upload failed",
            lambda: self._http.post(
                f"accounts/{account_id}/documents",
                files={"file": (file_name, buffer, "application/pdf")},
            ),
        )
        if not document or not document.get("id"):
            raise ValidationError(
                "Upload succeeded but no document ID was returned",
                {"response": document},
            )
        self._logger.info("Document uploaded", {"document_id": document["id"]})
        return document

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/documents`` — list workspace documents.

        ``params`` accepts ``page``, ``per_page`` (sent as ``per-page``),
        ``search``, ``sort`` (e.g. ``-updated_at``), and ``status``. Returns
        ``{"data": [...], "meta": {...}}`` where ``meta`` is built from the
        documented ``x-pagination-*`` response headers.
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list documents",
            lambda: self._http.get(f"accounts/{acc_id}/documents", params=cleaned),
        )

    def statuses(self) -> list[dict[str, Any]]:
        """``GET /documents/statuses`` — list documented status codes."""
        result = self._call(
            "Failed to list document statuses",
            lambda: self._http.get("documents/statuses"),
        )
        return result if isinstance(result, list) else []

    def get(self, document_id: str) -> dict[str, Any]:
        """``GET /documents/{document_id}`` — fetch a single document."""
        doc_id = self._require_id(document_id, "Document ID")
        return self._call(
            "Failed to fetch document details",
            lambda: self._http.get(f"documents/{doc_id}"),
        )

    def wait_until_ready(
        self,
        document_id: str,
        timeout: float = 30.0,
        poll_interval: float = 2.0,
    ) -> dict[str, Any]:
        """Poll ``documents.get`` until the document leaves a processing state.

        Resolves when the status is one of ``metadata_ready``,
        ``pending_signature``, or ``certificated``. Raises ``ValidationError``
        if the status reaches a terminal failure (``failed``,
        ``rejected_by_signer``, ``rejected_by_user``, ``expired``) or if the
        timeout elapses.
        """
        doc_id = self._require_id(document_id, "Document ID")
        deadline = time.monotonic() + timeout
        attempts = 0
        self._logger.info(
            "Waiting for document to be ready",
            {"document_id": doc_id, "timeout": timeout},
        )

        while time.monotonic() < deadline:
            attempts += 1
            try:
                document = self.get(doc_id)
            except ValidationError:
                raise
            except Exception as err:
                self._logger.warning(
                    "Error checking document status", {"error": str(err)}
                )
                time.sleep(poll_interval)
                continue

            status = document.get("status", "unknown")
            self._logger.debug(
                "Document status check", {"attempts": attempts, "status": status}
            )
            if status in _READY_STATUSES:
                return document
            if status in _FAILED_STATUSES:
                raise ValidationError(
                    f"Document processing failed with status: {status}",
                    {"status": status},
                )
            time.sleep(poll_interval)

        raise ValidationError(
            "Timeout waiting for document to be ready",
            {"document_id": doc_id, "attempts": attempts},
        )

    def download(
        self,
        document_id: str,
        artifact_name: str = "certificated",
    ) -> bytes:
        """``GET /documents/{document_id}/download/{artifact_name}``.

        Valid artifacts: ``original``, ``certificated``, ``certificate-page``,
        ``bundle``. Returns the raw bytes.
        """
        doc_id = self._require_id(document_id, "Document ID")
        artifact = self._require_id(artifact_name, "Artifact name")
        return self._call_binary(
            "Failed to download document",
            lambda: self._http.get(f"documents/{doc_id}/download/{artifact}"),
        )

    def thumbnail(self, document_id: str) -> bytes:
        """``GET /documents/{document_id}/thumbnail`` — first-page thumbnail bytes."""
        doc_id = self._require_id(document_id, "Document ID")
        return self._call_binary(
            "Failed to download document thumbnail",
            lambda: self._http.get(f"documents/{doc_id}/thumbnail"),
        )

    def download_page(self, document_id: str, page_id: str) -> bytes:
        """``GET /documents/{document_id}/pages/{page_id}/download``."""
        doc_id = self._require_id(document_id, "Document ID")
        pid = self._require_id(page_id, "Page ID")
        return self._call_binary(
            "Failed to download page",
            lambda: self._http.get(f"documents/{doc_id}/pages/{pid}/download"),
        )

    def activities(self, document_id: str) -> list[dict[str, Any]]:
        """``GET /documents/{document_id}/activities`` — event audit log."""
        doc_id = self._require_id(document_id, "Document ID")
        result = self._call(
            "Failed to fetch document activities",
            lambda: self._http.get(f"documents/{doc_id}/activities"),
        )
        return result if isinstance(result, list) else []

    def delete(self, document_id: str) -> None:
        """``DELETE /documents/{document_id}``.

        The API only permits deletion when the document is in a deletable
        status (``metadata_ready``, ``expired``, ``pending_signature``,
        ``rejected_by_signer``, ``rejected_by_user``, ``failed``). A 400 is
        returned otherwise and surfaced as :class:`ApiError`.
        """
        doc_id = self._require_id(document_id, "Document ID")
        return self._call_void(
            "Failed to delete document",
            lambda: self._http.delete(f"documents/{doc_id}"),
        )

    def create_from_template(
        self,
        template_id: str,
        signers: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/templates/{template_id}/documents``.

        ``signers`` is the documented list of role assignments
        (each entry needs ``role_id`` plus ``id``/``verification_method``/...).
        ``options`` may include ``name``, ``message``, ``expires_at``,
        ``editor_fields``, ``copy_receivers``.
        """
        tmpl_id = self._require_id(template_id, "Template ID")
        acc_id = self._account_id(account_id)
        if not signers:
            raise ValidationError("At least one signer is required")
        body: dict[str, Any] = {"signers": signers, **(options or {})}
        self._logger.info(
            "Creating document from template",
            {"template_id": tmpl_id, "account_id": acc_id},
        )
        return self._call(
            "Failed to create document from template",
            lambda: self._http.post(
                f"accounts/{acc_id}/templates/{tmpl_id}/documents",
                json=body,
            ),
        )

    def estimate_cost_from_template(
        self,
        template_id: str,
        signers: list[dict[str, Any]],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/templates/{template_id}/documents/estimate-cost``."""
        tmpl_id = self._require_id(template_id, "Template ID")
        acc_id = self._account_id(account_id)
        if not signers:
            raise ValidationError("At least one signer is required")
        return self._call(
            "Failed to estimate cost from template",
            lambda: self._http.post(
                f"accounts/{acc_id}/templates/{tmpl_id}/documents/estimate-cost",
                json={"signers": signers},
            ),
        )

    def verify(self, signature_hash: str) -> dict[str, Any]:
        """``GET /documents/{signature_hash}/verify`` — public verification."""
        h = self._require_id(signature_hash, "Signature hash")
        return self._call(
            "Failed to verify document",
            lambda: self._http.get(f"documents/{h}/verify"),
        )

    def public_info(self, document_id: str) -> dict[str, Any]:
        """``GET /public/documents/{document_id}`` — public metadata, no auth."""
        doc_id = self._require_id(document_id, "Document ID")
        return self._call(
            "Failed to fetch public document information",
            lambda: self._http.get(f"public/documents/{doc_id}"),
        )

    def send_token(
        self,
        document_id: str,
        recipient: str,
        channel: str,
    ) -> dict[str, Any]:
        """``PUT /public/documents/{document_id}/send-token``.

        Sends a 6-digit verification token to ``recipient`` over ``channel``
        (``email`` or ``whatsapp``).
        """
        doc_id = self._require_id(document_id, "Document ID")
        self._require_id(recipient, "Recipient")
        self._require_id(channel, "Channel")
        return self._call(
            "Failed to send document token",
            lambda: self._http.put(
                f"public/documents/{doc_id}/send-token",
                json={"recipient": recipient, "channel": channel},
            ),
        )


def _load_source(source: dict[str, Any]) -> tuple[bytes, str]:
    if "buffer" in source:
        if not source.get("file_name"):
            raise ValidationError("file_name is required when uploading a buffer")
        return source["buffer"], source["file_name"]
    file_path = source.get("file_path")
    if not file_path:
        raise ValidationError("file_path is required")
    with open(file_path, "rb") as f:
        buffer = f.read()
    file_name: str = source.get("file_name") or os.path.basename(file_path)
    return buffer, file_name


def _validate_upload(buffer: bytes, file_name: str) -> None:
    if not buffer:
        raise ValidationError("File buffer is empty", {"file_name": file_name})
    if not file_name.lower().endswith(".pdf"):
        raise ValidationError("Only PDF files are supported", {"file_name": file_name})
    if len(buffer) > MAX_UPLOAD_BYTES:
        raise ValidationError(
            "File size exceeds maximum allowed (25MB)",
            {"file_size": len(buffer), "max_size": MAX_UPLOAD_BYTES},
        )
