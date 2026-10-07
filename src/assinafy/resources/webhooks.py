from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..errors import AssinafyError, ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params, validate_email
from .base import BaseResource

# Curated convenience default used when ``register`` is called without an
# explicit ``events`` list. Pass your own ``events`` (discoverable at runtime via
# :meth:`WebhookResource.list_event_types`) to control the full subscription.
_DEFAULT_EVENTS = [
    "document_ready",
    "document_prepared",
    "signer_signed_document",
    "signer_rejected_document",
    "document_processing_failed",
]

_ENDPOINT_FIELDS = {"url", "email", "events", "name", "is_active", "signing_enabled"}


class WebhookResource(BaseResource):
    """Webhook endpoints, signing secrets, event-type discovery and delivery history.

    An account can register 1 webhook endpoint, or up to 3 on paid plans. Each
    endpoint has its own URL, event list and signing setting, and every active
    endpoint subscribed to an event receives it. Manage endpoints with
    :meth:`list_endpoints`, :meth:`create_endpoint`, :meth:`get_endpoint`,
    :meth:`update_endpoint` and :meth:`delete_endpoint`; read or rotate the
    Standard Webhooks signing secret with :meth:`get_endpoint_secret` and
    :meth:`rotate_endpoint_secret`.

    The older subscription calls (:meth:`register`, :meth:`get`,
    :meth:`inactivate`) still work and act on the account's oldest endpoint.

    Every endpoint method returns (or lists) this endpoint shape, ``data``
    envelope unwrapped::

        {"id": "65f1c2a9b3e4d5f60718293a4b5c6d7e", "name": "ERP",
         "url": "https://example.com/webhooks/assinafy",
         "email": "ops@example.com",
         "events": ["document_ready", "signer_signed_document"],
         "is_active": true, "signing_enabled": true,
         "created_at": "2026-10-01T12:00:00Z",
         "updated_at": "2026-10-01T12:00:00Z"}
    """

    def register(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/webhooks/subscriptions`` — upsert the oldest endpoint.

        Updates the account's oldest webhook endpoint, creating it when the
        account has none. Accounts with several endpoints use
        :meth:`update_endpoint`. ``payload`` requires ``url`` and ``email``. An
        omitted ``events`` or ``is_active`` is filled in
        from the *current* subscription (so a partial call — e.g. only rotating
        ``url`` — can't silently reactivate an inactivated subscription or
        collapse a custom event list). If no subscription exists yet, ``events``
        defaults to a curated subset (:data:`_DEFAULT_EVENTS`) and ``is_active``
        defaults to ``True``. Pass an explicit ``events=[]`` to genuinely clear
        all events (it is not treated as "omitted").

        Example request body (JSON)::

            {
              "url": "https://example.com/webhooks/assinafy",
              "email": "ops@example.com",
              "events": ["document_ready", "signer_signed_document"],
              "is_active": true
            }

        Example response (``data`` envelope unwrapped)::

            {
              "events": ["document_ready", "signer_signed_document"],
              "is_active": true,
              "url": "https://example.com/webhooks/assinafy",
              "email": "ops@example.com",
              "updated_at": "2026-06-05T20:50:55Z"
            }
        """
        _validate_webhook_fields(
            payload, {"url", "email", "events", "is_active"}, required=("url", "email")
        )

        acc_id = self._account_id(account_id)
        events = payload.get("events")
        is_active = payload.get("is_active")
        if events is None or is_active is None:
            current = self.get(acc_id)
            if events is None:
                events = (current or {}).get("events") if current else _DEFAULT_EVENTS
            if is_active is None:
                is_active = (current or {}).get("is_active", True) if current else True

        body = {
            "url": payload["url"],
            "email": payload["email"],
            "events": events,
            "is_active": is_active,
        }

        self._logger.info("Registering webhook subscription")
        return self._call_dict(
            "Failed to register webhook",
            lambda: self._http.put(f"accounts/{acc_id}/webhooks/subscriptions", json=body),
        )

    def get(self, account_id: str | None = None) -> dict[str, Any] | None:
        """``GET /accounts/{account_id}/webhooks/subscriptions`` — read the oldest endpoint.

        Accounts with several endpoints use :meth:`list_endpoints`. Returns
        ``None`` when the API answers 404; otherwise the configured fields.

        Example response (``data`` envelope unwrapped)::

            {
              "events": ["document_ready", "document_prepared"],
              "is_active": true,
              "url": "https://example.com/webhooks/assinafy",
              "email": "ops@example.com",
              "updated_at": "2026-06-05T20:50:55Z"
            }

        Request body: none.
        """
        acc_id = self._account_id(account_id)
        return self._call_optional(
            "Failed to fetch webhook subscription",
            lambda: self._http.get(f"accounts/{acc_id}/webhooks/subscriptions"),
        )

    def inactivate(self, account_id: str | None = None) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/webhooks/inactivate`` — stop delivery.

        Soft-disables the account's oldest endpoint (sets ``is_active`` to
        ``false``) while preserving its ``url``/``events``; re-enable it by
        calling :meth:`register` again. To remove an endpoint and free its slot,
        use :meth:`delete_endpoint`.

        Example response (``data`` envelope unwrapped)::

            {
              "events": ["document_ready", "document_prepared"],
              "is_active": false,
              "url": "https://example.com/webhooks/assinafy",
              "email": "ops@example.com",
              "updated_at": "2026-06-05T20:50:55Z"
            }
        """
        acc_id = self._account_id(account_id)
        self._logger.info("Inactivating webhook subscription")
        return self._call_dict(
            "Failed to inactivate webhook subscription",
            lambda: self._http.put(f"accounts/{acc_id}/webhooks/inactivate"),
        )

    def list_event_types(self) -> list[dict[str, Any]]:
        """``GET /webhooks/event-types`` — global catalog of event types.

        Example response (``data`` envelope unwrapped)::

            [
              {"id": "document_uploaded",
               "description": "Triggered when the User has uploaded a Document"},
              {"id": "document_ready",
               "description": "Triggered when the last Signer signs the Document"}
            ]

        Request body: none.
        """
        return self._call_plain_list(
            "Failed to list webhook event types",
            lambda: self._http.get("webhooks/event-types"),
        )

    def list_dispatches(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/webhooks`` — webhook delivery history.

        ``params`` accepts ``event`` (an event-type name), ``delivered``
        (Python ``True``/``False``, sent as the documented ``true``/``false``
        strings), ``from`` / ``to`` (Unix-second timestamps), and standard
        pagination keys (``page``, ``per_page``). Returns
        ``{"data": [...], "meta": {...}}``.

        Example response (``data`` envelope unwrapped, ``meta`` from
        ``x-pagination-*`` headers)::

            {"data": [
                {"id": "a1b2c3d4e5f6...", "event": "document_ready",
                 "activity_id": 456, "endpoint": "https://example.com/webhook",
                 "payload": {"event": "document_ready", "id": 456,
                             "object": {"id": "abc123", "type": "Document"},
                             "subject": {"id": "def456", "type": "User"}},
                 "delivered": true, "http_status": 200, "response_body": "OK",
                 "error": null, "created_at": "2026-06-05T20:50:55Z",
                 "updated_at": "2026-06-05T20:50:56Z"}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}

        Request body: none.
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params if params is not None else {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list webhook dispatches",
            lambda: self._http.get(f"accounts/{acc_id}/webhooks", params=cleaned),
        )

    def retry_dispatch(
        self,
        dispatch_id: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/webhooks/{dispatch_id}/retry``.

        Forces redelivery of a single webhook dispatch (useful after the
        circuit breaker pauses delivery). ``dispatch_id`` is the hex-string
        ``id`` from :meth:`list_dispatches`. Returns the newly created webhook
        entry (same shape as a ``list_dispatches`` item).

        Example response (``data`` envelope unwrapped)::

            {"resource": "activity_dispatching_history",
             "id": "a1b2c3d4e5f6...", "event": "document_ready",
             "activity_id": 456, "endpoint": "https://example.com/webhook",
             "delivered": true, "http_status": 200, "response_body": "OK",
             "error": null, "created_at": "2026-06-05T20:50:55Z",
             "updated_at": "2026-06-05T20:50:56Z"}
        """
        acc_id = self._account_id(account_id)
        did = self._path_id(dispatch_id, "Dispatch ID")
        return self._call_dict(
            "Failed to retry webhook dispatch",
            lambda: self._http.post(f"accounts/{acc_id}/webhooks/{did}/retry"),
        )

    def list_endpoints(self, account_id: str | None = None) -> list[dict[str, Any]]:
        """``GET /accounts/{account_id}/webhooks/endpoints`` — list endpoints, oldest first.

        Request body: none. Each item has the endpoint shape shown on the
        class docstring.

        Example response (``data`` envelope unwrapped)::

            [{"id": "65f1c2a9b3e4d5f60718293a4b5c6d7e", "name": "ERP",
              "url": "https://example.com/webhooks/assinafy",
              "email": "ops@example.com",
              "events": ["document_ready", "signer_signed_document"],
              "is_active": true, "signing_enabled": true,
              "created_at": "2026-10-01T12:00:00Z",
              "updated_at": "2026-10-01T12:00:00Z"}]
        """
        acc_id = self._account_id(account_id)
        return self._call_plain_list(
            "Failed to list webhook endpoints",
            lambda: self._http.get(f"accounts/{acc_id}/webhooks/endpoints"),
        )

    def create_endpoint(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/webhooks/endpoints`` — register an endpoint.

        ``url``, ``email`` and ``events`` are required; ``name``, ``is_active``
        (default ``true``) and ``signing_enabled`` (default ``false``) are
        optional. An account can have 1 endpoint, or up to 3 on paid plans;
        creating one past the limit raises :class:`~assinafy.errors.ApiError`
        with status ``403``, and a ``url`` another endpoint already uses raises
        status ``400``. With ``signing_enabled`` a secret is generated; read it
        with :meth:`get_endpoint_secret`.

        Example request body (JSON)::

            {"url": "https://example.com/webhooks/assinafy",
             "email": "ops@example.com",
             "events": ["document_ready", "signer_signed_document"],
             "name": "ERP", "is_active": true, "signing_enabled": true}

        Example response (``data`` envelope unwrapped)::

            {"id": "65f1c2a9b3e4d5f60718293a4b5c6d7e", "name": "ERP",
             "url": "https://example.com/webhooks/assinafy",
             "email": "ops@example.com",
             "events": ["document_ready", "signer_signed_document"],
             "is_active": true, "signing_enabled": true,
             "created_at": "2026-10-01T12:00:00Z",
             "updated_at": "2026-10-01T12:00:00Z"}
        """
        _validate_webhook_fields(payload, _ENDPOINT_FIELDS, required=("url", "email", "events"))
        acc_id = self._account_id(account_id)
        body = dict(payload)
        self._logger.info("Creating webhook endpoint")
        return self._call_dict(
            "Failed to create webhook endpoint",
            lambda: self._http.post(f"accounts/{acc_id}/webhooks/endpoints", json=body),
        )

    def get_endpoint(self, endpoint_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/webhooks/endpoints/{endpoint_id}`` — read one endpoint.

        Request body: none. Returns the endpoint shape shown on the class
        docstring (``data`` envelope unwrapped)::

            {"id": "65f1c2a9b3e4d5f60718293a4b5c6d7e", "name": "ERP",
             "url": "https://example.com/webhooks/assinafy",
             "email": "ops@example.com", "events": ["document_ready"],
             "is_active": true, "signing_enabled": false,
             "created_at": "2026-10-01T12:00:00Z",
             "updated_at": "2026-10-01T12:00:00Z"}
        """
        path = self._endpoint_path(endpoint_id, account_id)
        return self._call_dict("Failed to fetch webhook endpoint", lambda: self._http.get(path))

    def update_endpoint(
        self,
        endpoint_id: str,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/webhooks/endpoints/{endpoint_id}`` — change an endpoint.

        Only the fields sent are updated. Accepts ``url``, ``email``,
        ``events``, ``name``, ``is_active`` and ``signing_enabled``. Turning
        ``signing_enabled`` on generates a secret when the endpoint has none
        and keeps the current one otherwise; turning it off discards the
        secret.

        Example request body (JSON)::

            {"events": ["document_ready"], "is_active": false}

        Example response (``data`` envelope unwrapped)::

            {"id": "65f1c2a9b3e4d5f60718293a4b5c6d7e", "name": "ERP",
             "url": "https://example.com/webhooks/assinafy",
             "email": "ops@example.com", "events": ["document_ready"],
             "is_active": false, "signing_enabled": true,
             "created_at": "2026-10-01T12:00:00Z",
             "updated_at": "2026-10-02T09:30:00Z"}
        """
        _validate_webhook_fields(payload, _ENDPOINT_FIELDS, required=())
        if not payload:
            raise ValidationError("Webhook endpoint update requires at least one field")
        path = self._endpoint_path(endpoint_id, account_id)
        body = dict(payload)
        self._logger.info("Updating webhook endpoint")
        return self._call_dict(
            "Failed to update webhook endpoint", lambda: self._http.put(path, json=body)
        )

    def delete_endpoint(self, endpoint_id: str, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/webhooks/endpoints/{endpoint_id}`` — remove it.

        Stops delivery to the endpoint and frees its slot. Request body: none.
        The documented response is ``data: []``; the SDK returns ``None``.
        """
        path = self._endpoint_path(endpoint_id, account_id)
        self._logger.info("Deleting webhook endpoint")
        self._call_void("Failed to delete webhook endpoint", lambda: self._http.delete(path))

    def get_endpoint_secret(self, endpoint_id: str, account_id: str | None = None) -> str:
        """``GET /accounts/{account_id}/webhooks/endpoints/{endpoint_id}/secret``.

        Returns the endpoint's Standard Webhooks signing secret
        (``whsec_`` followed by the base64-encoded key), taken from the
        response ``{"secret": "whsec_..."}``. Pass it to
        :class:`~assinafy.support.webhook_verifier.WebhookVerifier` and keep it
        out of logs. The API answers ``400`` when signing is disabled, and the
        operation is not available to OAuth applications. Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"secret": "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"}
        """
        path = self._endpoint_path(endpoint_id, account_id) + "/secret"
        return self._secret("Failed to fetch webhook endpoint secret", lambda: self._http.get(path))

    def rotate_endpoint_secret(self, endpoint_id: str, account_id: str | None = None) -> str:
        """``POST /accounts/{account_id}/webhooks/endpoints/{endpoint_id}/secret/rotate``.

        Replaces the signing secret and returns the new one. The old secret
        stops working immediately: deliveries sent after the rotation are
        signed only with the new secret, so update the receiver right away. The
        API answers ``400`` when signing is disabled, and the operation is not
        available to OAuth applications. Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"secret": "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"}
        """
        path = self._endpoint_path(endpoint_id, account_id) + "/secret/rotate"
        self._logger.info("Rotating webhook endpoint secret")
        return self._secret(
            "Failed to rotate webhook endpoint secret", lambda: self._http.post(path)
        )

    def _endpoint_path(self, endpoint_id: str, account_id: str | None) -> str:
        acc_id = self._account_id(account_id)
        eid = self._path_id(endpoint_id, "Endpoint ID")
        return f"accounts/{acc_id}/webhooks/endpoints/{eid}"

    def _secret(self, label: str, request_fn: Callable[[], httpx.Response]) -> str:
        secret = self._call_dict(label, request_fn).get("secret")
        if not isinstance(secret, str) or not secret:
            raise AssinafyError(f"{label}: API returned no secret")
        return secret


def _validate_webhook_url(value: Any) -> None:
    if not isinstance(value, str):
        raise ValidationError("Webhook URL must be an absolute HTTP(S) URL")
    try:
        parsed = urlsplit(value)
    except ValueError as err:
        raise ValidationError("Webhook URL must be an absolute HTTP(S) URL") from err
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("Webhook URL must be an absolute HTTP(S) URL")


def _validate_webhook_fields(payload: Any, allowed: set[str], *, required: tuple[str, ...]) -> None:
    """Validate a webhook subscription or endpoint body before it is sent."""
    if not isinstance(payload, dict):
        raise ValidationError("Webhook payload must be a mapping")
    unknown = payload.keys() - allowed
    if unknown:
        raise ValidationError(f"Unknown webhook fields: {', '.join(sorted(unknown))}")
    for key in required:
        if key not in payload:
            raise ValidationError(f"Webhook {key} is required")
    if "url" in payload:
        _validate_webhook_url(payload["url"])
    if "email" in payload:
        validate_email(payload["email"], "Webhook email")
    if "events" in payload and (
        not isinstance(payload["events"], list)
        or any(not isinstance(event, str) or not event for event in payload["events"])
    ):
        raise ValidationError("Webhook events must be a list of event names")
    if "name" in payload and (not isinstance(payload["name"], str) or not payload["name"].strip()):
        raise ValidationError("Webhook name must be a non-empty string")
    for flag in ("is_active", "signing_enabled"):
        if flag in payload and not isinstance(payload[flag], bool):
            raise ValidationError(f"Webhook {flag} must be boolean")
