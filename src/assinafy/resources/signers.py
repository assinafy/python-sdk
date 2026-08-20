from __future__ import annotations

import re
from typing import Any

from ..errors import ApiError, ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SIGNATURE_TYPES = frozenset({"signature", "initial"})
_SIGNATURE_CONTENT_TYPES = frozenset({"image/png", "image/jpeg"})
_SIGNER_FIELDS = frozenset({"full_name", "email", "whatsapp_phone_number"})
_CONFIRM_DATA_FIELDS = frozenset(
    {"full_name", "email", "government_id", "whatsapp_phone_number", "has_accepted_terms"}
)


class SignerResource(BaseResource):
    """Signer endpoints — workspace CRUD plus signer-access-code flows.

    The account-scoped methods (``create``/``get``/``list``/``update``/
    ``delete``) authenticate with the workspace API key. The signer-session
    methods (``get_self``/``accept_terms``/``verify_email``/``confirm_data``/
    ``upload_signature``/``download_signature``) authenticate with a
    per-signer access code obtained through the verification flow.

    Signer-returning methods expose this complete unwrapped shape::

        {"resource": "signer", "id": "signer-id", "full_name": "Example Signer",
         "email": "signer@example.com", "whatsapp_phone_number": null,
         "has_accepted_terms": false}
    """

    def create(self, payload: dict[str, Any], account_id: str | None = None) -> dict[str, Any]:
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
        self._logger.info("Creating signer", {"has_email": bool(body.get("email"))})
        signer = self._call_dict(
            "Failed to create signer",
            lambda: self._http.post(f"accounts/{acc_id}/signers", json=body),
        )
        if not isinstance(signer.get("id"), str) or not signer["id"]:
            raise ValidationError("Signer creation succeeded without an ID", {"response": signer})
        return signer

    def get(self, signer_id: str, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/signers/{signer_id}`` — fetch one signer.

        Example response (``data`` envelope unwrapped)::

            {"resource": "signer", "id": "1031ff86...", "full_name": "John Doe",
             "email": "john@example.com", "whatsapp_phone_number": null,
             "has_accepted_terms": false}
        """
        acc_id = self._account_id(account_id)
        sid = self._path_id(signer_id, "Signer ID")
        return self._call_dict(
            "Failed to fetch signer",
            lambda: self._http.get(f"accounts/{acc_id}/signers/{sid}"),
        )

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /accounts/{account_id}/signers`` — list workspace signers.

        ``params`` accepts ``page``, ``per_page`` (sent as ``per-page``), and
        ``search``. Other keys are forwarded for compatibility with older
        deployments. Returns ``{"data": [...], "meta": {...}}``.

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
        sid = self._path_id(signer_id, "Signer ID")
        body = _build_signer_payload(payload, require_full_name=False)
        if payload.get("government_id") is not None:
            government_id = payload["government_id"]
            if not isinstance(government_id, str) or not government_id.strip():
                raise ValidationError("government_id must be a non-empty string")
            body["government_id"] = government_id
        if not body:
            raise ValidationError("At least one signer field is required")
        return self._call_dict(
            "Failed to update signer",
            lambda: self._http.put(
                f"accounts/{acc_id}/signers/{sid}",
                json=body,
            ),
        )

    def delete(self, signer_id: str, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/signers/{signer_id}`` — delete a signer.

        Request body: none. Success returns ``None``; the response has no
        ``data`` payload.
        """
        acc_id = self._account_id(account_id)
        sid = self._path_id(signer_id, "Signer ID")
        return self._call_void(
            "Failed to delete signer",
            lambda: self._http.delete(f"accounts/{acc_id}/signers/{sid}"),
        )

    def find_by_email(self, email: str, account_id: str | None = None) -> dict[str, Any] | None:
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
            if isinstance(signer, dict) and (signer.get("email") or "").lower() == target:
                return signer
        return None

    def get_self(self, signer_access_code: str) -> dict[str, Any]:
        """``GET /signers/self?signer-access-code={access_code}`` — signer self-view.

        Adds ``has_signature`` / ``has_initial`` flags to the base signer fields.

        Example response (``data`` envelope unwrapped)::

            {"resource": "signer", "id": "1031ff86...", "full_name": "John Doe",
             "email": "john@example.com", "whatsapp_phone_number": null,
             "has_accepted_terms": true, "has_signature": true,
             "has_initial": false, "is_signature_reusable": false}
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._call_dict(
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

        The access code is sent in the documented ``signer-access-code`` query
        parameter. The request has no body. Success returns the no-data envelope
        ``{"status": 200, "message": ""}``.
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._call_dict(
            "Failed to accept signer terms",
            lambda: self._http.put(
                "signers/accept-terms",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
            ),
        )

    def verify_email(
        self,
        signer_access_code: str,
        verification_code: str,
    ) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`verify_code`.

        The API code may arrive through email or WhatsApp; new callers should
        prefer the channel-neutral method name.
        """
        return self.verify_code(signer_access_code, verification_code)

    def verify_code(
        self,
        signer_access_code: str,
        verification_code: str,
    ) -> dict[str, Any]:
        """``POST /verify`` — confirm a signer verification code.

        The signer access code is sent in the documented query parameter; the
        verification code is the only JSON field. Success is a no-data envelope
        containing ``status`` and ``message``.

        Example request body (JSON)::

            {"verification-code": "123456"}

        Success returns the no-data envelope ``{"status": 200, "message": ""}``.
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        code = self._require_id(verification_code, "Verification code")
        return self._call_dict(
            "Failed to verify signer code",
            lambda: self._http.post(
                "verify",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json={"verification-code": code},
            ),
        )

    def confirm_data(
        self,
        document_id: str,
        signer_access_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """``PUT /documents/{document_id}/signers/confirm-data``.

        The current contract accepts ``full_name``, ``email``, and
        ``government_id``. ``whatsapp_phone_number`` and ``has_accepted_terms``
        remain accepted for compatibility with earlier deployed signer flows.
        Required fields depend on the signer's verification channel. The access
        code is sent as the ``signer-access-code`` query parameter.

        Example request body (JSON)::

            {"full_name": "Example Signer", "email": "signer@example.com",
             "government_id": "00000000000"}

        Returns the complete signer payload documented on :class:`SignerResource`.
        """
        doc_id = self._path_id(document_id, "Document ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        if not isinstance(payload, dict):
            raise ValidationError("Signer data must be a mapping")
        unknown = payload.keys() - _CONFIRM_DATA_FIELDS
        if unknown:
            raise ValidationError(f"Unknown signer-data fields: {', '.join(sorted(unknown))}")
        for field in ("full_name", "government_id", "whatsapp_phone_number"):
            value = payload.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValidationError(f"{field} must be a non-empty string")
        if payload.get("email") is not None:
            _assert_email(payload["email"])
        accepted_terms = payload.get("has_accepted_terms")
        if accepted_terms is not None and not isinstance(accepted_terms, bool):
            raise ValidationError("has_accepted_terms must be boolean")
        body = clean_params(
            {
                "full_name": payload.get("full_name"),
                "email": payload.get("email"),
                "government_id": payload.get("government_id"),
                "whatsapp_phone_number": payload.get("whatsapp_phone_number"),
                "has_accepted_terms": payload.get("has_accepted_terms"),
            }
        )
        if not body:
            raise ValidationError("At least one signer-data field is required")
        return self._call_dict(
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
        reuse: bool | None = None,
    ) -> None:
        """``POST /signature?signer-access-code=...&type={signature|initial}&reuse=...``.

        Uploads the signer's signature (or initials) image. ``content`` is the
        raw image bytes. The current contract publishes ``image/png``;
        ``image/jpeg`` remains supported for compatibility with earlier API
        documentation. ``reuse`` sets the signer's
        ``is_signature_reusable`` flag when given; omit it to leave the flag
        unchanged. Success is ``None``; the API envelope contains only
        ``status`` and ``message``.
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        _assert_signature_type(signature_type)
        if not isinstance(content, (bytes, bytearray, memoryview)) or not content:
            raise ValidationError("Signature content is required")
        if not isinstance(content_type, str) or content_type not in _SIGNATURE_CONTENT_TYPES:
            raise ValidationError("Signature content type must be image/png or image/jpeg")
        if reuse is not None and not isinstance(reuse, bool):
            raise ValidationError("reuse must be boolean")
        self._call_void(
            "Failed to upload signer signature",
            lambda: self._http.post(
                "signature",
                params=clean_params(
                    {
                        "signer_access_code": access_code,
                        "type": signature_type,
                        "reuse": reuse,
                    },
                    QUERY_PARAM_ALIASES,
                ),
                content=bytes(content),
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


def _build_signer_payload(payload: dict[str, Any], require_full_name: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Signer payload must be a mapping")
    allowed = _SIGNER_FIELDS if require_full_name else _SIGNER_FIELDS | {"government_id"}
    unknown = payload.keys() - allowed
    if unknown:
        raise ValidationError(f"Unknown signer fields: {', '.join(sorted(unknown))}")
    full_name = payload.get("full_name")
    if require_full_name and (not isinstance(full_name, str) or not full_name.strip()):
        raise ValidationError("full_name is required")
    if full_name is not None and (not isinstance(full_name, str) or not full_name.strip()):
        raise ValidationError("full_name must be a non-empty string")
    email = payload.get("email")
    if email is not None:
        _assert_email(email)
    phone = payload.get("whatsapp_phone_number")
    if phone is not None and (not isinstance(phone, str) or not phone.strip()):
        raise ValidationError("whatsapp_phone_number must be a non-empty string")
    return clean_params(
        {
            "full_name": full_name,
            "email": email,
            "whatsapp_phone_number": phone,
        }
    )


def _assert_email(email: str) -> None:
    if not isinstance(email, str) or not email or not _EMAIL_RE.match(email):
        raise ValidationError("Invalid email address", {"email": email})


def _assert_signature_type(signature_type: str) -> None:
    if not isinstance(signature_type, str) or signature_type not in _SIGNATURE_TYPES:
        raise ValidationError(
            "Signature type must be 'signature' or 'initial'",
            {"type": signature_type},
        )
