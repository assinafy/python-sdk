from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource

_DEFAULT_EVENTS = [
    "document_ready",
    "document_prepared",
    "signer_signed_document",
    "signer_rejected_document",
    "document_processing_failed",
]


class WebhookResource(BaseResource):
    """Webhook subscription, event-type discovery, and dispatch history."""

    def register(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/webhooks/subscriptions`` — upsert subscription.

        ``payload`` requires ``url`` and ``email``. ``events`` defaults to a
        common subset when omitted; pass a list to override. ``is_active``
        defaults to ``True``.
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
        """``GET /accounts/{account_id}/webhooks/subscriptions``.

        The API returns 200 with empty fields when nothing is configured; this
        method also returns ``None`` if the endpoint ever responds with 404.
        """
        acc_id = self._account_id(account_id)
        return self._call_optional(
            "Failed to fetch webhook subscription",
            lambda: self._http.get(f"accounts/{acc_id}/webhooks/subscriptions"),
        )

    def delete(self, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/webhooks/subscriptions``."""
        acc_id = self._account_id(account_id)
        self._logger.info("Deleting webhook subscription")
        return self._call_void(
            "Failed to delete webhook subscription",
            lambda: self._http.delete(f"accounts/{acc_id}/webhooks/subscriptions"),
        )

    def inactivate(self, account_id: str | None = None) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/webhooks/inactivate`` — soft-disable."""
        acc_id = self._account_id(account_id)
        self._logger.info("Inactivating webhook subscription")
        return self._call(
            "Failed to inactivate webhook subscription",
            lambda: self._http.put(f"accounts/{acc_id}/webhooks/inactivate"),
        )

    def list_event_types(self) -> list[dict[str, Any]]:
        """``GET /webhooks/event-types`` — global catalog of event types."""
        return self._call(
            "Failed to list webhook event types",
            lambda: self._http.get("webhooks/event-types"),
        )

    def list_dispatches(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/webhooks`` — webhook delivery history.

        ``params`` accepts ``event``, ``delivered`` (bool), and standard
        pagination keys.
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
        """``POST /accounts/{account_id}/webhooks/{dispatch_id}/retry``."""
        acc_id = self._account_id(account_id)
        did = self._require_id(dispatch_id, "Dispatch ID")
        return self._call(
            "Failed to retry webhook dispatch",
            lambda: self._http.post(f"accounts/{acc_id}/webhooks/{did}/retry"),
        )
