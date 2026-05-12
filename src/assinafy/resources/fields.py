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
        """``GET /accounts/{account_id}/fields``.

        ``params`` accepts ``include_standard`` and ``include_inactive`` plus
        the usual ``page`` / ``per_page`` / ``search`` / ``sort``.
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list field definitions",
            lambda: self._http.get(f"accounts/{acc_id}/fields", params=cleaned),
        )

    def get(self, field_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/fields/{field_id}``."""
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
        """``PUT /accounts/{account_id}/fields/{field_id}``."""
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
        """``DELETE /accounts/{account_id}/fields/{field_id}``."""
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

        Pass ``signer_access_code`` when validating in the signer flow; omit
        when validating from an authenticated backend.
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

        ``values`` is a list of ``{field_id, value}`` objects per the docs.
        """
        if not values:
            raise ValidationError("At least one field value is required")
        acc_id = self._account_id(account_id)
        result = self._call(
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
        return result if isinstance(result, list) else []

    def list_types(self) -> list[dict[str, Any]]:
        """``GET /field-types`` — global catalog of built-in field types."""
        result = self._call(
            "Failed to list field types",
            lambda: self._http.get("field-types"),
        )
        return result if isinstance(result, list) else []
