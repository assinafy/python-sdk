from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
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

        ``payload`` requires ``url`` and ``email``. ``events`` defaults to a
        curated subset (:data:`_DEFAULT_EVENTS`) when omitted — pass an explicit
        list (see :meth:`list_event_types`) for full control. ``is_active``
        defaults to ``True``.

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
        if not payload.get("url"):
            raise ValidationError("Webhook URL is required")
        if not payload.get("email"):
            raise ValidationError("Webhook email is required")

        acc_id = self._account_id(account_id)
        events = payload.get("events")
        body = {
            "url": payload["url"],
            "email": payload["email"],
            "events": events if events else _DEFAULT_EVENTS,
            "is_active": payload.get("is_active", True),
        }

        self._logger.info("Registering webhook", {"url": payload["url"]})
        return self._call(
            "Failed to register webhook",
            lambda: self._http.put(
                f"accounts/{acc_id}/webhooks/subscriptions", json=body
            ),
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
        return self._call(
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

        ``params`` accepts ``event``, ``delivered`` (bool), ``from`` / ``to``
        (Unix-second timestamps), and standard pagination keys (``page``,
        ``per_page``). Returns ``{"data": [...], "meta": {...}}``.

        Example response (``data`` envelope unwrapped, ``meta`` from
        ``x-pagination-*`` headers)::

            {"data": [
                {"id": 42, "event": "document_ready", "delivered": true,
                 "response_status": 200, "created_at": "2026-06-05T20:50:55Z"}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
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
        circuit breaker pauses delivery). ``dispatch_id`` is the ``id`` from
        :meth:`list_dispatches`.

        Example response (``data`` envelope unwrapped)::

            {"id": 42, "event": "document_ready", "delivered": true,
             "response_status": 200}
        """
        acc_id = self._account_id(account_id)
        did = self._require_id(dispatch_id, "Dispatch ID")
        return self._call(
            "Failed to retry webhook dispatch",
            lambda: self._http.post(f"accounts/{acc_id}/webhooks/{did}/retry"),
        )
