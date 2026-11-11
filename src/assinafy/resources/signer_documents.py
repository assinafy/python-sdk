from __future__ import annotations

import builtins
from typing import Any

from ..errors import ValidationError
from ..types import DOCUMENT_ARTIFACT_NAMES, DocumentArtifactName
from ..utils import QUERY_PARAM_ALIASES, clean_params, normalize_expand, validate_decline_reason
from .base import BaseResource


class SignerDocumentResource(BaseResource):
    """Signer-facing document endpoints.

    Every method that takes ``signer_access_code`` rejects a missing or blank
    code before sending anything, and the request carries only that code —
    never the client's API key or bearer token. Listing and searching a signer's
    documents with the workspace credentials is a separate, explicit call:
    :meth:`list_as_workspace` and :meth:`search_as_workspace`. Original downloads
    require the signer code; certified copies use a token from the sent link.
    Both omit workspace credentials.
    """

    def current(
        self,
        signer_id: str,
        signer_access_code: str,
        *,
        expand: str | builtins.list[str] | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/document?signer-access-code=...``.

        Returns the complete unwrapped
        :class:`~assinafy.resources.documents.DocumentResource` payload for the
        document the signer is currently expected to act on. ``current_signer``
        contains their verification/notification methods and completion state.
        ``expand="envelope"`` adds the code's envelope ``{id, name}`` or null,
        even if its own document was removed from the envelope. This endpoint
        works before certificate/biometric signers confirm their data.
        After the signer finishes all their documents for more than 30 minutes
        (or the workspace is deleted), the code is closed. The response then
        contains only ``id``, ``name``, ``status``, ``current_signer`` (id,
        verification_method, notification_methods, completed),
        ``is_signer_access_closed: true``, ``certified_copy`` and any requested
        ``envelope``. ``certified_copy`` has ``available``, nullable
        ``notification_method`` and nullable ``resends_left``. These status/copy
        keys also accompany open-code reads. Other signer operations return
        410 for a closed code; :meth:`request_certified_copy` remains available.
        The assignment contains their own items and omits ``signers``,
        ``signing_urls``, ``copy_receivers`` and ``summary``.

        Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"resource": "document", "id": "document-id", "account_id": "account-id",
             "template_id": null, "name": "contract.pdf", "status": "metadata_ready",
             "artifacts": {"original": "https://api.example/document/original"},
             "is_closed": false, "signing_url": "https://app.example/sign/document-id",
             "decline_reason": null, "declined_by": null, "tags": [],
             "assignment": {"id": "assignment-id", "document_id": "document-id",
                            "created_at": "2026-06-03T03:54:16Z",
                            "sender_email": "sender@example.com", "method": "virtual",
                            "expires_at": null, "message": null, "items": []},
             "current_signer": {"resource": "signer", "id": "signer-id",
                                "full_name": "Example Signer", "email": "signer@example.com",
                                "whatsapp_phone_number": null, "government_id": null,
                                "has_accepted_terms": true, "verification_method": "Email",
                                "notification_methods": ["Email"], "completed": false},
             "verification_code": null, "verification_url": null, "pages": [],
             "created_at": "2026-06-03T03:54:16Z",
             "updated_at": "2026-06-03T03:54:17Z"}
        """
        sid = self._path_id(signer_id, "Signer ID")
        query = self._signer_query(
            signer_access_code, expand=normalize_expand(expand, frozenset({"envelope"}))
        )
        return self._call_dict(
            "Failed to fetch current signer document",
            lambda: self._http.get(f"signers/{sid}/document", params=query),
        )

    def list(
        self,
        signer_id: str,
        signer_access_code: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/documents?signer-access-code=...``.

        ``params`` accepts ``page``, ``per_page`` and ``envelope_id`` to filter
        one envelope. Other
        keys are forwarded for deployment compatibility. The signer access code
        is required and is the only credential sent; an invalid code returns
        401. Use :meth:`list_as_workspace` to list with the workspace API key or
        bearer token instead.
        ``signer_id`` must be the code's signer (otherwise HTTP 403). Only
        documents whose signing step has been reached are listed, and their
        assignments omit ``signing_urls``.
        Returns ``{"data": [Document, ...], "meta": {...}}`` where each item
        has the complete :class:`~assinafy.resources.documents.DocumentResource`
        shape and ``meta`` contains the four documented pagination integers.

        Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"data": [{"resource": "document", "id": "document-id", "account_id": "account-id",
             "template_id": null, "name": "contract.pdf", "status": "metadata_ready",
             "artifacts": {"original": "https://api.example/document/original"},
             "is_closed": false, "signing_url": "https://app.example/sign/document-id",
             "decline_reason": null, "declined_by": null, "tags": [],
             "assignment": null, "pages": [],
             "verification_code": null, "verification_url": null,
             "created_at": "2026-06-03T03:54:16Z",
             "updated_at": "2026-06-03T03:54:17Z"}],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._list_documents(signer_id, params, access_code)

    def list_as_workspace(
        self,
        signer_id: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/documents`` with the workspace credentials.

        Lists the documents of a signer that belongs to the client's workspace,
        authenticated with the configured API key or bearer token. No signer
        access code is sent; ``params`` must not contain one. ``params`` accepts
        ``page``, ``per_page`` (sent as ``per-page``) and ``envelope_id`` keys.
        Returns the same ``{"data": [Document, ...], "meta": {...}}`` shape as
        :meth:`list`.

        Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"data": [{"resource": "document", "id": "document-id",
              "account_id": "account-id", "name": "contract.pdf",
              "template_id": null, "status": "metadata_ready",
              "artifacts": {"original": "https://api.example/document/original"},
              "is_closed": false, "signing_url": "https://app.example/sign/document-id",
              "decline_reason": null, "declined_by": null, "tags": [],
              "assignment": null, "pages": [],
              "verification_code": null, "verification_url": null,
              "created_at": "2026-06-03T03:54:16Z",
              "updated_at": "2026-06-03T03:54:17Z"}],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        return self._list_documents(signer_id, params, None)

    def _list_documents(
        self,
        signer_id: str,
        params: dict[str, Any] | None,
        access_code: str | None,
    ) -> dict[str, Any]:
        sid = self._path_id(signer_id, "Signer ID")
        cleaned = clean_params(params if params is not None else {}, QUERY_PARAM_ALIASES)
        if "signer-access-code" in cleaned:
            raise ValidationError("Pass signer_access_code separately from params")
        if access_code is not None:
            cleaned["signer-access-code"] = access_code
        return self._call_list(
            "Failed to list signer documents",
            lambda: self._http.get(f"signers/{sid}/documents", params=cleaned),
        )

    def search(
        self,
        signer_id: str,
        signer_access_code: str,
        search: str | None = None,
        *,
        envelope_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/documents/search?signer-access-code=...``.

        Lightweight, compact counterpart to :meth:`list` (no pagination
        parameters are documented for this endpoint). ``search`` is an optional
        partial-match term; ``envelope_id`` optionally filters one envelope.
        The signer access code is required and is the only
        credential sent; use :meth:`search_as_workspace` for workspace access.
        Returns ``{"data": [Document, ...]}`` where every
        item has the complete
        :class:`~assinafy.resources.documents.DocumentResource` shape.
        ``signer_id`` must match the access code's signer (HTTP 403 otherwise).
        Only reached signing steps are included; ``signing_urls`` are omitted
        from each assignment.

        Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"data": [{"resource": "document", "id": "document-id", "account_id": "account-id",
             "template_id": null, "name": "contract.pdf", "status": "metadata_ready",
             "artifacts": {"original": "https://api.example/document/original"},
             "is_closed": false, "signing_url": "https://app.example/sign/document-id",
             "decline_reason": null, "declined_by": null, "tags": [],
             "assignment": null, "pages": [],
             "verification_code": null, "verification_url": null,
             "created_at": "2026-06-03T03:54:16Z",
             "updated_at": "2026-06-03T03:54:17Z"}]}
        """
        env_id = None if envelope_id is None else self._path_id(envelope_id, "Envelope ID")
        query = self._signer_query(signer_access_code, search=search, envelope_id=env_id)
        return self._search_documents(signer_id, query)

    def search_as_workspace(
        self,
        signer_id: str,
        search: str | None = None,
        *,
        envelope_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /signers/{signer_id}/documents/search`` with the workspace credentials.

        Searches the documents of a signer that belongs to the client's
        workspace, authenticated with the configured API key or bearer token;
        no signer access code is sent. ``search`` is an optional partial-match
        term; ``envelope_id`` optionally filters one envelope. Returns the same
        ``{"data": [Document, ...]}`` shape as :meth:`search`.

        Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"data": [{"resource": "document", "id": "document-id",
              "account_id": "account-id", "name": "contract.pdf",
              "template_id": null, "status": "metadata_ready",
              "artifacts": {"original": "https://api.example/document/original"},
              "is_closed": false, "signing_url": "https://app.example/sign/document-id",
              "decline_reason": null, "declined_by": null, "tags": [],
              "assignment": null, "pages": [],
              "verification_code": null, "verification_url": null,
              "created_at": "2026-06-03T03:54:16Z",
              "updated_at": "2026-06-03T03:54:17Z"}]}
        """
        env_id = None if envelope_id is None else self._path_id(envelope_id, "Envelope ID")
        return self._search_documents(
            signer_id, clean_params({"search": search, "envelope_id": env_id})
        )

    def _search_documents(self, signer_id: str, query: dict[str, Any]) -> dict[str, Any]:
        sid = self._path_id(signer_id, "Signer ID")
        return self._call_list(
            "Failed to search signer documents",
            lambda: self._http.get(f"signers/{sid}/documents/search", params=query),
        )

    def sign_multiple(
        self,
        document_ids: builtins.list[str],
        signer_access_code: str,
    ) -> None:
        """``PUT /signers/documents/sign-multiple?signer-access-code=...``.

        Signs several virtual documents in one call. Each must be pending
        signature and ready for this signer at the current signing step.
        Invalid document state or method returns HTTP 400; unknown document
        IDs return HTTP 404.

        Example request body (JSON)::

            {"document_ids": ["doc-1", "doc-2"]}

        OpenAPI returns ``data: []`` on success; the SDK maps that empty result
        to ``None``.
        """
        query = self._signer_query(signer_access_code)
        _assert_document_ids(document_ids)
        self._call_void(
            "Failed to sign multiple documents",
            lambda: self._http.put(
                "signers/documents/sign-multiple",
                params=query,
                json={"document_ids": document_ids},
            ),
        )

    def decline_multiple(
        self,
        document_ids: builtins.list[str],
        decline_reason: str,
        signer_access_code: str,
    ) -> None:
        """``PUT /signers/documents/decline-multiple?signer-access-code=...``.

        Declines several documents in one call with a shared reason (maximum 2000 characters).

        Example request body (JSON)::

            {"document_ids": ["doc-1", "doc-2"],
             "decline_reason": "Unfavorable terms."}

        OpenAPI returns ``data: []`` on success; the SDK maps that empty result
        to ``None``.
        """
        query = self._signer_query(signer_access_code)
        reason = validate_decline_reason(decline_reason)
        _assert_document_ids(document_ids)
        self._call_void(
            "Failed to decline multiple documents",
            lambda: self._http.put(
                "signers/documents/decline-multiple",
                params=query,
                json={"document_ids": document_ids, "decline_reason": reason},
            ),
        )

    def download(
        self,
        signer_id: str,
        document_id: str,
        signer_access_code: str | None = None,
        artifact_name: DocumentArtifactName = "certificated",
    ) -> bytes:
        """``GET /signers/{signer_id}/documents/{document_id}/download/{artifact}``.

        The current API serves only ``artifact_name="original"`` with the
        signer's access code while signing is open; other artifacts return
        HTTP 403, and a closed code returns 410. Workspace credentials are
        never sent. Without a code, legacy links redirect to the expired-link
        page (302), surfaced as :class:`~assinafy.errors.ApiError`; the SDK does
        not follow it and return HTML as a PDF.

        The optional code and historical ``"certificated"`` default remain for
        compatibility with older deployments. For current signing flows pass
        a code and ``"original"`` explicitly. For the signed copy use
        :meth:`request_certified_copy` and :meth:`download_certified_copy` with
        the token delivered to the signer. Returns raw PDF bytes.

        Request body: none.
        """
        sid = self._path_id(signer_id, "Signer ID")
        doc_id = self._path_id(document_id, "Document ID")
        artifact = self._require_id(artifact_name, "Artifact name")
        if artifact not in DOCUMENT_ARTIFACT_NAMES:
            raise ValidationError(f"Unknown document artifact: {artifact}")
        query = {} if signer_access_code is None else self._signer_query(signer_access_code)
        return self._call_binary(
            "Failed to download signer document",
            lambda: self._http.get(
                f"signers/{sid}/documents/{doc_id}/download/{artifact}", params=query
            ),
        )

    def theme(self, signer_access_code: str) -> dict[str, Any]:
        """``GET /sign/theme`` — workspace branding for a signing page.

        Query: ``signer-access-code`` only; no request body or workspace
        credentials. Available before verification and after document deletion.
        Colors are six hexadecimal digits without ``#``. Response::

            {"account_name": "Example Workspace", "primary_color": "aabbcc",
             "secondary_color": "ffffff",
             "logo": "https://api.assinafy.com.br/v1/sign/logo"}

        ``logo`` is null when absent. Its URL contains no access code; use
        :meth:`logo` to retrieve it with the signer code safely.
        """
        query = self._signer_query(signer_access_code)
        return self._call_dict(
            "Failed to fetch signing theme", lambda: self._http.get("sign/theme", params=query)
        )

    def logo(self, signer_access_code: str) -> bytes:
        """``GET /sign/logo`` — raw workspace logo image bytes for the signer.

        Query: ``signer-access-code`` only; no request body or workspace
        credentials. Available before verification and after document deletion.
        HTTP 404 means no logo exists. An unopened signing step returns 400.
        """
        query = self._signer_query(signer_access_code)
        return self._call_binary(
            "Failed to download signing logo", lambda: self._http.get("sign/logo", params=query)
        )

    def request_certified_copy(
        self, signer_access_code: str, *, document_id: str | None = None
    ) -> dict[str, Any]:
        """``POST /sign/certified-copy`` — send the signer a fresh download link.

        Query: ``signer-access-code`` only, including a closed code. Sends to
        the original signing contact/channel, never a changed signer record.
        No body by default; for another document in the code's envelope send::

            {"document_id": "document-id"}

        Response (``data`` envelope unwrapped)::

            {"available": true, "notification_method": "Email",
             "resends_left": null, "sent_to": "s***@example.com"}

        The link lasts 30 minutes. Email allows one send per two minutes and
        ten per 24 hours; WhatsApp allows one resend per signature request.
        HTTP 429 enforces these limits; 409 means the signer/document is not
        ready or there is no recorded contact. No automatic retries.
        """
        query = self._signer_query(signer_access_code)
        body = (
            {}
            if document_id is None
            else {"document_id": self._path_id(document_id, "Document ID")}
        )
        kwargs: dict[str, Any] = {"json": body} if body else {}
        return self._call_dict(
            "Failed to request certified copy",
            lambda: self._http.post("sign/certified-copy", params=query, **kwargs),
        )

    def download_certified_copy(self, token: str, *, pades: bool = False) -> bytes:
        """``GET /signers/downloads/{token}`` — download a sent certified PDF.

        ``token`` comes from the link delivered to the signer; never log it.
        No request body, query, workspace credentials or signer code. With
        ``pades=True``, append the documented ``/pades`` suffix to download the
        ICP-Brasil signatures instead (404 if absent). Returns PDF bytes.
        Completion links last seven days; re-sent links last thirty minutes.
        An unknown/expired link returns 302 to an expired-link page, surfaced
        as :class:`~assinafy.errors.ApiError` without following the redirect.
        Use :meth:`resend_certified_copy` for a known expired token.
        """
        link_token = self._path_id(token, "Download token")
        if not isinstance(pades, bool):
            raise ValidationError("pades must be boolean")
        suffix = "/pades" if pades else ""
        return self._call_binary(
            "Failed to download certified copy",
            lambda: self._http.get(f"signers/downloads/{link_token}{suffix}"),
        )

    def resend_certified_copy(self, token: str) -> dict[str, Any]:
        """``POST /signers/downloads/{token}/resend`` — renew an expired sent link.

        No request body or workspace credentials. The token may have expired;
        never log it. Sends a new thirty-minute link to the signing contact on
        its original channel, with the same limits as :meth:`request_certified_copy`.
        Response (``data`` envelope unwrapped)::

            {"available": false, "notification_method": "Whatsapp",
             "resends_left": 0, "sent_to": "+55***0000"}

        HTTP 404 means an unknown token; 409 means no copy can be sent (such
        as a copy-receiver link, missing contact or uncertified document);
        429 means the resend limit was reached. No automatic retries.
        """
        link_token = self._path_id(token, "Download token")
        return self._call_dict(
            "Failed to resend certified copy",
            lambda: self._http.post(f"signers/downloads/{link_token}/resend"),
        )


def _assert_document_ids(document_ids: list[str]) -> None:
    if (
        not isinstance(document_ids, list)
        or not document_ids
        or any(not isinstance(document_id, str) or not document_id for document_id in document_ids)
    ):
        raise ValidationError("At least one document ID is required")
