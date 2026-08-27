from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ..errors import ValidationError
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


class WebhookResource(BaseResource):
    """Webhook subscription, event-type discovery, and dispatch history.

    A workspace has a single webhook subscription. There is no ``DELETE``
    endpoint for it in the documented API — use :meth:`inactivate` to stop
    delivery without losing the configured URL/events.
    """

    def register(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/webhooks/subscriptions`` — upsert subscription.

        ``payload`` requires ``url`` and ``email``. Since a workspace has a
        single subscription, an omitted ``events`` or ``is_active`` is filled in
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
        if not isinstance(payload, dict):
            raise ValidationError("Webhook payload must be a mapping")
        unknown = payload.keys() - {"url", "email", "events", "is_active"}
        if unknown:
            raise ValidationError(f"Unknown webhook fields: {', '.join(sorted(unknown))}")
        _validate_webhook_url(payload.get("url"))
        validate_email(payload.get("email"), "Webhook email")
        if "events" in payload and (
            not isinstance(payload["events"], list)
            or any(not isinstance(event, str) or not event for event in payload["events"])
        ):
            raise ValidationError("Webhook events must be a list of event names")
        if "is_active" in payload and not isinstance(payload["is_active"], bool):
            raise ValidationError("Webhook is_active must be boolean")

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
        """``GET /accounts/{account_id}/webhooks/subscriptions`` — read the subscription.

        Returns ``None`` if the endpoint responds with 404. The live API returns
        a 200 envelope with the configured fields when a subscription exists.

        Example response (``data`` envelope unwrapped)::

            {
              "events": ["document_ready", "document_prepared"],
              "is_active": true,
              "url": "https://example.com/webhooks/assinafy",
              "email": "ops@example.com",
              "updated_at": "2026-06-05T20:50:55Z"
            }
        """
        acc_id = self._account_id(account_id)
        return self._call_optional(
            "Failed to fetch webhook subscription",
            lambda: self._http.get(f"accounts/{acc_id}/webhooks/subscriptions"),
        )

    def inactivate(self, account_id: str | None = None) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/webhooks/inactivate`` — stop delivery.

        Soft-disables the subscription (sets ``is_active`` to ``false``) while
        preserving the configured ``url``/``events``. This is the documented way
        to "remove" a webhook; re-enable it by calling :meth:`register` again.

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


def _validate_webhook_url(value: Any) -> None:
    if not isinstance(value, str):
        raise ValidationError("Webhook URL must be an absolute HTTP(S) URL")
    try:
        parsed = urlsplit(value)
    except ValueError as err:
        raise ValidationError("Webhook URL must be an absolute HTTP(S) URL") from err
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("Webhook URL must be an absolute HTTP(S) URL")
