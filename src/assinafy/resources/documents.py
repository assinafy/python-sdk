from __future__ import annotations

import builtins
import math
import os
import time
from typing import Any

from ..errors import ApiError, NetworkError, ValidationError
from ..types import DOCUMENT_ARTIFACT_NAMES, DocumentArtifactName
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_READY_STATUSES = frozenset({"metadata_ready", "pending_signature", "certificated"})
_FAILED_STATUSES = frozenset({"failed", "rejected_by_signer", "rejected_by_user", "expired"})
_TOKEN_CHANNELS = frozenset({"email", "whatsapp"})
_TEMPLATE_OPTIONS = frozenset({"name", "message", "expires_at", "editor_fields", "tags", "signers"})
_TEMPLATE_SIGNER_FIELDS = frozenset(
    {"role_id", "id", "verification_method", "notification_methods", "step"}
)
_TEMPLATE_ESTIMATE_SIGNER_FIELDS = frozenset(
    {"role_id", "verification_method", "notification_methods"}
)
_VERIFICATION_METHODS = frozenset({"Email", "Whatsapp", "DigitalCertificate"})
_NOTIFICATION_METHODS = frozenset({"Email", "Whatsapp"})


class DocumentResource(BaseResource):
    """Document endpoints — upload, list, download, certify, verify, tag.

    Document-returning methods preserve this complete unwrapped top-level
    payload (nested arrays/objects use their own documented resource shapes)::

        {"resource": "document", "id": "document-id", "account_id": "account-id",
         "template_id": null, "name": "contract.pdf", "status": "metadata_ready",
         "artifacts": {"original": "https://api.example/document/original"},
         "is_closed": false, "signing_url": "https://app.example/sign/document-id",
         "decline_reason": null, "declined_by": null, "tags": [],
         "assignment": null, "pages": [],
         "created_at": "2026-06-03T03:54:16Z",
         "updated_at": "2026-06-03T03:54:17Z"}
    """

    def upload(
        self,
        source: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/documents`` — upload a PDF.

        ``source`` is either ``{"file_path": "..."}`` or
        ``{"buffer": b"...", "file_name": "name.pdf"}``. The uploader sends
        ``multipart/form-data`` with the documented ``file`` part. Local
        validation enforces a ``.pdf`` extension and the 25 MB API limit (the
        API additionally limits documents to 2000 pages).

        ``account_id`` overrides the client's default account for this call.

        Example response (``data`` envelope unwrapped)::

            {"resource": "document", "id": "1031ff86...",
             "account_id": "account-id", "template_id": null, "name": "sdk.pdf",
             "status": "uploaded",
             "artifacts": {"original": "https://.../download/original"},
             "is_closed": false, "signing_url": "https://app.../sign/1031ff86...",
             "decline_reason": null, "declined_by": null, "tags": [],
             "created_at": "2026-06-05T20:50:43Z",
             "updated_at": "2026-06-05T20:50:44Z", "pages": []}
        """
        buffer, file_name = _load_source(source)
        _validate_upload(buffer, file_name)

        acc_id = self._account_id(account_id)
        self._logger.info("Uploading document", {"file_name": file_name, "size": len(buffer)})

        document = self._call_dict(
            "Document upload failed",
            lambda: self._http.post(
                f"accounts/{acc_id}/documents",
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

        Example response (``data`` envelope unwrapped)::

            {"data": [
                {"id": "document-id", "account_id": "account-id",
                 "template_id": null, "name": "contract.pdf",
                 "status": "metadata_ready",
                 "artifacts": {"original": "https://.../download/original",
                               "thumbnail": "https://.../thumbnail"},
                 "is_closed": false, "signing_url": "https://app.../sign/...",
                 "decline_reason": null, "declined_by": null,
                 "tags": [{"id": "1031ff85...", "name": "Contracts",
                           "color": null}],
                 "assignment": null,
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

    def statuses(self) -> builtins.list[dict[str, Any]]:
        """``GET /documents/statuses`` — list documented status codes.

        Example response (``data`` envelope unwrapped, full set)::

            [{"code": "uploading", "deletable": false},
             {"code": "uploaded", "deletable": false},
             {"code": "metadata_processing", "deletable": false},
             {"code": "metadata_ready", "deletable": true},
             {"code": "expired", "deletable": true},
             {"code": "certificating", "deletable": false},
             {"code": "certificated", "deletable": false},
             {"code": "rejected_by_signer", "deletable": true},
             {"code": "pending_signature", "deletable": true},
             {"code": "rejected_by_user", "deletable": true},
             {"code": "failed", "deletable": true}]
        """
        return self._call_plain_list(
            "Failed to list document statuses",
            lambda: self._http.get("documents/statuses"),
        )

    def get(self, document_id: str) -> dict[str, Any]:
        """``GET /documents/{document_id}`` — fetch a single document.

        The single-document response embeds ``assignment`` (or ``null``) and
        ``pages`` once metadata processing completes.

        Example response (``data`` envelope unwrapped)::

            {"resource": "document", "id": "1031ff86...",
             "account_id": "account-id", "name": "sdk.pdf",
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
        doc_id = self._path_id(document_id, "Document ID")
        return self._call_dict(
            "Failed to fetch document details",
            lambda: self._http.get(f"documents/{doc_id}"),
        )

    def rename(self, document_id: str, name: str) -> dict[str, Any]:
        """``PATCH /documents/{document_id}`` — rename a document.

        Only allowed before the signature process starts (the document is in
        ``uploaded`` or ``metadata_ready`` status with no signers yet); once an
        assignment exists or the document is certificated the API locks the name
        and returns a 400. Server-side the name is normalized (diacritics
        removed) and capped at 255 characters.

        Example request body (JSON)::

            {"name": "Service agreement.pdf"}

        Example response (``data`` envelope unwrapped)::

            {"resource": "document", "id": "103b08a1...",
             "account_id": "account-id", "template_id": null,
             "name": "Renamed via SDK.pdf", "status": "metadata_ready",
             "artifacts": {"original": "https://.../download/original",
                           "thumbnail": "https://.../thumbnail"},
             "is_closed": false, "tags": [],
             "created_at": "2026-06-05T20:50:43Z",
             "updated_at": "2026-06-05T20:50:49Z"}
        """
        doc_id = self._path_id(document_id, "Document ID")
        new_name = self._require_id(name, "Document name")
        if len(new_name) > 255:
            raise ValidationError(
                "Document name must be 255 characters or fewer",
                {"length": len(new_name)},
            )
        return self._call_dict(
            "Failed to rename document",
            lambda: self._http.patch(f"documents/{doc_id}", json={"name": new_name}),
        )

    def search(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/documents/search`` — lightweight search.

        A compact counterpart to :meth:`list`: it returns documents **without**
        the expanded ``assignment`` / ``pages`` fields, which makes it cheaper
        for autocomplete/typeahead. ``params`` accepts ``search`` (partial match
        on document name / signer name / signer email), ``status``, and the
        usual ``page`` / ``per_page`` (sent as ``per-page``) pagination keys.
        Returns ``{"data": [...], "meta": {...}}`` when the API returns the
        ``x-pagination-*`` headers.

        Example response (``data`` envelope unwrapped)::

            {"data": [
                {"id": "document-id", "account_id": "account-id",
                 "template_id": null, "name": "Renamed via SDK.pdf",
                 "status": "metadata_ready",
                 "artifacts": {"original": "https://.../download/original",
                               "thumbnail": "https://.../thumbnail"},
                 "is_closed": false,
                 "signing_url": "https://app.../sign/103b08a1...",
                 "decline_reason": null, "declined_by": null, "tags": [],
                 "created_at": "2026-06-05T20:50:43Z",
                 "updated_at": "2026-06-05T20:50:49Z"}
             ]}
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to search documents",
            lambda: self._http.get(f"accounts/{acc_id}/documents/search", params=cleaned),
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
        Re-raises immediately (no retry) if the document can't be found at all
        (``404``), since that will never resolve by waiting.
        """
        doc_id = self._path_id(document_id, "Document ID")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValidationError("timeout must be greater than zero")
        if (
            isinstance(poll_interval, bool)
            or not isinstance(poll_interval, (int, float))
            or not math.isfinite(poll_interval)
            or poll_interval <= 0
        ):
            raise ValidationError("poll_interval must be greater than zero")
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
            except ApiError as err:
                if err.status_code not in {408, 429} and err.status_code < 500:
                    raise
                self._logger.warning("Error checking document status", {"error": str(err)})
            except NetworkError as err:
                self._logger.warning("Error checking document status", {"error": str(err)})
            else:
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
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(poll_interval, remaining))

        raise ValidationError(
            "Timeout waiting for document to be ready",
            {"document_id": doc_id, "attempts": attempts},
        )

    def download(
        self,
        document_id: str,
        artifact_name: DocumentArtifactName = "certificated",
    ) -> bytes:
        """``GET /documents/{document_id}/download/{artifact_name}`` — raw bytes.

        Valid artifacts: ``original``, ``certificated``, ``certificate-page``,
        ``pades``, and ``bundle``. ``pades`` exists only for documents signed
        with ICP-Brasil certificates. Returns the raw PDF/ZIP bytes.
        """
        doc_id = self._path_id(document_id, "Document ID")
        artifact = self._require_id(artifact_name, "Artifact name")
        if artifact not in DOCUMENT_ARTIFACT_NAMES:
            raise ValidationError(f"Unknown document artifact: {artifact}")
        return self._call_binary(
            "Failed to download document",
            lambda: self._http.get(f"documents/{doc_id}/download/{artifact}"),
        )

    def thumbnail(self, document_id: str) -> bytes:
        """``GET /documents/{document_id}/thumbnail`` — first-page thumbnail (JPEG bytes)."""
        doc_id = self._path_id(document_id, "Document ID")
        return self._call_binary(
            "Failed to download document thumbnail",
            lambda: self._http.get(f"documents/{doc_id}/thumbnail"),
        )

    def download_page(self, document_id: str, page_id: str) -> bytes:
        """``GET /documents/{document_id}/pages/{page_id}/download`` — page image (JPEG bytes).

        ``page_id`` comes from the ``pages[].id`` of :meth:`get` once metadata
        processing has produced page renders.
        """
        doc_id = self._path_id(document_id, "Document ID")
        pid = self._path_id(page_id, "Page ID")
        return self._call_binary(
            "Failed to download page",
            lambda: self._http.get(f"documents/{doc_id}/pages/{pid}/download"),
        )

    def activities(self, document_id: str) -> builtins.list[dict[str, Any]]:
        """``GET /documents/{document_id}/activities`` — event audit log.

        Example response (``data`` envelope unwrapped)::

            [{"id": 8257, "event": "document_uploaded",
              "message": "Documento criado.", "payload": [],
              "origin": {"ip": "192.0.2.1",
                         "user-agent": "assinafy-python-sdk/1.x"},
              "created_at": "2026-06-05T20:50:44Z"}]
        """
        doc_id = self._path_id(document_id, "Document ID")
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
        Request body: none. Success returns ``None``; the API response has no
        ``data`` payload.
        """
        doc_id = self._path_id(document_id, "Document ID")
        return self._call_void(
            "Failed to delete document",
            lambda: self._http.delete(f"documents/{doc_id}"),
        )

    def create_from_template(
        self,
        template_id: str,
        signers: builtins.list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/templates/{template_id}/documents``.

        ``signers`` is the documented list of role assignments (each entry needs
        ``role_id`` plus ``id``/``verification_method``/...). ``options`` may
        include ``name``, ``message``, ``expires_at``, ``editor_fields``,
        ``tags``.

        Example request body (JSON)::

            {"signers": [{"role_id": "role-1", "id": "1031ff86...",
                          "verification_method": "Email"}],
             "name": "NDA - John Doe", "message": "Please sign."}

        Returns the created document object (``data`` envelope unwrapped).
        """
        tmpl_id = self._path_id(template_id, "Template ID")
        acc_id = self._account_id(account_id)
        if not isinstance(signers, list) or not signers:
            raise ValidationError("At least one signer is required")
        _validate_template_signers(signers, require_id=True)
        if options is not None and not isinstance(options, dict):
            raise ValidationError("Template options must be a mapping")
        option_values = options or {}
        unknown = option_values.keys() - _TEMPLATE_OPTIONS
        if unknown:
            raise ValidationError(f"Unknown template options: {', '.join(sorted(unknown))}")
        # `signers` is applied last so an `options` dict can never silently
        # override the just-validated list (e.g. a stray "signers" key in options).
        body: dict[str, Any] = {**option_values, "signers": signers}
        self._logger.info(
            "Creating document from template",
            {"template_id": tmpl_id, "account_id": acc_id},
        )
        return self._call_dict(
            "Failed to create document from template",
            lambda: self._http.post(
                f"accounts/{acc_id}/templates/{tmpl_id}/documents",
                json=body,
            ),
        )

    def estimate_cost_from_template(
        self,
        template_id: str,
        signers: builtins.list[dict[str, Any]],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/templates/{template_id}/documents/estimate-cost``.

        Unlike :meth:`create_from_template`, contact information is not required
        here — only ``role_id`` and optionally ``verification_method`` /
        ``notification_methods`` per signer.

        Example request body (JSON)::

            {"signers": [{"role_id": "role-1"}]}

        Returns a cost-estimate object (``data`` envelope unwrapped) with the
        same shape as :meth:`assinafy.resources.assignments.AssignmentResource.estimate_cost`.
        """
        tmpl_id = self._path_id(template_id, "Template ID")
        acc_id = self._account_id(account_id)
        if not isinstance(signers, list) or not signers:
            raise ValidationError("At least one signer is required")
        _validate_template_signers(signers, require_id=False, estimate=True)
        return self._call_dict(
            "Failed to estimate cost from template",
            lambda: self._http.post(
                f"accounts/{acc_id}/templates/{tmpl_id}/documents/estimate-cost",
                json={"signers": signers},
            ),
        )

    def verify(self, signature_hash: str) -> dict[str, Any]:
        """``GET /documents/{signature_hash}/verify`` — public signature verification.

        Complete unwrapped response for a valid document::

            {"hash": "0000000000000000000000000000000000000000",
             "id": "document-id", "status": "certificated", "page_count": "1",
             "signer_count": "1", "completed_count": 1,
             "completed_at": "2026-06-03T03:54:16Z",
             "verified_at": "2026-06-03T03:55:00Z", "is_valid": true,
             "message": ""}
        """
        h = self._path_id(signature_hash, "Signature hash")
        return self._call_dict(
            "Failed to verify document",
            lambda: self._http.get(f"documents/{h}/verify"),
        )

    def public_info(self, document_id: str) -> dict[str, Any]:
        """``GET /public/documents/{document_id}`` — public metadata, no auth required.

        The current OpenAPI schema describes the full :class:`DocumentResource`
        payload documented above.
        Sandbox deployments have also returned this compact, backward-compatible
        public representation, which the SDK preserves without discarding fields::

            {"resource": "document", "id": "1031ff86...", "name": "sdk.pdf",
             "page_count": "1", "created_by": "Acme Inc."}
        """
        doc_id = self._path_id(document_id, "Document ID")
        return self._call_dict(
            "Failed to fetch public document information",
            lambda: self._http.get(f"public/documents/{doc_id}"),
        )

    def send_token(
        self,
        document_id: str,
        recipient: str | None = None,
        channel: str | None = None,
        *,
        email: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /public/documents/{document_id}/send-token``.

        The current OpenAPI body is optional and accepts ``email``. Existing
        sandbox deployments still require the earlier ``recipient`` +
        ``channel`` shape (``email`` or ``whatsapp``), so both forms remain
        supported. Do not mix them. A successful no-data envelope is returned.

        Current request body (JSON)::

            {"email": "signer@example.com"}

        Backward-compatible request body (JSON)::

            {"recipient": "signer@example.com", "channel": "email"}
        """
        doc_id = self._path_id(document_id, "Document ID")
        if email is not None and (recipient is not None or channel is not None):
            raise ValidationError("Use email or recipient/channel, not both")
        if email is not None:
            body = {"email": self._require_id(email, "Email")}
        elif recipient is not None or channel is not None:
            if not isinstance(channel, str) or channel not in _TOKEN_CHANNELS:
                raise ValidationError('Channel must be "email" or "whatsapp"')
            body = {
                "recipient": self._require_id(recipient, "Recipient"),
                "channel": self._require_id(channel, "Channel"),
            }
        else:
            body = {}
        path = f"public/documents/{doc_id}/send-token"
        return self._call_dict(
            "Failed to send document token",
            lambda: self._http.put(path, json=body) if body else self._http.put(path),
        )

    def list_tags(
        self,
        document_id: str,
        account_id: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """``GET /accounts/{account_id}/documents/{document_id}/tags`` — list document tags.

        Example response (``data`` envelope unwrapped)::

            [{"id": "1031ff86...", "name": "Contracts", "color": null,
              "created_at": "2026-06-05T20:50:43Z",
              "updated_at": "2026-06-05T20:50:43Z"}]
        """
        acc_id = self._account_id(account_id)
        doc_id = self._path_id(document_id, "Document ID")
        return self._call_plain_list(
            "Failed to list document tags",
            lambda: self._http.get(f"accounts/{acc_id}/documents/{doc_id}/tags"),
        )

    def replace_tags(
        self,
        document_id: str,
        tags: builtins.list[str],
        account_id: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """``PUT /accounts/{account_id}/documents/{document_id}/tags`` — replace all tags.

        Replaces all document tags with ``tags`` (a list of tag IDs). Passing
        an empty list is documented and detaches all tags from the document.

        Example request body (JSON)::

            {"tags": ["tag-id-1", "tag-id-2"]}

        Returns the resulting tag list (``data`` envelope unwrapped).
        """
        acc_id = self._account_id(account_id)
        doc_id = self._path_id(document_id, "Document ID")
        body = {"tags": _validate_tag_ids(tags, allow_empty=True)}
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
        tags: builtins.list[str],
        account_id: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """``POST /accounts/{account_id}/documents/{document_id}/tags`` — add tags.

        Adds ``tags`` (a non-empty list of tag IDs) to the document without
        removing existing ones.

        Example request body (JSON)::

            {"tags": ["tag-id"]}

        Returns the resulting tag list (``data`` envelope unwrapped).
        """
        acc_id = self._account_id(account_id)
        doc_id = self._path_id(document_id, "Document ID")
        body = {"tags": _validate_tag_ids(tags, allow_empty=False)}
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
        doc_id = self._path_id(document_id, "Document ID")
        tid = self._path_id(tag_id, "Tag ID")
        return self._call_dict(
            "Failed to detach document tag",
            lambda: self._http.delete(f"accounts/{acc_id}/documents/{doc_id}/tags/{tid}"),
        )


def _load_source(source: dict[str, Any]) -> tuple[bytes, str]:
    if not isinstance(source, dict):
        raise ValidationError("source must be a mapping")
    if "buffer" in source:
        file_name = source.get("file_name")
        if not isinstance(file_name, str) or not file_name:
            raise ValidationError("file_name is required when uploading a buffer")
        buffer = source["buffer"]
        if not isinstance(buffer, (bytes, bytearray, memoryview)):
            raise ValidationError("buffer must contain bytes")
        return bytes(buffer), file_name
    file_path = source.get("file_path")
    if not isinstance(file_path, (str, os.PathLike)) or not file_path:
        raise ValidationError("file_path is required")
    try:
        with open(file_path, "rb") as f:
            buffer = f.read()
    except OSError as err:
        raise ValidationError(
            "Unable to read upload file", {"file_path": os.fspath(file_path)}
        ) from err
    file_name = source.get("file_name") or os.path.basename(file_path)
    if not isinstance(file_name, str):
        raise ValidationError("file_name must be a string")
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


def _validate_tag_ids(tags: list[str], allow_empty: bool) -> list[str]:
    if not isinstance(tags, list):
        raise ValidationError("tags must be a list")
    if not tags and not allow_empty:
        raise ValidationError("At least one tag ID is required")
    if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise ValidationError("Tag IDs must be non-empty strings", {"tags": tags})
    return tags


def _validate_template_signers(
    signers: list[dict[str, Any]], require_id: bool, *, estimate: bool = False
) -> None:
    allowed = _TEMPLATE_ESTIMATE_SIGNER_FIELDS if estimate else _TEMPLATE_SIGNER_FIELDS
    for signer in signers:
        if not isinstance(signer, dict):
            raise ValidationError("Template signers must be objects")
        unknown = signer.keys() - allowed
        if unknown:
            raise ValidationError(f"Unknown template signer fields: {', '.join(sorted(unknown))}")
        if not isinstance(signer.get("role_id"), str) or not signer["role_id"]:
            raise ValidationError("Template signer role_id is required")
        if require_id and (not isinstance(signer.get("id"), str) or not signer["id"]):
            raise ValidationError("Template signer id is required")
        verification = signer.get("verification_method")
        if verification is not None and (
            not isinstance(verification, str) or verification not in _VERIFICATION_METHODS
        ):
            raise ValidationError("Invalid template signer verification_method")
        notifications = signer.get("notification_methods")
        if notifications is not None and (
            not isinstance(notifications, list)
            or any(
                not isinstance(method, str) or method not in _NOTIFICATION_METHODS
                for method in notifications
            )
        ):
            raise ValidationError("Invalid template signer notification_methods")
        step = signer.get("step")
        if step is not None and (not isinstance(step, int) or isinstance(step, bool) or step < 1):
            raise ValidationError("Template signer step must be a positive integer")
