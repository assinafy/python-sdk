from __future__ import annotations

from typing import Any

from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource


class TemplateResource(BaseResource):
    """Template endpoints — discovery (list + get).

    Document creation from a template lives on
    :meth:`assinafy.resources.documents.DocumentResource.create_from_template`.

    The published OpenAPI exposes ``list`` only. ``get`` is retained because
    the route is deployed and answers on the live API (it authenticates rather
    than 404s) and the published schema text describes a single-template
    response. No template mutation or page-download paths are published.
    """

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/templates`` — list workspace templates.

        ``params`` accepts the published ``page``, ``per_page``, and ``search``
        keys. Other keys are forwarded for compatibility with deployments that
        implement the API's global list-query options.

        Example response (``data`` envelope unwrapped, ``meta`` from
        ``x-pagination-*`` headers)::

            {"data": [
                {"id": "fa7f3e52...", "name": "nda.pdf",
                 "document_name": "nda.pdf", "message": null, "status": "ready",
                 "pages": [{"id": "fa7f3e52...", "number": 1, "height": 2100,
                            "width": 1275, "download_url": "https://api.example/page",
                            "fields": [{"id": "placement-id", "field_id": "field-id",
                                        "role_id": "role-id", "label": "Signature",
                                        "display_settings": {"left": 69, "top": 282},
                                        "created_at": "2024-07-19T15:23:03Z",
                                        "updated_at": "2024-07-19T15:23:03Z"}]}],
                 "roles": [{"id": "fa7f3e52...", "name": "Editor",
                            "assignment_type": "Editor",
                            "created_at": "2024-07-19T15:23:03Z",
                            "updated_at": "2024-07-19T15:23:03Z"}],
                 "tags": [{"id": "fa8c09f3...", "name": "HR"}],
                 "created_at": "2024-07-19T15:23:03Z",
                 "updated_at": "2024-07-19T15:23:03Z"}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params if params is not None else {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list templates",
            lambda: self._http.get(f"accounts/{acc_id}/templates", params=cleaned),
        )

    def get(self, template_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/templates/{template_id}`` — fetch one template.

        Unlike :meth:`list`, the single-template response additionally includes
        ``default_document_tags`` (tags auto-applied to documents created from
        this template).

        Example response (``data`` envelope unwrapped)::

            {"resource": "template", "id": "fa7f3e52...", "name": "nda.pdf",
             "document_name": "nda.pdf", "message": null, "status": "ready",
             "pages": [{"id": "page-id", "number": 1, "height": 2100,
                        "width": 1275, "download_url": "https://api.example/page",
                        "fields": [{"id": "placement-id", "field_id": "field-id",
                                    "role_id": "role-id", "label": "Signature",
                                    "display_settings": {"left": 69, "top": 282},
                                    "created_at": "2024-07-19T15:23:03Z",
                                    "updated_at": "2024-07-19T15:23:03Z"}]}],
             "roles": [{"id": "role-id", "name": "Signer",
                        "assignment_type": "Signer",
                        "created_at": "2024-07-19T15:23:03Z",
                        "updated_at": "2024-07-19T15:23:03Z"}],
             "tags": [{"id": "tag-id", "name": "HR"}],
             "default_document_tags": [{"id": "tag-id", "name": "Signed"}],
             "created_at": "2024-07-19T15:23:03Z",
             "updated_at": "2024-07-19T15:23:03Z"}
        """
        acc_id = self._account_id(account_id)
        tmpl_id = self._path_id(template_id, "Template ID")
        return self._call_dict(
            "Failed to fetch template",
            lambda: self._http.get(f"accounts/{acc_id}/templates/{tmpl_id}"),
        )
