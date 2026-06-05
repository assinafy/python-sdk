from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource


class FieldResource(BaseResource):
    """Field-definition endpoints (custom and standard fields)."""

    def create(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/fields`` — create a custom field.

        ``payload`` requires ``type`` (one of the values returned by
        :meth:`list_types`) and ``name``. Optional: ``regex``, ``is_required``,
        ``is_read_only``, ``is_visible``.

        Example request body (JSON)::

            {"type": "text", "name": "CPF"}

        Example response (``data`` envelope unwrapped)::

            {"resource": "field_definition", "id": "1031ff86...", "name": "CPF",
             "type": "text", "regex": null, "is_pre_defined": false,
             "is_active": true, "is_required": true, "is_standard": false,
             "is_read_only": false, "is_visible": true}
        """
        if not payload.get("type"):
            raise ValidationError("type is required")
        if not payload.get("name"):
            raise ValidationError("name is required")
        acc_id = self._account_id(account_id)
        return self._call(
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

        ``params`` accepts ``include_standard`` and ``include_inactive`` plus
        the usual ``page`` / ``per_page`` / ``search`` / ``sort``.

        Example response (``data`` envelope unwrapped, ``meta`` from
        ``x-pagination-*`` headers)::

            {"data": [
                {"id": "102d25a4...", "name": "Nome", "type": "personName",
                 "regex": null, "is_pre_defined": true, "is_active": true,
                 "is_required": false, "is_standard": false,
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
        fid = self._require_id(field_id, "Field ID")
        return self._call(
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

        Example request body (JSON)::

            {"name": "CPF updated"}

        Returns the updated field-definition object (``data`` envelope unwrapped).
        """
        acc_id = self._account_id(account_id)
        fid = self._require_id(field_id, "Field ID")
        body = clean_params(payload)
        if not body:
            raise ValidationError("At least one field attribute is required")
        return self._call(
            "Failed to update field definition",
            lambda: self._http.put(f"accounts/{acc_id}/fields/{fid}", json=body),
        )

    def delete(self, field_id: str, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/fields/{field_id}`` — delete a field."""
        acc_id = self._account_id(account_id)
        fid = self._require_id(field_id, "Field ID")
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

            {"value": "400.676.228-36"}

        Example response (``data`` envelope unwrapped)::

            {"type": "text", "success": true, "error_message": ""}
        """
        acc_id = self._account_id(account_id)
        fid = self._require_id(field_id, "Field ID")
        return self._call(
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
        values: list[dict[str, Any]],
        signer_access_code: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """``POST /accounts/{account_id}/fields/validate-multiple``.

        ``values`` is a list of ``{field_id, value}`` objects (sent as the raw
        JSON request body).

        Example request body (JSON array)::

            [{"field_id": "1031ff86...", "value": "400.676.228-36"}]

        Example response (``data`` envelope unwrapped)::

            [{"field_id": "1031ff86...", "type": "text", "success": true,
              "error_message": ""}]
        """
        if not values:
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

    def list_types(self) -> list[dict[str, Any]]:
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
