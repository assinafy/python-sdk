"""Internal utilities: response envelope handling, logger, query aliases, uploads."""

from __future__ import annotations

import math
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .errors import ApiError, AssinafyError, NetworkError, ValidationError
from .types import NOTIFICATION_METHODS, VERIFICATION_METHODS, Logger

# Pythonic keyword -> documented hyphenated query/body key mapping.
QUERY_PARAM_ALIASES = {
    "per_page": "per-page",
    "signer_access_code": "signer-access-code",
}
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def handle_assinafy_response(response: Any) -> Any:
    """Unwrap the documented ``{status, data, message}`` envelope.

    Returns ``response["data"]`` for 2xx envelopes, raises :class:`ApiError`
    for non-2xx envelopes, and passes through anything that isn't an envelope.
    """
    if isinstance(response, dict) and "status" in response and "data" in response:
        status = response["status"]
        if isinstance(status, int) and 200 <= status < 300:
            return response["data"]
        raise ApiError.from_response(status, response)
    return response


def to_sdk_error(error: Exception, fallback_message: str) -> AssinafyError:
    """Coerce any exception into the SDK's typed error hierarchy."""
    if isinstance(error, AssinafyError):
        return error

    if isinstance(error, httpx.HTTPStatusError):
        try:
            data: Any = error.response.json()
        except ValueError:
            data = None
        return ApiError.from_response(
            error.response.status_code, data, headers=error.response.headers
        )

    if isinstance(error, httpx.RequestError):
        return NetworkError(f"{fallback_message}: {type(error).__name__}")

    return AssinafyError(f"{fallback_message}: {type(error).__name__}")


class _NoopLogger:
    def debug(self, message: str, context: dict[str, Any] | None = None) -> None: ...
    def info(self, message: str, context: dict[str, Any] | None = None) -> None: ...
    def warning(self, message: str, context: dict[str, Any] | None = None) -> None: ...
    def error(self, message: str, context: dict[str, Any] | None = None) -> None: ...


_NOOP_LOGGER: Logger = _NoopLogger()


def create_noop_logger() -> Logger:
    """Return a shared no-op logger that conforms to :class:`Logger`."""
    return _NOOP_LOGGER


