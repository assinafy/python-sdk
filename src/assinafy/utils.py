"""Internal utilities: response envelope handling, logger, query aliases."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from .errors import ApiError, AssinafyError, NetworkError, ValidationError
from .types import Logger

# Pythonic keyword -> documented hyphenated query/body key mapping.
QUERY_PARAM_ALIASES = {
    "per_page": "per-page",
    "signer_access_code": "signer-access-code",
}
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


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
        return ApiError.from_response(error.response.status_code, data)

    if isinstance(error, httpx.RequestError):
        return NetworkError(f"{fallback_message}: {error}")

    return AssinafyError(f"{fallback_message}: {error}")


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


def validate_email(value: Any, name: str = "Email") -> str:
    """Return a syntactically valid email address."""
    if not isinstance(value, str) or not _EMAIL_RE.fullmatch(value):
        raise ValidationError(f"Invalid {name.lower()}", {name.lower(): value})
    return value
