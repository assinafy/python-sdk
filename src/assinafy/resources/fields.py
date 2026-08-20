from __future__ import annotations

import builtins
from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource

_CREATE_FIELDS = frozenset({"name", "type", "regex", "is_required"})
_UPDATE_FIELDS = frozenset({"name", "regex", "is_active"})


class FieldResource(BaseResource):
    """Field-definition endpoints (custom and standard fields)."""

    def create(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/fields`` — create a custom field.

        ``payload`` requires ``type`` (one of the values returned by
        :meth:`list_types`) and ``name``. Optional: ``regex``, ``is_required``.
        ``is_read_only``/``is_visible`` are server-controlled response fields,
        not accepted create input (confirmed live: passing them is silently
        ignored).

        Example request body (JSON)::

            {"type": "text", "name": "CPF"}

        Example response (``data`` envelope unwrapped)::

            {"resource": "field_definition", "id": "1031ff86...", "name": "CPF",
             "type": "text", "regex": null, "is_pre_defined": false,
             "is_active": true, "is_required": true, "is_standard": false,
             "is_read_only": false, "is_visible": true}
        """
        if not isinstance(payload, dict):
            raise ValidationError("Field payload must be a mapping")
        unknown = payload.keys() - _CREATE_FIELDS
        if unknown:
            raise ValidationError(f"Unknown field attributes: {', '.join(sorted(unknown))}")
        self._require_id(payload.get("type"), "type")
        self._require_id(payload.get("name"), "name")
        if payload.get("regex") is not None and not isinstance(payload["regex"], str):
            raise ValidationError("regex must be a string or None")
        if "is_required" in payload and not isinstance(payload["is_required"], bool):
            raise ValidationError("is_required must be boolean")
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to create field definition",
            lambda: self._http.post(
                f"accounts/{acc_id}/fields",
                json=clean_params(payload),
            ),
        )

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/fields`` — list field definitions.

        ``params`` accepts the documented ``include_standard`` and
        ``include_inactive`` flags. Other keys are forwarded for compatibility
        with deployments that implement the API's global list-query options.

        Example response (``data`` envelope unwrapped, ``meta`` from
        ``x-pagination-*`` headers)::

            {"data": [
                {"resource": "field_definition", "id": "field-id", "name": "Nome",
                 "type": "personName", "regex": null, "is_pre_defined": true,
                 "is_active": true, "is_required": false, "is_standard": false,
                 "is_read_only": false, "is_visible": true}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 11, "last_page": 1}}
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list field definitions",
            lambda: self._http.get(f"accounts/{acc_id}/fields", params=cleaned),
        )

    def get(self, field_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/fields/{field_id}`` — fetch one field.

        Example response (``data`` envelope unwrapped)::

            {"resource": "field_definition", "id": "1031ff86...", "name": "CPF",
             "type": "text", "regex": null, "is_pre_defined": false,
             "is_active": true, "is_required": true, "is_standard": false,
             "is_read_only": false, "is_visible": true}
        """
        acc_id = self._account_id(account_id)
        fid = self._path_id(field_id, "Field ID")
        return self._call_dict(
            "Failed to fetch field definition",
            lambda: self._http.get(f"accounts/{acc_id}/fields/{fid}"),
        )

    def update(
        self,
        field_id: str,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/fields/{field_id}`` — update a field.

        Passing ``{"regex": None}`` is preserved and clears the field's regex,
        matching :meth:`~assinafy.resources.tags.TagResource.update`'s handling
        of ``color: None``.

        Example request body (JSON)::

            {"name": "CPF updated"}    # or {"regex": null} to clear the regex

        Returns the updated field-definition object (``data`` envelope unwrapped).
        """
        acc_id = self._account_id(account_id)
        fid = self._path_id(field_id, "Field ID")
        if not isinstance(payload, dict):
            raise ValidationError("Field payload must be a mapping")
        unknown = payload.keys() - _UPDATE_FIELDS
        if unknown:
            raise ValidationError(f"Unknown field attributes: {', '.join(sorted(unknown))}")
        if "name" in payload:
            self._require_id(payload["name"], "name")
        if payload.get("regex") is not None and not isinstance(payload["regex"], str):
            raise ValidationError("regex must be a string or None")
        if "is_active" in payload and not isinstance(payload["is_active"], bool):
            raise ValidationError("is_active must be boolean")
        body = {k: v for k, v in payload.items() if k == "regex" or v is not None}
        if not body:
            raise ValidationError("At least one field attribute is required")
        return self._call_dict(
            "Failed to update field definition",
            lambda: self._http.put(f"accounts/{acc_id}/fields/{fid}", json=body),
        )

    def delete(self, field_id: str, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/fields/{field_id}`` — delete a field.

        Request body: none. Success returns ``None``; the response has no
        ``data`` payload.
        """
        acc_id = self._account_id(account_id)
        fid = self._path_id(field_id, "Field ID")
        self._call_void(
            "Failed to delete field definition",
            lambda: self._http.delete(f"accounts/{acc_id}/fields/{fid}"),
        )

    def validate(
        self,
        field_id: str,
        value: Any,
        signer_access_code: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/fields/{field_id}/validate``.

        Validates a single value against a field definition's rules. Pass
        ``signer_access_code`` when validating in the signer flow; omit it when
        validating from an authenticated backend.

        Example request body (JSON)::

            {"value": "hello"}

        Example response (``data`` envelope unwrapped; ``type`` echoes the field's
        type, e.g. ``cpf`` for a CPF field)::

            {"type": "text", "success": true, "error_message": ""}
        """
        acc_id = self._account_id(account_id)
        fid = self._path_id(field_id, "Field ID")
        return self._call_dict(
            "Failed to validate field value",
            lambda: self._http.post(
                f"accounts/{acc_id}/fields/{fid}/validate",
                params=clean_params(
                    {"signer_access_code": signer_access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json={"value": value},
            ),
        )

    def validate_multiple(
        self,
        values: builtins.list[dict[str, Any]],
        signer_access_code: str | None = None,
        account_id: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """``POST /accounts/{account_id}/fields/validate-multiple``.

        ``values`` is a list of ``{field_id, value}`` objects (sent as the raw
        JSON request body).

        Example request body (JSON array)::

            [{"field_id": "1031ff86...", "value": "hi"}]

        Example response (``data`` envelope unwrapped)::

            [{"field_id": "1031ff86...", "type": "text", "success": true,
              "error_message": ""}]
        """
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("field_id"), str)
                or not item["field_id"]
                or "value" not in item
                for item in values
            )
        ):
            raise ValidationError("At least one field value is required")
        acc_id = self._account_id(account_id)
        return self._call_plain_list(
            "Failed to validate field values",
            lambda: self._http.post(
                f"accounts/{acc_id}/fields/validate-multiple",
                params=clean_params(
                    {"signer_access_code": signer_access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json=values,
            ),
        )

    def list_types(self) -> builtins.list[dict[str, Any]]:
        """``GET /field-types`` — global catalog of built-in field types.

        Example response (``data`` envelope unwrapped)::

            [{"type": "personName", "name": "Nome"},
             {"type": "cpf", "name": "CPF"},
             {"type": "text", "name": "Texto"},
             {"type": "date", "name": "Data"}]
        """
        return self._call_plain_list(
            "Failed to list field types",
            lambda: self._http.get("field-types"),
        )
