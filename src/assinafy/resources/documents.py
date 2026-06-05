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
    """Document endpoints — upload, list, download, certify, verify, tag."""

    def upload(
        self,
        source: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/documents`` — upload a PDF.

        ``source`` is either ``{"file_path": "..."}`` or
        ``{"buffer": b"...", "file_name": "name.pdf"}``. The uploader sends
        ``multipart/form-data`` with the documented ``file`` part. Local
        validation enforces a ``.pdf`` extension and the 25 MB API limit (the
        API additionally limits documents to 2000 pages).

        ``options`` may contain ``account_id`` to override the client default.

        Example response (``data`` envelope unwrapped)::

            {"resource": "document", "id": "1031ff86...",
             "account_id": "102d25a4...", "template_id": null, "name": "sdk.pdf",
             "status": "uploaded",
             "artifacts": {"original": "https://.../download/original"},
             "is_closed": false, "signing_url": "https://app.../sign/1031ff86...",
             "decline_reason": null, "declined_by": null, "tags": [],
             "created_at": "2026-06-05T20:50:43Z",
             "updated_at": "2026-06-05T20:50:44Z", "pages": []}
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
        ``search``, ``sort`` (e.g. ``-updated_at``), ``status``, ``method``,
        and ``tags`` (comma-separated tag IDs). Returns
        ``{"data": [...], "meta": {...}}`` where ``meta`` is built from the
        documented ``x-pagination-*`` response headers.

        Example response (``data`` envelope unwrapped, one item trimmed)::

            {"data": [
                {"id": "1031ff84...", "account_id": "102d25a4...",
                 "template_id": null, "name": "contract.pdf",
                 "status": "metadata_ready",
                 "artifacts": {"original": "https://.../download/original",
                               "thumbnail": "https://.../thumbnail"},
                 "is_closed": false, "signing_url": "https://app.../sign/...",
                 "decline_reason": null, "declined_by": null,
                 "tags": [{"id": "1031ff85...", "name": "Contracts",
                           "color": null}],
                 "assignment": {"id": "1031ff85...", "method": "virtual",
                                "expires_at": null, "signers": [...]},
                 "created_at": "2026-06-05T20:50:33Z",
                 "updated_at": "2026-06-05T20:50:41Z"}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list documents",
            lambda: self._http.get(f"accounts/{acc_id}/documents", params=cleaned),
        )

    def statuses(self) -> list[dict[str, Any]]:
        """``GET /documents/statuses`` — list documented status codes.

        Example response (``data`` envelope unwrapped)::

            [{"code": "uploaded", "deletable": false},
             {"code": "metadata_ready", "deletable": true},
             {"code": "pending_signature", "deletable": true},
             {"code": "certificated", "deletable": false}]
        """
        return self._call_plain_list(
            "Failed to list document statuses",
            lambda: self._http.get("documents/statuses"),
        )

    def get(self, document_id: str) -> dict[str, Any]:
        """``GET /documents/{document_id}`` — fetch a single document.

        The single-document response embeds ``assignment`` (or ``null``) and
        ``pages`` once metadata processing completes.

        Example response (``data`` envelope unwrapped, trimmed)::

            {"resource": "document", "id": "1031ff86...",
             "account_id": "102d25a4...", "name": "sdk.pdf",
             "status": "metadata_ready",
             "artifacts": {"original": "https://.../download/original",
                           "thumbnail": "https://.../thumbnail"},
             "is_closed": false, "tags": [], "assignment": null,
             "pages": [{"id": "1031ff87...", "number": 1, "height": 1651,
                        "width": 1275,
                        "download_url": "https://.../pages/1031ff87.../download"}],
             "created_at": "2026-06-05T20:50:43Z",
             "updated_at": "2026-06-05T20:50:49Z"}
        """
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
        """Poll :meth:`get` until the document leaves a processing state.

        Resolves (returning the document) when the status is one of
        ``metadata_ready``, ``pending_signature``, or ``certificated``. Raises
        :class:`~assinafy.errors.ValidationError` if the status reaches a
        terminal failure (``failed``, ``rejected_by_signer``,
        ``rejected_by_user``, ``expired``) or if the timeout elapses.
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
        """``GET /documents/{document_id}/download/{artifact_name}`` — raw bytes.

        Valid artifacts: ``original``, ``certificated``, ``certificate-page``,
        ``bundle``. (``certificated``/``bundle`` exist only once the document is
        certificated.) Returns the raw PDF bytes.
        """
        doc_id = self._require_id(document_id, "Document ID")
        artifact = self._require_id(artifact_name, "Artifact name")
        return self._call_binary(
            "Failed to download document",
            lambda: self._http.get(f"documents/{doc_id}/download/{artifact}"),
        )

    def thumbnail(self, document_id: str) -> bytes:
        """``GET /documents/{document_id}/thumbnail`` — first-page thumbnail (JPEG bytes)."""
        doc_id = self._require_id(document_id, "Document ID")
        return self._call_binary(
            "Failed to download document thumbnail",
            lambda: self._http.get(f"documents/{doc_id}/thumbnail"),
        )

    def download_page(self, document_id: str, page_id: str) -> bytes:
        """``GET /documents/{document_id}/pages/{page_id}/download`` — page image (JPEG bytes).

        ``page_id`` comes from the ``pages[].id`` of :meth:`get` once metadata
        processing has produced page renders.
        """
        doc_id = self._require_id(document_id, "Document ID")
        pid = self._require_id(page_id, "Page ID")
        return self._call_binary(
            "Failed to download page",
            lambda: self._http.get(f"documents/{doc_id}/pages/{pid}/download"),
        )

    def activities(self, document_id: str) -> list[dict[str, Any]]:
        """``GET /documents/{document_id}/activities`` — event audit log.

        Example response (``data`` envelope unwrapped)::

            [{"id": 8257, "event": "document_uploaded",
              "message": "Documento criado.", "payload": [],
              "origin": {"ip": "99.75.13.162",
                         "user-agent": "assinafy-python-sdk/1.3.2"},
              "created_at": "2026-06-05T20:50:44Z"}]
        """
        doc_id = self._require_id(document_id, "Document ID")
        return self._call_plain_list(
            "Failed to fetch document activities",
            lambda: self._http.get(f"documents/{doc_id}/activities"),
        )

    def delete(self, document_id: str) -> None:
        """``DELETE /documents/{document_id}`` — delete a document.

        The API only permits deletion when the document is in a deletable
        status (``metadata_ready``, ``expired``, ``pending_signature``,
        ``rejected_by_signer``, ``rejected_by_user``, ``failed``). A 400 is
        returned otherwise and surfaced as :class:`~assinafy.errors.ApiError`.
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

        ``signers`` is the documented list of role assignments (each entry needs
        ``role_id`` plus ``id``/``verification_method``/...). ``options`` may
        include ``name``, ``message``, ``expires_at``, ``editor_fields``,
        ``copy_receivers``.

        Example request body (JSON)::

            {"signers": [{"role_id": "role-1", "id": "1031ff86...",
                          "verification_method": "Email"}],
             "name": "NDA - John Doe", "message": "Please sign."}

        Returns the created document object (``data`` envelope unwrapped).
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
        """``POST /accounts/{account_id}/templates/{template_id}/documents/estimate-cost``.

        Example request body (JSON)::

            {"signers": [{"role_id": "role-1", "id": "1031ff86..."}]}

        Returns a cost-estimate object (``data`` envelope unwrapped) with the
        same shape as :meth:`assinafy.resources.assignments.AssignmentResource.estimate_cost`.
        """
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
        """``GET /documents/{signature_hash}/verify`` — public signature verification.

        Returns the public verification record for a certificated document
        (``data`` envelope unwrapped).
        """
        h = self._require_id(signature_hash, "Signature hash")
        return self._call(
            "Failed to verify document",
            lambda: self._http.get(f"documents/{h}/verify"),
        )

    def public_info(self, document_id: str) -> dict[str, Any]:
        """``GET /public/documents/{document_id}`` — public metadata, no auth required.

        Example response (``data`` envelope unwrapped)::

            {"resource": "document", "id": "1031ff86...", "name": "sdk.pdf",
             "page_count": "1", "created_by": "Acme Inc."}
        """
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

        Example request body (JSON)::

            {"recipient": "signer@example.com", "channel": "email"}
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

    def list_tags(
        self,
        document_id: str,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """``GET /accounts/{account_id}/documents/{document_id}/tags`` — list document tags.

        Example response (``data`` envelope unwrapped)::

            [{"id": "1031ff86...", "name": "Contracts", "color": null,
              "created_at": "2026-06-05T20:50:43Z",
              "updated_at": "2026-06-05T20:50:43Z"}]
        """
        acc_id = self._account_id(account_id)
        doc_id = self._require_id(document_id, "Document ID")
        return self._call_plain_list(
            "Failed to list document tags",
            lambda: self._http.get(f"accounts/{acc_id}/documents/{doc_id}/tags"),
        )

    def replace_tags(
        self,
        document_id: str,
        tags: list[str],
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """``PUT /accounts/{account_id}/documents/{document_id}/tags`` — replace all tags.

        Replaces all document tags with ``tags`` (a list of tag names). Passing
        an empty list is documented and detaches all tags from the document.

        Example request body (JSON)::

            {"tags": ["Contracts", "2026-Q1"]}

        Returns the resulting tag list (``data`` envelope unwrapped).
        """
        acc_id = self._account_id(account_id)
        doc_id = self._require_id(document_id, "Document ID")
        body = {"tags": _validate_tag_names(tags, allow_empty=True)}
        return self._call_plain_list(
            "Failed to replace document tags",
            lambda: self._http.put(
                f"accounts/{acc_id}/documents/{doc_id}/tags",
                json=body,
            ),
        )

    def append_tags(
        self,
        document_id: str,
        tags: list[str],
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """``POST /accounts/{account_id}/documents/{document_id}/tags`` — add tags.

        Adds ``tags`` (a non-empty list of tag names) to the document without
        removing existing ones.

        Example request body (JSON)::

            {"tags": ["Urgent"]}

        Returns the resulting tag list (``data`` envelope unwrapped).
        """
        acc_id = self._account_id(account_id)
        doc_id = self._require_id(document_id, "Document ID")
        body = {"tags": _validate_tag_names(tags, allow_empty=False)}
        return self._call_plain_list(
            "Failed to append document tags",
            lambda: self._http.post(
                f"accounts/{acc_id}/documents/{doc_id}/tags",
                json=body,
            ),
        )

    def detach_tag(
        self,
        document_id: str,
        tag_id: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``DELETE /accounts/{account_id}/documents/{document_id}/tags/{tag_id}``.

        Detaches one tag from a document. The tag resource itself is not deleted.

        Example response (``data`` envelope unwrapped)::

            {"detached": true}
        """
        acc_id = self._account_id(account_id)
        doc_id = self._require_id(document_id, "Document ID")
        tid = self._require_id(tag_id, "Tag ID")
        return self._call_plain_dict(
            "Failed to detach document tag",
            lambda: self._http.delete(
                f"accounts/{acc_id}/documents/{doc_id}/tags/{tid}"
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


def _validate_tag_names(tags: list[str], allow_empty: bool) -> list[str]:
    if not isinstance(tags, list):
        raise ValidationError("tags must be a list")
    if not tags and not allow_empty:
        raise ValidationError("At least one tag name is required")
    if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise ValidationError("Tag names must be non-empty strings", {"tags": tags})
    return tags
