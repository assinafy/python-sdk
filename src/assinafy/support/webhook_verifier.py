from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


class WebhookVerifier:
    """Webhook payload parsing and (optional) HMAC-SHA256 verification.

    **Envelope.** Per the documented Payload Reference, every webhook body has
    this top-level shape::

        {
          "id": 987,                # internal activity id (use to dedup)
          "event": "document_ready",
          "message": null,          # human-readable, may contain placeholders
          "payload": null,          # event-specific params (object|null)
          "origin": {"ip": "...", "user-agent": "..."},
          "created_at": 1705312200, # unix seconds
          "subject": {...},         # entity that performed the action (+ "type")
          "object": {...},          # entity acted upon (+ "type")
          "account_id": "..."
        }

    Use :meth:`get_event_type`, :meth:`get_event_payload`,
    :meth:`get_event_subject`, and :meth:`get_event_object` to read these fields.

    **Signatures.** The documented Delivery Contract specifies the HTTP method,
    ``Content-Type``, retry, and circuit-breaker behavior, but it does **not**
    define any signature header or shared-secret scheme. :meth:`verify` is
    therefore provided only for accounts that have separately arranged an
    HMAC-SHA256 scheme with Assinafy; it assumes the common pattern
    ``hex(hmac_sha256(secret, body))`` sent in a request header that you pass in.
    If your account uses a different scheme, subclass and override
    :meth:`verify`. With no shared secret configured, :meth:`verify` always
    returns ``False``.
    """

    def __init__(self, webhook_secret: str | None = None) -> None:
        self._webhook_secret = webhook_secret

    def verify(self, payload: bytes | str, signature: str) -> bool:
        """Constant-time compare ``HMAC-SHA256(secret, payload)`` against ``signature``.

        Returns ``False`` when no secret is configured or ``signature`` is empty.
        See the class docstring: the public API does not document a signature
        mechanism, so this is only meaningful for accounts with a negotiated
        HMAC scheme.
        """
        if not self._webhook_secret or not signature:
            return False

        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        expected = hmac.new(
            self._webhook_secret.encode("utf-8"),
            raw,
            hashlib.sha256,
        ).hexdigest()
        provided = signature.strip()
        return hmac.compare_digest(expected, provided)

    def extract_event(self, payload: bytes | str) -> dict[str, Any] | None:
        """Parse the JSON envelope and return the top-level event dict, or ``None``."""
        try:
            text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def get_event_type(self, event: dict[str, Any] | None) -> str | None:
        """Return the documented top-level ``event`` field (e.g. ``document_ready``)."""
        if not event or not isinstance(event, dict):
            return None
        value = event.get("event")
        return value if isinstance(value, str) else None

    def get_event_payload(self, event: dict[str, Any] | None) -> dict[str, Any]:
        """Return the documented ``payload`` field (event-specific parameters).

        ``payload`` is ``null`` for events that carry no extra parameters; this
        returns ``{}`` in that case.
        """
        if not event or not isinstance(event, dict):
            return {}
        result = event.get("payload")
        return result if isinstance(result, dict) else {}

    def get_event_subject(self, event: dict[str, Any] | None) -> dict[str, Any]:
        """Return the documented ``subject`` entity (who performed the action).

        Includes a ``type`` key (``User``/``Signer``/``Account``/...).
        """
        if not event or not isinstance(event, dict):
            return {}
        result = event.get("subject")
        return result if isinstance(result, dict) else {}

    def get_event_object(self, event: dict[str, Any] | None) -> dict[str, Any]:
        """Return the documented ``object`` entity (what the action was performed on).

        Includes a ``type`` key (``Document``/``Template``/...). For a
        ``Document`` object, ``assignment`` and ``pages`` are expanded inline.
        """
        if not event or not isinstance(event, dict):
            return {}
        result = event.get("object")
        return result if isinstance(result, dict) else {}

    def get_event_data(self, event: dict[str, Any] | None) -> dict[str, Any]:
        """Backward-compatible alias of :meth:`get_event_object`.

        Returns the documented top-level ``object`` entity (the resource the
        event acted on). For the event-specific parameters, use
        :meth:`get_event_payload` instead.
        """
        return self.get_event_object(event)
