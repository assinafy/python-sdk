"""Exception hierarchy for the Assinafy SDK.

All SDK-raised errors subclass :class:`AssinafyError`. ``except AssinafyError``
catches every documented failure mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class AssinafyError(Exception):
    """Base class for every error raised by the SDK."""

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = context or {}


class ApiError(AssinafyError):
    """Raised when the API returns a non-2xx response.

    Attributes:
        status_code: HTTP status code (or the documented envelope ``status``).
        response_data: Parsed JSON body, when available.
        rate_limit_limit: ``X-Rate-Limit-Limit`` — requests allowed in the
            current window, or ``None`` when the header is absent.
        rate_limit_remaining: ``X-Rate-Limit-Remaining`` — requests left in the
            current window, or ``None``.
        rate_limit_reset: ``X-Rate-Limit-Reset`` — seconds until the window
            resets, or ``None``.
        retry_after: ``Retry-After`` — seconds to wait before retrying, sent
            with ``429 Too Many Requests``; ``None`` when absent.

    Example::

        try:
            client.documents.list()
        except ApiError as err:
            if err.status_code == 429 and err.retry_after is not None:
                time.sleep(err.retry_after)
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        response_data: Any = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message, {"status_code": status_code, "response_data": response_data})
        self.status_code = status_code
        self.response_data = response_data
        self.rate_limit_limit = _int_header(headers, "x-rate-limit-limit")
        self.rate_limit_remaining = _int_header(headers, "x-rate-limit-remaining")
        self.rate_limit_reset = _int_header(headers, "x-rate-limit-reset")
        self.retry_after = _int_header(headers, "retry-after")

    @classmethod
    def from_response(
        cls,
        status_code: int,
        response_data: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ApiError:
        """Build an ``ApiError`` from a documented error envelope or raw status.

        ``headers`` are the HTTP response headers; the rate-limit values are
        read from them case-insensitively when present.
        """
        data = response_data if isinstance(response_data, dict) else {}
        raw_message = data.get("message")
        raw_error = data.get("error")
        if isinstance(raw_message, str) and raw_message:
            message = raw_message
        elif isinstance(raw_error, str) and raw_error:
            message = raw_error
        else:
            message = "API request failed"
        return cls(message, status_code, response_data, headers=headers)


def _int_header(headers: Mapping[str, str] | None, name: str) -> int | None:
    """Read a non-negative integer header, or ``None`` when absent or malformed."""
    if headers is None:
        return None
    value = next((v.strip() for k, v in headers.items() if k.lower() == name), "")
    return int(value) if value.isascii() and value.isdigit() else None


class ValidationError(AssinafyError):
    """Raised for client-side validation failures before a request is sent."""

    def __init__(
        self,
        message: str = "Validation failed",
        errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, {"errors": errors or {}})
        self.errors: dict[str, Any] = errors or {}


class NetworkError(AssinafyError):
    """Raised when no HTTP response arrived (DNS, refused connection, TLS handshake, timeout).

    After a timeout or a dropped connection the API may still have processed the
    request; for an OAuth refresh, the old refresh token may already be retired.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
