from __future__ import annotations

import re
from typing import Any

from ..errors import ApiError, ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SIGNATURE_TYPES = frozenset({"signature", "initial"})


class SignerResource(BaseResource):
    """Signer endpoints — workspace CRUD plus signer-access-code flows.

    The account-scoped methods (``create``/``get``/``list``/``update``/
    ``delete``) authenticate with the workspace API key. The signer-session
    methods (``get_self``/``accept_terms``/``verify_email``/``confirm_data``/
    ``upload_signature``/``download_signature``) authenticate with a
    per-signer access code obtained through the verification flow.
    """

    def create(
        self, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """``POST /accounts/{account_id}/signers`` — create a workspace signer.

        ``payload`` requires ``full_name``. Include ``email`` and/or
        ``whatsapp_phone_number`` (E.164, e.g. ``+5548999990000``) depending on
        the verification/notification channels you plan to use.

        Example request body (JSON)::

            {"full_name": "John Doe", "email": "john@example.com"}

        Example response (``data`` envelope unwrapped)::

            {"resource": "signer", "id": "1031ff86...", "full_name": "John Doe",
             "email": "john@example.com", "whatsapp_phone_number": null,
             "has_accepted_terms": false}
        """
        body = _build_signer_payload(payload, require_full_name=True)
        acc_id = self._account_id(account_id)
        self._logger.info("Creating signer", {"email": body.get("email")})
        return self._call(
            "Failed to create signer",
            lambda: self._http.post(f"accounts/{acc_id}/signers", json=body),
        )

    def get(self, signer_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/signers/{signer_id}`` — fetch one signer.

        Example response (``data`` envelope unwrapped)::

            {"resource": "signer", "id": "1031ff86...", "full_name": "John Doe",
             "email": "john@example.com", "whatsapp_phone_number": null,
             "has_accepted_terms": false}
        """
        acc_id = self._account_id(account_id)
        sid = self._require_id(signer_id, "Signer ID")
        return self._call(
            "Failed to fetch signer",
            lambda: self._http.get(f"accounts/{acc_id}/signers/{sid}"),
        )

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/signers`` — list workspace signers.

        ``params`` accepts ``page``, ``per_page`` (sent as ``per-page``),
        ``search``, ``sort``. Returns ``{"data": [...], "meta": {...}}``.

        Example response (``data`` envelope unwrapped)::

            {"data": [
                {"id": "19e6b92e...", "full_name": "John Doe",
                 "email": "john@example.com", "whatsapp_phone_number": null,
                 "has_accepted_terms": false}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 3, "last_page": 1}}
        """
        acc_id = self._account_id(account_id)
        cleaned = clean_params(params or {}, QUERY_PARAM_ALIASES)
        return self._call_list(
            "Failed to list signers",
            lambda: self._http.get(f"accounts/{acc_id}/signers", params=cleaned),
        )

    def update(
        self,
        signer_id: str,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/signers/{signer_id}`` — update a signer.

        Verification integrity rules apply server-side: ``email`` cannot be
        changed once email-verified for an in-flight document, and the same for
        ``whatsapp_phone_number``.

        Example request body (JSON)::

            {"full_name": "Johnny Doe"}

        Returns the updated signer object (``data`` envelope unwrapped).
        """
        acc_id = self._account_id(account_id)
        sid = self._require_id(signer_id, "Signer ID")
        body = _build_signer_payload(payload, require_full_name=False)
        if not body:
            raise ValidationError("At least one signer field is required")
        return self._call(
            "Failed to update signer",
            lambda: self._http.put(
                f"accounts/{acc_id}/signers/{sid}",
                json=body,
            ),
        )

    def delete(self, signer_id: str, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/signers/{signer_id}`` — delete a signer."""
        acc_id = self._account_id(account_id)
        sid = self._require_id(signer_id, "Signer ID")
        return self._call_void(
            "Failed to delete signer",
            lambda: self._http.delete(f"accounts/{acc_id}/signers/{sid}"),
        )

    def find_by_email(
        self, email: str, account_id: str | None = None
    ) -> dict[str, Any] | None:
        """Convenience wrapper around :meth:`list` that filters by exact email.

        Performs ``GET /accounts/{account_id}/signers?search={email}&per-page=100``
        and returns the first signer whose ``email`` matches case-insensitively,
        or ``None``.

        Example return value::

            {"id": "1031ff86...", "full_name": "John Doe",
             "email": "john@example.com", "whatsapp_phone_number": null,
             "has_accepted_terms": false}
        """
        _assert_email(email)
        try:
            result = self.list({"search": email, "per_page": 100}, account_id)
        except ApiError as err:
            if err.status_code == 404:
                return None
            raise
        target = email.lower()
        for signer in result.get("data", []):
            if (signer.get("email") or "").lower() == target:
                return signer
        return None

    def get_self(self, signer_access_code: str) -> dict[str, Any]:
        """``GET /signers/self?signer-access-code={access_code}`` — signer self-view.

        Adds ``has_signature`` / ``has_initial`` flags to the base signer fields.

        Example response (``data`` envelope unwrapped)::

            {"resource": "signer", "id": "1031ff86...", "full_name": "John Doe",
             "email": "john@example.com", "whatsapp_phone_number": null,
             "has_accepted_terms": true, "has_signature": true,
             "has_initial": false}
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._call(
            "Failed to fetch signer self",
            lambda: self._http.get(
                "signers/self",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
            ),
        )

    def accept_terms(self, signer_access_code: str) -> dict[str, Any]:
        """``PUT /signers/accept-terms`` — record terms acceptance for a signer.

        The access code is sent in the documented hyphenated body key.

        Example request body (JSON)::

            {"signer-access-code": "9uAWyOXx9hgz..."}
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._call(
            "Failed to accept signer terms",
            lambda: self._http.put(
                "signers/accept-terms",
                json={"signer-access-code": access_code},
            ),
        )

    def verify_email(
        self,
        signer_access_code: str,
        verification_code: str,
    ) -> dict[str, Any]:
        """``POST /verify`` — confirm the 6-digit token from ``send_token``.

        Both keys are sent in the documented hyphenated form.

        Example request body (JSON)::

            {"signer-access-code": "9uAWyOXx9hgz...", "verification-code": "123456"}
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        code = self._require_id(verification_code, "Verification code")
        return self._call(
            "Failed to verify signer email",
            lambda: self._http.post(
                "verify",
                json={
                    "signer-access-code": access_code,
                    "verification-code": code,
                },
            ),
        )

    def confirm_data(
        self,
        document_id: str,
        signer_access_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """``PUT /documents/{document_id}/signers/confirm-data``.

        ``payload`` may include ``email``, ``whatsapp_phone_number`` and
        ``has_accepted_terms``. Required fields depend on the signer's
        verification / notification channel(s) — see the API docs. The access
        code is sent as the ``signer-access-code`` query parameter.

        Example request body (JSON)::

            {"email": "john@example.com", "has_accepted_terms": true}
        """
        doc_id = self._require_id(document_id, "Document ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        if payload.get("email"):
            _assert_email(str(payload["email"]))
        body = clean_params(
            {
                "email": payload.get("email"),
                "whatsapp_phone_number": payload.get("whatsapp_phone_number"),
                "has_accepted_terms": payload.get("has_accepted_terms"),
            }
        )
        return self._call(
            "Failed to confirm signer data",
            lambda: self._http.put(
                f"documents/{doc_id}/signers/confirm-data",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json=body,
            ),
        )

    def upload_signature(
        self,
        signer_access_code: str,
        content: bytes,
        signature_type: str = "signature",
        content_type: str = "image/png",
    ) -> None:
        """``POST /signature?signer-access-code=...&type={signature|initial}``.

        Uploads the signer's signature (or initials) image. ``content`` is the
        raw image bytes, sent with a matching ``content_type`` (``image/png`` or
        ``image/jpeg`` per the docs).
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        _assert_signature_type(signature_type)
        if not content:
            raise ValidationError("Signature content is required")
        self._call_void(
            "Failed to upload signer signature",
            lambda: self._http.post(
                "signature",
                params=clean_params(
                    {
                        "signer_access_code": access_code,
                        "type": signature_type,
                    },
                    QUERY_PARAM_ALIASES,
                ),
                content=content,
                headers={"Content-Type": content_type},
            ),
        )

    def download_signature(
        self,
        signer_access_code: str,
        signature_type: str = "signature",
    ) -> bytes:
        """``GET /signature/{type}?signer-access-code=...`` — download signature bytes.

        ``signature_type`` is ``signature`` or ``initial``. Returns the raw
        image bytes.
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        _assert_signature_type(signature_type)
        return self._call_binary(
            "Failed to download signer signature",
            lambda: self._http.get(
                f"signature/{signature_type}",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
            ),
        )


def _build_signer_payload(
    payload: dict[str, Any], require_full_name: bool
) -> dict[str, Any]:
    full_name = payload.get("full_name")
    if require_full_name and not full_name:
        raise ValidationError("full_name is required")
    email = payload.get("email")
    if email:
        _assert_email(str(email))
    return clean_params(
        {
            "full_name": full_name,
            "email": email,
            "whatsapp_phone_number": payload.get("whatsapp_phone_number"),
        }
    )


def _assert_email(email: str) -> None:
    if not email or not _EMAIL_RE.match(email):
        raise ValidationError("Invalid email address", {"email": email})


def _assert_signature_type(signature_type: str) -> None:
    if signature_type not in _SIGNATURE_TYPES:
        raise ValidationError(
            "Signature type must be 'signature' or 'initial'",
            {"type": signature_type},
        )
