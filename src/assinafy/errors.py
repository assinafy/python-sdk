"""Exception hierarchy for the Assinafy SDK.

All SDK-raised errors subclass :class:`AssinafyError`. ``except AssinafyError``
catches every documented failure mode.
"""

from __future__ import annotations

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
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        response_data: Any = None,
    ) -> None:
        super().__init__(message, {"status_code": status_code, "response_data": response_data})
        self.status_code = status_code
        self.response_data = response_data

    @classmethod
    def from_response(cls, status_code: int, response_data: Any) -> ApiError:
        """Build an ``ApiError`` from a documented error envelope or raw status."""
        data = response_data if isinstance(response_data, dict) else {}
        raw_message = data.get("message")
        raw_error = data.get("error")
        if isinstance(raw_message, str) and raw_message:
            message = raw_message
        elif isinstance(raw_error, str) and raw_error:
            message = raw_error
        else:
            message = "API request failed"
        return cls(message, status_code, response_data)


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
    """Raised when the request never reached the API (DNS, timeout, refused)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
