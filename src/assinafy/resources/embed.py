from __future__ import annotations

from typing import Any

from .base import BaseResource


class EmbedResource(BaseResource):
    """Single-use signing sessions consumed by Assinafy's embedded signing page.

    Integrations normally load the URL returned by
    :meth:`AssignmentResource.create_embed_session` in an iframe. Exchanging
    its token directly consumes it, so that URL can no longer open the session.
    """

    def exchange(self, token: str, parent_origin: str | None = None) -> dict[str, Any]:
        """``POST /embed/sessions/{token}/exchange`` — consume an embed token once.

        The 64-character token from the embed URL is the credential. No workspace
        API key or bearer token is sent. It is consumed even on a ``409`` refusal;
        expired, unknown and already-used tokens receive ``410``. Never retry an
        ambiguous network failure, log the token or persist the returned access code
        in browser storage.

        Optional JSON request body::

            {"parent_origin": "https://app.example.com"}

        Response (``data`` unwrapped)::

            {"signer_access_code": "synthetic-access-code", "signer_id": "signer-id",
             "document_id": "document-id", "verification_method": "Email",
             "embed_origins": ["https://app.example.com"]}
        """
        session_token = self._path_id(token, "Embed session token")
        body = (
            {}
            if parent_origin is None
            else {"parent_origin": self._require_id(parent_origin, "Parent origin")}
        )
        return self._call_dict(
            "Failed to exchange embed session",
            lambda: self._http.post(f"embed/sessions/{session_token}/exchange", json=body),
        )
