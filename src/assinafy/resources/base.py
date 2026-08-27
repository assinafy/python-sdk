from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import httpx

from ..errors import ApiError, AssinafyError, ValidationError
from ..types import Logger
from ..utils import create_noop_logger, handle_assinafy_response, to_sdk_error

_T = TypeVar("_T")


class BaseResource:
    """Shared HTTP plumbing for resource classes.

    All resources share the same ``httpx.Client`` from
    :class:`~assinafy.client.AssinafyClient`,
    a default account ID, and a logger. Response handling goes through a small
    set of helpers (``_call``, ``_call_dict``, ``_call_nullable_dict``,
    ``_call_optional``, ``_call_void``, ``_call_binary``, ``_call_list``,
    ``_call_plain_list``)
    so envelope handling, error normalization, and pagination meta parsing live
    in one place.
    """

    def __init__(
        self,
        http: httpx.Client,
        default_account_id: str | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._http = http
        self._default_account_id = default_account_id
        self._logger: Logger = logger if logger is not None else create_noop_logger()

    def _account_id(self, explicit: str | None = None) -> str:
        account_id = self._default_account_id if explicit is None else explicit
        if account_id is None:
            raise ValidationError(
                "Account ID is required. Provide it as a parameter or set a default in the client."
            )
        return self._path_id(account_id, "Account ID")

    def _require_id(self, value: str | None, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{name} is required")
        return value

    def _path_id(self, value: str | None, name: str) -> str:
        """Validate an opaque API ID before interpolating it into a URL path."""
        segment = self._require_id(value, name)
        if segment in {".", ".."} or any(char in segment for char in "/\\?#%"):
            raise ValidationError(f"{name} contains invalid path characters")
        return segment

    def _guard(self, label: str, thunk: Callable[[], _T]) -> _T:
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
        except AssinafyError:
            raise
        except Exception as err:
            raise to_sdk_error(err, label) from err

    def _call(self, label: str, request_fn: Callable[[], httpx.Response]) -> Any:
        def run() -> Any:
            response = request_fn()
            response.raise_for_status()
            return handle_assinafy_response(response.json())

        return self._guard(label, run)

    def _call_dict(self, label: str, request_fn: Callable[[], httpx.Response]) -> dict[str, Any]:
        result = self._call(label, request_fn)
        if not isinstance(result, dict):
            raise AssinafyError(f"{label}: API returned a non-object payload", {"response": result})
        return result

    def _call_nullable_dict(
        self, label: str, request_fn: Callable[[], httpx.Response]
    ) -> dict[str, Any] | None:
        result = self._call(label, request_fn)
        if result is None or isinstance(result, dict):
            return result
        raise AssinafyError(f"{label}: API returned an invalid payload", {"response": result})

    def _call_optional(
        self, label: str, request_fn: Callable[[], httpx.Response]
    ) -> dict[str, Any] | None:
        try:
            return self._call_nullable_dict(label, request_fn)
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

    def _call_list(self, label: str, request_fn: Callable[[], httpx.Response]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            response = request_fn()
            response.raise_for_status()
            unwrapped = handle_assinafy_response(response.json())
            if isinstance(unwrapped, list):
                data = unwrapped
            elif isinstance(unwrapped, dict) and isinstance(unwrapped.get("data"), list):
                data = unwrapped["data"]
            else:
                raise AssinafyError(
                    f"{label}: API returned a non-list payload", {"response": unwrapped}
                )
            meta = _parse_pagination_meta(response.headers)
            result: dict[str, Any] = {"data": data}
            if meta is not None:
                result["meta"] = meta
            return result

        return self._guard(label, run)

    def _call_plain_list(self, label: str, request_fn: Callable[[], httpx.Response]) -> list[Any]:
        """Unwrap an endpoint that returns a bare JSON array (no pagination).

        Raises :class:`AssinafyError` when the API violates the documented array shape.
        """
        result = self._call(label, request_fn)
        if not isinstance(result, list):
            raise AssinafyError(f"{label}: API returned a non-list payload", {"response": result})
        return result


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
