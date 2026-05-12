from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


class WebhookVerifier:
    """HMAC-SHA256 webhook payload verifier.

    The Assinafy API delivers webhook events as documented at
    https://api.assinafy.com.br/v1/docs (see "Payload Reference"). The
    signature header name / scheme is configured per-account with Assinafy.
    This helper assumes the common pattern: ``hex(hmac_sha256(secret, body))``
    sent in a request header that the caller passes to :meth:`verify`.

    If your account uses a different scheme, subclass and override
    :meth:`verify` rather than reimplementing the wire reads.
    """

    def __init__(self, webhook_secret: str | None = None) -> None:
        self._webhook_secret = webhook_secret

    def verify(self, payload: bytes | str, signature: str) -> bool:
        """Constant-time compare HMAC-SHA256(secret, payload) against signature."""
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
        """Parse the JSON envelope and return the top-level event dict, or None."""
        try:
            text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def get_event_type(self, event: dict[str, Any] | None) -> str | None:
        """Return the documented ``event`` field (falling back to ``type``)."""
        if not event or not isinstance(event, dict):
            return None
        return event.get("event") or event.get("type")

    def get_event_data(self, event: dict[str, Any] | None) -> dict[str, Any]:
        """Return the documented ``data`` field (falling back to ``object``)."""
        if not event or not isinstance(event, dict):
            return {}
        result = event.get("data") or event.get("object")
        return result if isinstance(result, dict) else {}
