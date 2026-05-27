from __future__ import annotations

import re
from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource

_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


class TagResource(BaseResource):
    """Workspace tag endpoints for organizing documents and templates."""

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/tags`` — list workspace tags.

        ``params`` accepts ``search`` plus the standard ``page`` / ``per_page``
        pagination keys. Returns ``{"data": [...], "meta": {...}}`` when the
        API returns pagination headers.
        """
        acc_id = self._account_id(account_id)
        return self._call_list(
            "Failed to list tags",
            lambda: self._http.get(
                f"accounts/{acc_id}/tags",
                params=clean_params(params or {}, QUERY_PARAM_ALIASES),
            ),
        )

    def create(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/tags`` — create a workspace tag.

        ``payload`` requires ``name`` and may include ``color`` as a 6-character
        hex value, with or without a leading ``#``.
        """
        acc_id = self._account_id(account_id)
        body = _build_tag_payload(payload, require_name=True)
        return self._call(
            "Failed to create tag",
            lambda: self._http.post(f"accounts/{acc_id}/tags", json=body),
        )

    def update(
        self,
        tag_id: str,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/tags/{tag_id}`` — update name/color.

        Passing ``{"color": None}`` is preserved and clears the color server-side
        as documented.
        """
        acc_id = self._account_id(account_id)
        tid = self._require_id(tag_id, "Tag ID")
        body = _build_tag_payload(payload, require_name=False)
        return self._call(
            "Failed to update tag",
            lambda: self._http.put(f"accounts/{acc_id}/tags/{tid}", json=body),
        )

    def delete(
        self,
        tag_id: str,
        force: bool = False,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``DELETE /accounts/{account_id}/tags/{tag_id}``.

        Set ``force=True`` to detach the tag from documents/templates before
        deletion, matching the documented ``force`` query parameter.
        """
        acc_id = self._account_id(account_id)
        tid = self._require_id(tag_id, "Tag ID")
        return self._call(
            "Failed to delete tag",
            lambda: self._http.delete(
                f"accounts/{acc_id}/tags/{tid}",
                params=clean_params({"force": True if force else None}),
            ),
        )


def _build_tag_payload(payload: dict[str, Any], require_name: bool) -> dict[str, Any]:
    body: dict[str, Any] = {}

    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Tag name is required")
        body["name"] = name
    elif require_name:
        raise ValidationError("Tag name is required")

    if "color" in payload:
        color = payload["color"]
        if color is not None:
            if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
                raise ValidationError(
                    "Tag color must be a 6-character hex value",
                    {"color": color},
                )
        body["color"] = color

    if not body:
        raise ValidationError("At least one tag field is required")
    return body
