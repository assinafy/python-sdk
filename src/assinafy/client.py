from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from .errors import ValidationError
from .resources.assignments import AssignmentResource
from .resources.authentication import AuthenticationResource
from .resources.documents import DocumentResource
from .resources.fields import FieldResource
from .resources.signer_documents import SignerDocumentResource
from .resources.signers import SignerResource
from .resources.tags import TagResource
from .resources.templates import TemplateResource
from .resources.webhooks import WebhookResource
from .support.webhook_verifier import WebhookVerifier
from .types import Logger
from .utils import create_noop_logger

_SDK_VERSION = "1.3.0"
_DEFAULT_BASE_URL = "https://api.assinafy.com.br/v1"
_USER_AGENT = f"assinafy-python-sdk/{_SDK_VERSION}"


class AssinafyClient:
    """Top-level entry point for the Assinafy API.

    All resources hang off this client (``client.documents``, ``client.signers``,
    etc.). The client is synchronous, backed by ``httpx.Client``, and is safe to
    use as a context manager.

    Args:
        api_key: API key sent as the ``X-Api-Key`` header. Preferred.
        token: Access token sent as ``Authorization: Bearer ...``. Used when
            ``api_key`` is not provided.
        account_id: Workspace/account ID used as the default for account-scoped
            methods (e.g. ``documents.list``). May be overridden per call.
        base_url: API base URL. Defaults to ``https://api.assinafy.com.br/v1``.
        webhook_secret: Shared secret used by :class:`WebhookVerifier`.
        timeout: Per-request timeout in seconds.
        logger: Optional ``Logger``-shaped object (``debug``/``info``/``warning``
            /``error`` methods). Defaults to a no-op logger.
    """

    def __init__(
        self,
        api_key: str | None = None,
        token: str | None = None,
        account_id: str | None = None,
        base_url: str | None = None,
        webhook_secret: str | None = None,
        timeout: float = 30.0,
        logger: Logger | None = None,
    ) -> None:
        self._logger: Logger = logger or create_noop_logger()

        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if api_key:
            headers["X-Api-Key"] = api_key
        elif token:
            headers["Authorization"] = f"Bearer {token}"

        self._http = httpx.Client(
            base_url=(base_url or _DEFAULT_BASE_URL).rstrip("/") + "/",
            timeout=timeout,
            headers=headers,
        )

        self.authentication = AuthenticationResource(self._http, None, self._logger)
        self.documents = DocumentResource(self._http, account_id, self._logger)
        self.signers = SignerResource(self._http, account_id, self._logger)
        self.signer_documents = SignerDocumentResource(self._http, account_id, self._logger)
        self.assignments = AssignmentResource(self._http, account_id, self._logger)
        self.webhooks = WebhookResource(self._http, account_id, self._logger)
        self.templates = TemplateResource(self._http, account_id, self._logger)
        self.tags = TagResource(self._http, account_id, self._logger)
        self.fields = FieldResource(self._http, account_id, self._logger)
        self.webhook_verifier = WebhookVerifier(webhook_secret)

    def upload_and_request_signatures(
        self,
        source: dict[str, Any],
        signers: list[dict[str, Any]],
        message: str | None = None,
        wait_for_ready: bool = True,
        expires_at: str | None = None,
        copy_receivers: list[str] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload a PDF, create signers, and start a virtual signature workflow.

        Convenience helper that chains three documented endpoints:

        1. ``POST /accounts/{account_id}/documents`` to upload the PDF
        2. ``POST /accounts/{account_id}/signers`` for each signer dict
        3. ``POST /documents/{document_id}/assignments`` with ``method=virtual``

        Args:
            source: Either ``{"file_path": "..."}`` or
                ``{"buffer": b"...", "file_name": "..."}``.
            signers: List of signer payloads (``full_name`` + ``email`` or
                ``whatsapp_phone_number``).
            message: Optional message included in signer notifications.
            wait_for_ready: If ``True`` (default), poll ``documents.get`` until
                the document leaves ``uploaded`` / ``metadata_processing``.
            expires_at: Optional ISO 8601 expiration timestamp.
            copy_receivers: Optional list of email addresses to copy on the
                signature invitation.
            account_id: Override the client's default account ID for this call.

        Returns:
            ``{"document": ..., "assignment": ..., "signer_ids": [...]}``.
        """
        if not signers:
            raise ValidationError("At least one signer is required")

        self._logger.info(
            "Starting upload + signature workflow", {"signer_count": len(signers)}
        )

        document = self.documents.upload(
            source, {"account_id": account_id} if account_id else None
        )
        if wait_for_ready:
            self.documents.wait_until_ready(document["id"])

        signer_ids = [
            self.signers.create(signer, account_id)["id"] for signer in signers
        ]

        assignment_payload: dict[str, Any] = {"method": "virtual", "signers": signer_ids}
        if message is not None:
            assignment_payload["message"] = message
        if expires_at is not None:
            assignment_payload["expires_at"] = expires_at
        if copy_receivers is not None:
            assignment_payload["copy_receivers"] = copy_receivers

        assignment = self.assignments.create(document["id"], assignment_payload)
        self._logger.info(
            "Upload + signature workflow completed", {"document_id": document["id"]}
        )
        return {"document": document, "assignment": assignment, "signer_ids": signer_ids}

    def get_http_client(self) -> httpx.Client:
        """Return the underlying ``httpx.Client``. Useful for advanced use only."""
        return self._http

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> AssinafyClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