def clean_params(
    params: dict[str, Any],
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Drop ``None`` values and apply hyphenated aliases.

    Used to turn Pythonic kwargs like ``per_page=20`` into the documented
    query strings (``per-page=20``) without sending phantom ``key=None``
    pairs.
    """
    if not isinstance(params, dict):
        raise ValidationError("Parameters must be a mapping")
    aliases = aliases or {}
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        wire_key = aliases.get(key, key)
        if wire_key in cleaned:
            raise ValidationError(f"Conflicting parameter aliases for {wire_key}")
        cleaned[wire_key] = value
    return cleaned


def validate_datetime(value: Any, name: str, *, allow_none: bool = False) -> None:
    """Validate an OpenAPI ``date-time`` value without changing it."""
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not _RFC3339_RE.fullmatch(value):
        raise ValidationError(f"{name} must be an RFC 3339 timestamp")
    candidate = value[:-1] + "+00:00" if value[-1] in "Zz" else value
    try:
        datetime.fromisoformat(candidate)
    except ValueError as err:
        raise ValidationError(f"{name} must be an RFC 3339 timestamp") from err


def validate_expiration(value: Any, name: str = "expires_at", *, allow_none: bool = False) -> None:
    """Accept ISO dates, UTC datetimes, and finite Unix seconds without rewriting them.

    The API interprets date-only expirations as 23:59 UTC and checks that the
    expiration is at least one hour in the future. Numeric text is Unix seconds;
    numeric fractions are dropped by the server. Zero and empty text clear expiration.
    """
    if value is None and allow_none:
        return
    if value == "":
        return
    if not isinstance(value, bool) and (
        isinstance(value, (int, float))
        or isinstance(value, str)
        and _NUMBER_RE.fullmatch(value.strip())
    ):
        try:
            number = Decimal(str(value) if isinstance(value, float) else value)
        except InvalidOperation:
            raise ValidationError(f"{name} must be a finite Unix timestamp") from None
        if not number.is_finite():
            raise ValidationError(f"{name} must be a finite Unix timestamp")
        return
    candidate = value
    if isinstance(value, str):
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            candidate = value + "T23:59:00Z"
        elif re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?",
            value,
        ):
            candidate = value + "Z"
    validate_datetime(candidate, name)


def load_file_source(source: dict[str, Any]) -> tuple[bytes, str]:
    """Resolve a ``multipart/form-data`` upload source to ``(bytes, file_name)``.

    Shared by every documented ``file`` upload part — documents and account
    logos. ``source`` carries exactly one of ``file_path`` or ``buffer``;
    ``file_name`` is required alongside a buffer and defaults to the path's
    basename otherwise. Content-specific limits (PDF extension, size caps) are
    the caller's to enforce.
    """
    if not isinstance(source, dict):
        raise ValidationError("source must be a mapping")
    unknown = source.keys() - {"buffer", "file_path", "file_name"}
    if unknown:
        raise ValidationError(f"Unknown source fields: {', '.join(sorted(unknown))}")
    if ("buffer" in source) == ("file_path" in source):
        raise ValidationError("source must contain exactly one of buffer or file_path")
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
        with open(file_path, "rb") as handle:
            buffer = handle.read()
    except OSError as err:
        raise ValidationError(
            "Unable to read upload file", {"file_path": os.fspath(file_path)}
        ) from err
    file_name = source.get("file_name") or os.path.basename(file_path)
    if not isinstance(file_name, str):
        raise ValidationError("file_name must be a string")
    return buffer, file_name


def validate_email(value: Any, name: str = "Email") -> str:
    """Return a syntactically valid email address."""
    if not isinstance(value, str) or not _EMAIL_RE.fullmatch(value):
        raise ValidationError(f"Invalid {name.lower()}", {name.lower(): value})
    return value


def stats_params(granularity: str, month: str | None) -> dict[str, str]:
    """Build monthly/daily KPI query parameters; daily queries require YYYY-MM."""
    if not isinstance(granularity, str) or granularity not in {"monthly", "daily"}:
        raise ValidationError('granularity must be "monthly" or "daily"')
    if month is not None and (
        not isinstance(month, str) or re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None
    ):
        raise ValidationError("month must use YYYY-MM format")
    if granularity == "daily" and month is None:
        raise ValidationError("month is required for daily granularity")
    return {k: v for k, v in {"granularity": granularity, "month": month}.items() if v}


def validate_wait_options(timeout: float, poll_interval: float) -> None:
    """Require finite positive polling durations; raises ValidationError before I/O."""
    for name, value in (("timeout", timeout), ("poll_interval", poll_interval)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValidationError(f"{name} must be greater than zero")


def build_signer_payload(payload: dict[str, Any], require_full_name: bool) -> dict[str, Any]:
    """Build signer fields, omitting None; updates accept empty contact fields to clear them."""
    if not isinstance(payload, dict):
        raise ValidationError("Signer payload must be a mapping")
    allowed = {"full_name", "email", "whatsapp_phone_number", "government_id"}
    unknown = payload.keys() - allowed
    if unknown:
        raise ValidationError(f"Unknown signer fields: {', '.join(sorted(unknown))}")
    full_name = payload.get("full_name")
    if require_full_name and (not isinstance(full_name, str) or not full_name.strip()):
        raise ValidationError("full_name is required")
    if full_name is not None and (not isinstance(full_name, str) or not full_name.strip()):
        raise ValidationError("full_name must be a non-empty string")
    email = payload.get("email")
    if email is not None and (require_full_name or email != ""):
        validate_email(email)
    phone = payload.get("whatsapp_phone_number")
    if (
        phone is not None
        and (require_full_name or phone != "")
        and (not isinstance(phone, str) or not phone.strip())
    ):
        raise ValidationError("whatsapp_phone_number must be a non-empty string")
    government_id = payload.get("government_id")
    if (
        government_id is not None
        and (require_full_name or government_id != "")
        and (not isinstance(government_id, str) or not government_id.strip())
    ):
        raise ValidationError("government_id must be a non-empty string")
    return clean_params(
        {
            "full_name": full_name,
            "email": email,
            "whatsapp_phone_number": phone,
            "government_id": government_id,
        }
    )


def validate_credit_ceiling(value: Any) -> None:
    """Validate an optional finite, nonnegative credit ceiling without changing its value."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValidationError("max_total_credits must be a finite nonnegative number")
    if isinstance(value, str) and not _NUMBER_RE.fullmatch(value.strip()):
        raise ValidationError("max_total_credits must be a finite nonnegative number")
    try:
        number = Decimal(str(value) if isinstance(value, float) else value)
    except InvalidOperation:
        raise ValidationError("max_total_credits must be a finite nonnegative number") from None
    if not number.is_finite() or number < 0:
        raise ValidationError("max_total_credits must be a finite nonnegative number")


def idempotency_headers(key: str | None) -> dict[str, str]:
    """Build an optional idempotency header without allowing header control characters."""
    if key is None:
        return {}
    if not isinstance(key, str) or any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise ValidationError("idempotency_key must be printable ASCII")
    return {"Idempotency-Key": key}


def normalize_expand(expand: str | list[str] | None, allowed: frozenset[str]) -> str | None:
    """Normalize supported expansions to the comma-separated query value."""
    if expand is None:
        return None
    values = expand.split(",") if isinstance(expand, str) else expand
    if not isinstance(values, list) or not values:
        raise ValidationError("expand must name at least one supported expansion")
    if any(not isinstance(value, str) or value.strip() not in allowed for value in values):
        raise ValidationError("expand contains an unsupported expansion")
    return ",".join(value.strip() for value in values)


def validate_signer_methods(verification: Any, notifications: Any, embedded: Any = None) -> None:
    """Validate the coupled verification and single notification channel."""
    if verification is not None and (
        not isinstance(verification, str) or verification not in VERIFICATION_METHODS
    ):
        raise ValidationError("Invalid signer verification_method")
    if notifications is not None:
        if (
            not isinstance(notifications, list)
            or len(notifications) != 1
            or not isinstance(notifications[0], str)
            or notifications[0] not in NOTIFICATION_METHODS
        ):
            raise ValidationError("notification_methods must contain exactly one Email or Whatsapp")
        if verification in {"Email", "Whatsapp"} and notifications != [verification]:
            raise ValidationError("notification_methods must match the verification_method")
    if embedded is not None and not isinstance(embedded, bool):
        raise ValidationError("embedded must be boolean")
    if embedded and verification not in {None, "Email", "Whatsapp"}:
        raise ValidationError("embedded signers require Email or Whatsapp verification")


def validate_decline_reason(value: Any) -> str:
    """Validate the required decline reason shared by single and bulk declines."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Decline reason is required")
    if len(value) > 2000:
        raise ValidationError("Decline reason must be 2000 characters or fewer")
    return value


def validate_boolean_preferences(preferences: Any, allowed: frozenset[str]) -> None:
    """Validate a partial notification preference map before sending it."""
    if not isinstance(preferences, dict):
        raise ValidationError("Notification preferences must be a mapping")
    if not preferences:
        raise ValidationError("At least one notification preference is required")
    for code, enabled in preferences.items():
        if code not in allowed:
            raise ValidationError("Unknown notification preference")
        if not isinstance(enabled, bool):
            raise ValidationError("Notification preference must be boolean")
