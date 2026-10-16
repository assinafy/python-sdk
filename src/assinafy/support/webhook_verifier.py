from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import time
from collections.abc import Mapping
from typing import Any

#: Default replay window, in seconds, for :meth:`WebhookVerifier.verify_delivery`.
DEFAULT_TOLERANCE_SECONDS = 300


class WebhookVerifier:
    """Webhook signature verification and payload parsing.

    **Signatures.** An endpoint created or updated with
    ``signing_enabled: true`` signs every delivery following the
    `Standard Webhooks <https://www.standardwebhooks.com>`_ specification. Each
    request carries three headers:

    ``webhook-id``
        Message ID, identical on every attempt of the same event to the same
        endpoint. Use it to deduplicate.
    ``webhook-timestamp``
        Unix timestamp (seconds) of the attempt.
    ``webhook-signature``
        One or more space-separated ``v1,<base64 signature>`` entries.

    Construct the verifier with the endpoint's ``whsec_...`` secret (from
    ``client.webhooks.get_endpoint_secret()``) and call :meth:`verify_delivery`
    with the **raw** request body and the request headers::

        verifier = WebhookVerifier("whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
        if not verifier.verify_delivery(raw_body, request.headers):
            return 401

    Each endpoint has its own secret; use one verifier per endpoint.

    **Envelope.** Every webhook body has this top-level shape::

        {
          "id": 987,                # internal activity id
          "event": "document_ready",
          "message": null,          # human-readable, may contain placeholders
          "payload": null,          # event-specific params (object|null)
          "origin": {"ip": "192.0.2.1", "user-agent": "example-agent/1.0"},
          "created_at": 1705312200, # unix seconds
          "subject": {"id": "actor-id", "type": "User"},
          "object": {"id": "document-id", "type": "Document"},
          "account_id": "account-id"
        }

    Use :meth:`get_event_type`, :meth:`get_event_payload`,
    :meth:`get_event_subject`, and :meth:`get_event_object` to read these fields.
    """

    def __init__(self, webhook_secret: str | None = None) -> None:
        self._webhook_secret = webhook_secret

    def verify_delivery(
        self,
        payload: bytes | str,
        headers: Mapping[str, str],
        *,
        tolerance: float = DEFAULT_TOLERANCE_SECONDS,
    ) -> bool:
        """Verify a Standard Webhooks signature and reject replayed deliveries.

        Computes ``base64(HMAC-SHA256(key, "{webhook-id}.{webhook-timestamp}.{body}"))``
        where ``key`` is the base64-decoded part of the secret after
        ``whsec_``, and accepts the request when any ``v1`` entry of
        ``webhook-signature`` matches in constant time and
        ``webhook-timestamp`` is within ``tolerance`` seconds of the local
        clock. Header names are matched case-insensitively.

        ``payload`` must be the body exactly as received; re-serialized JSON
        does not verify. Returns ``False`` when no secret is configured, the
        secret is not valid base64, or any header is missing or malformed.
        """
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, int | float)
            or not math.isfinite(tolerance)
            or tolerance <= 0
        ):
            raise ValueError("tolerance must be a finite positive number of seconds")
        if not self._webhook_secret:
            return False
        lowered = {str(name).lower(): value for name, value in headers.items()}
        message_id = lowered.get("webhook-id")
        timestamp = lowered.get("webhook-timestamp")
        signatures = lowered.get("webhook-signature")
        if not message_id or not timestamp or not signatures:
            return False
        try:
            sent_at = int(timestamp)
            key = base64.b64decode(self._webhook_secret.removeprefix("whsec_"), validate=True)
        except (ValueError, binascii.Error):
            return False
        if not key or abs(time.time() - sent_at) > tolerance:
            return False

        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        signed = f"{message_id}.{timestamp}.".encode() + raw
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest())
        return any(
            version == "v1"
            and candidate.isascii()
            and hmac.compare_digest(expected, candidate.encode("ascii"))
            for version, _, candidate in (entry.partition(",") for entry in signatures.split())
        )

    def verify(self, payload: bytes | str, signature: str) -> bool:
        """Legacy check: constant-time compare ``hex(HMAC-SHA256(secret, payload))``.

        Kept for receivers written against earlier SDK releases, which
        expected a hex digest of the body alone. Deliveries from endpoints with
        ``signing_enabled`` use the Standard Webhooks scheme instead; verify
        those with :meth:`verify_delivery`. Returns ``False`` when no secret is
        configured or ``signature`` is empty.
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
        return provided.isascii() and hmac.compare_digest(expected, provided)

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
