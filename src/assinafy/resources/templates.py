from __future__ import annotations

from typing import Any

from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource


class TemplateResource(BaseResource):
    """Template endpoints — discovery (list + get).

    Document creation from a template lives on
    :meth:`assinafy.resources.documents.DocumentResource.create_from_template`.

    Note: the docs reference template create/update/delete/page-download
    endpoints, but only ``list`` (and the single-template ``get`` shape) are
    given a documented request/response contract. Those mutating endpoints are
    intentionally not implemented here until Assinafy publishes their request
    bodies; implementing them blind would risk shipping a wrong contract.
    """

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/templates`` — list workspace templates.

        ``params`` accepts ``page``, ``per_page``, ``search``, ``status``,
        ``tags`` (comma-separated tag IDs, AND semantics), and ``sort``
        (``name``, ``updated_at``).

        Example response (``data`` envelope unwrapped, ``meta`` from
        ``x-pagination-*`` headers)::

            {"data": [
                {"id": "fa7f3e52...", "name": "nda.pdf",
                 "document_name": "nda.pdf", "message": null, "status": "Ready",
                 "pages": [{"id": "fa7f3e52...", "number": 1, "height": 2100,
                            "width": 1275, "fields": []}],
                 "roles": [{"id": "fa7f3e52...", "name": "Editor",
                            "assignment_type": "Editor"}],
                 "tags": [{"id": "fa8c09f3...", "name": "HR"}],
                 "created_at": "2024-07-19T15:23:03Z",
                 "updated_at": "2024-07-19T15:23:03Z"}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list templates",
            lambda: self._http.get(f"accounts/{acc_id}/templates", params=cleaned),
        )

    def get(self, template_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/templates/{template_id}`` — fetch one template.

        Unlike :meth:`list`, the single-template response additionally includes
        ``default_document_tags`` (tags auto-applied to documents created from
        this template).

        Example response (``data`` envelope unwrapped, trimmed)::

            {"resource": "template", "id": "fa7f3e52...", "name": "nda.pdf",
             "document_name": "nda.pdf", "message": null, "status": "ready",
             "pages": [...], "roles": [...], "tags": [{"id": "...", "name": "HR"}],
             "default_document_tags": [{"id": "...", "name": "Signed"}],
             "created_at": "2024-07-19T15:23:03Z",
             "updated_at": "2024-07-19T15:23:03Z"}
        """
        acc_id = self._account_id(account_id)
        tmpl_id = self._require_id(template_id, "Template ID")
        return self._call(
            "Failed to fetch template",
            lambda: self._http.get(f"accounts/{acc_id}/templates/{tmpl_id}"),
        )
