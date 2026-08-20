from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from ._version import __version__
from .errors import AssinafyError, ValidationError
from .resources.accounts import AccountResource
from .resources.assignments import AssignmentResource
from .resources.authentication import AuthenticationResource
from .resources.documents import DocumentResource
from .resources.fields import FieldResource
from .resources.signer_documents import SignerDocumentResource
from .resources.signers import SignerResource
from .resources.tags import TagResource
from .resources.templates import TemplateResource
from .resources.users import UserResource
from .resources.webhooks import WebhookResource
from .support.webhook_verifier import WebhookVerifier
from .types import Logger
from .utils import create_noop_logger

_DEFAULT_BASE_URL = "https://api.assinafy.com.br/v1"
_USER_AGENT = f"assinafy-python-sdk/{__version__}"


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

        for name, value in (("api_key", api_key), ("token", token), ("account_id", account_id)):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValidationError(f"{name} must be a non-empty string")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not timeout > 0:
            raise ValidationError("timeout must be a positive number")

        resolved_base_url = _DEFAULT_BASE_URL if base_url is None else base_url
        if not isinstance(resolved_base_url, str) or not resolved_base_url.strip():
            raise ValidationError("base_url must be a non-empty HTTP(S) URL")
        try:
            parsed_base_url = httpx.URL(resolved_base_url)
        except (TypeError, httpx.InvalidURL) as exc:
            raise ValidationError("base_url must be a non-empty HTTP(S) URL") from exc
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.host:
            raise ValidationError("base_url must be a non-empty HTTP(S) URL")

        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if api_key:
            headers["X-Api-Key"] = api_key
        elif token:
            headers["Authorization"] = f"Bearer {token}"

        self._http = httpx.Client(
            base_url=resolved_base_url.rstrip("/") + "/",
            timeout=timeout,
            headers=headers,
        )

        self.authentication = AuthenticationResource(self._http, None, self._logger)
        self.accounts = AccountResource(self._http, account_id, self._logger)
        self.users = UserResource(self._http, account_id, self._logger)
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
        wait_timeout: float = 30.0,
        wait_poll_interval: float = 2.0,
        expires_at: str | None = None,
        copy_receivers: list[str] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload a PDF, create signers, and start a virtual signature workflow.

        Convenience helper that chains three documented endpoints:

        1. ``POST /accounts/{account_id}/documents`` to upload the PDF
        2. ``POST /accounts/{account_id}/signers`` for each signer dict
        3. ``POST /documents/{document_id}/assignments`` with ``method=virtual``

        The three calls are not transactional: if signer creation or assignment
        creation fails partway through, the uploaded document and any signers
        already created are left in place (no automatic rollback). Inspect the
        raised error's context or call the individual resource methods directly
        if you need finer-grained control or cleanup.

        Args:
            source: Either ``{"file_path": "..."}`` or
                ``{"buffer": b"...", "file_name": "..."}``.
            signers: List of signer payloads (``full_name`` + ``email`` or
                ``whatsapp_phone_number``).
            message: Optional message included in signer notifications.
            wait_for_ready: If ``True`` (default), poll ``documents.get`` until
                the document leaves ``uploaded`` / ``metadata_processing``.
            wait_timeout: Forwarded to ``documents.wait_until_ready`` when
                ``wait_for_ready`` is ``True``.
            wait_poll_interval: Forwarded to ``documents.wait_until_ready`` when
                ``wait_for_ready`` is ``True``.
            expires_at: Optional ISO 8601 expiration timestamp.
            copy_receivers: Optional signer IDs that receive a copy of the
                completed document.
            account_id: Override the client's default account ID for this call.

        Returns:
            A mapping with ``document`` using the complete
            :class:`DocumentResource` shape, ``assignment`` using the complete
            :class:`AssignmentResource` shape, and ``signer_ids`` as the exact
            list of created signer ID strings.
        """
        if (
            not isinstance(signers, list)
            or not signers
            or any(not isinstance(signer, dict) for signer in signers)
        ):
            raise ValidationError("At least one signer is required")

        self._logger.info("Starting upload + signature workflow", {"signer_count": len(signers)})

        document = self.documents.upload(source, account_id)
        document_id = _response_id(document, "Document upload")
        if wait_for_ready:
            document = self.documents.wait_until_ready(
                document_id, timeout=wait_timeout, poll_interval=wait_poll_interval
            )
            document_id = _response_id(document, "Document readiness")

        signer_ids = [
            _response_id(self.signers.create(signer, account_id), "Signer creation")
            for signer in signers
        ]

        assignment_payload: dict[str, Any] = {"method": "virtual", "signers": signer_ids}
        if message is not None:
            assignment_payload["message"] = message
        if expires_at is not None:
            assignment_payload["expires_at"] = expires_at
        if copy_receivers is not None:
            assignment_payload["copy_receivers"] = copy_receivers

        assignment = self.assignments.create(document_id, assignment_payload)
        self._logger.info("Upload + signature workflow completed", {"document_id": document_id})
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


def _response_id(payload: dict[str, Any], operation: str) -> str:
    resource_id = payload.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        raise AssinafyError(f"{operation}: API response is missing a resource ID")
    return resource_id
