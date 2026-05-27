from __future__ import annotations

from typing import Any

from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource


class TemplateResource(BaseResource):
    """Template endpoints — discovery only.

    Document creation from a template lives on
    :class:`DocumentResource.create_from_template`.
    """

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/templates``.

        ``params`` accepts ``page``, ``per_page``, ``search``, ``status``,
        ``tags``, and ``sort`` (``name``, ``updated_at``).
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list templates",
            lambda: self._http.get(f"accounts/{acc_id}/templates", params=cleaned),
        )

    def get(self, template_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/templates/{template_id}``."""
        acc_id = self._account_id(account_id)
        tmpl_id = self._require_id(template_id, "Template ID")
        return self._call(
            "Failed to fetch template",
            lambda: self._http.get(f"accounts/{acc_id}/templates/{tmpl_id}"),
        )
