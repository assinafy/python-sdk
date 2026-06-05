from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from ..errors import ApiError, ValidationError
from ..types import Logger
from ..utils import create_noop_logger, handle_assinafy_response, to_sdk_error


class BaseResource:
    """Shared HTTP plumbing for resource classes.

    All resources share the same ``httpx.Client`` from :class:`AssinafyClient`,
    a default account ID, and a logger. Response handling goes through a small
    set of helpers (``_call``, ``_call_optional``, ``_call_void``,
    ``_call_binary``, ``_call_list``) so envelope handling, error normalization,
    and pagination meta parsing live in one place.
    """

    def __init__(
        self,
        http: httpx.Client,
        default_account_id: str | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._http = http
        self._default_account_id = default_account_id
        self._logger: Logger = logger or create_noop_logger()

    def _account_id(self, explicit: str | None = None) -> str:
        account_id = explicit or self._default_account_id
        if not account_id:
            raise ValidationError(
                "Account ID is required. Provide it as a parameter or set a default in the client."
            )
        return account_id

    def _require_id(self, value: str | None, name: str) -> str:
        if not value:
            raise ValidationError(f"{name} is required")
        return value

    def _guard(self, label: str, thunk: Callable[[], Any]) -> Any:
        """Run ``thunk`` and normalize any failure into the SDK error hierarchy.

        Centralizes the single try/except boundary shared by every ``_call*``
        helper, keeping error translation DRY. The catch is intentionally broad:
        any exception raised while sending the request or unwrapping the response
        is coerced to an :class:`AssinafyError` subclass (see
        :func:`~assinafy.utils.to_sdk_error`) so callers only ever need
        ``except AssinafyError``.
        """
        try:
            return thunk()
        except Exception as err:
            raise to_sdk_error(err, label) from err

    def _call(self, label: str, request_fn: Callable[[], httpx.Response]) -> Any:
        def run() -> Any:
            response = request_fn()
            response.raise_for_status()
            return handle_assinafy_response(response.json())

        return self._guard(label, run)

    def _call_optional(
        self, label: str, request_fn: Callable[[], httpx.Response]
    ) -> Any:
        try:
            return self._call(label, request_fn)
        except ApiError as err:
            if err.status_code == 404:
                return None
            raise

    def _call_void(self, label: str, request_fn: Callable[[], httpx.Response]) -> None:
        def run() -> None:
            response = request_fn()
            response.raise_for_status()
            try:
                handle_assinafy_response(response.json())
            except ValueError:
                pass

        self._guard(label, run)

    def _call_binary(self, label: str, request_fn: Callable[[], httpx.Response]) -> bytes:
        def run() -> bytes:
            response = request_fn()
            response.raise_for_status()
            return bytes(response.content)

        return self._guard(label, run)

    def _call_list(
        self, label: str, request_fn: Callable[[], httpx.Response]
    ) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            response = request_fn()
            response.raise_for_status()
            unwrapped = handle_assinafy_response(response.json())
            if isinstance(unwrapped, list):
                data = unwrapped
            elif isinstance(unwrapped, dict) and isinstance(unwrapped.get("data"), list):
                data = unwrapped["data"]
            else:
                data = []
            meta = _parse_pagination_meta(response.headers)
            result: dict[str, Any] = {"data": data}
            if meta is not None:
                result["meta"] = meta
            return result

        return self._guard(label, run)

    def _call_plain_list(
        self, label: str, request_fn: Callable[[], httpx.Response]
    ) -> list[Any]:
        """Unwrap an endpoint that returns a bare JSON array (no pagination).

        Coerces a non-list payload to ``[]`` so callers always receive a list.
        """
        result = self._call(label, request_fn)
        return result if isinstance(result, list) else []

    def _call_plain_dict(
        self, label: str, request_fn: Callable[[], httpx.Response]
    ) -> dict[str, Any]:
        """Unwrap an endpoint that returns a single JSON object.

        Coerces a non-dict payload to ``{}`` so callers always receive a dict.
        """
        result = self._call(label, request_fn)
        return result if isinstance(result, dict) else {}


def _parse_pagination_meta(headers: Any) -> dict[str, int] | None:
    keys = (
        ("current_page", "x-pagination-current-page"),
        ("per_page", "x-pagination-per-page"),
        ("total", "x-pagination-total-count"),
        ("last_page", "x-pagination-page-count"),
    )
    meta: dict[str, int] = {}
    for out_key, header in keys:
        parsed = _to_int(_read_header(headers, header))
        if parsed is not None:
            meta[out_key] = parsed
    return meta or None


def _read_header(headers: Any, key: str) -> str | None:
    if not hasattr(headers, "get"):
        return None
    value = headers.get(key)
    if value is None:
        return None
    return str(value[0]) if isinstance(value, list) else str(value)


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
