from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import validate_email
from .base import BaseResource

_SOCIAL_PROVIDERS = frozenset({"google"})


class AuthenticationResource(BaseResource):
    """Authentication endpoints (login, two-factor, API keys, password management).

    All request bodies use underscore-cased keys (the docs do not hyphenate any
    field in this area). Responses are unwrapped from the ``{status, data,
    message}`` envelope. Login methods return this complete session shape::

        {"access_token": "synthetic-jwt",
         "user": {"id": "user-id", "name": "Example User",
                  "email": "user@example.com", "telephone": null,
                  "government_id": null, "is_email_verified": true,
                  "has_accepted_terms": true,
                  "created_at": "2026-06-03T03:54:16Z",
                  "to_be_deleted_at": null},
         "accounts": [{"id": "account-id", "name": "Acme Inc.",
                       "roles": ["owner"], "is_delete_allowed": true,
                       "created_at": "2026-06-03T03:54:16Z"}]}
    """

    def login(self, email: str, password: str) -> dict[str, Any]:
        """``POST /login`` — exchange email + password for an access token.

        When the user has two-factor authentication enabled, the response
        carries an ``mfa_token`` instead of a session; pass it with the
        user's authenticator or recovery code to :meth:`verify_mfa` within
        5 minutes to receive the session below.

        Example request body (JSON)::

            {"email": "john@example.com", "password": "secret"}

        Example response (``data`` envelope unwrapped)::

            {"access_token": "synthetic-jwt",
             "user": {"id": "user-id", "name": "Example User",
                      "email": "user@example.com", "telephone": null,
                      "government_id": null, "is_email_verified": true,
                      "has_accepted_terms": true,
                      "created_at": "2026-06-03T03:54:16Z",
                      "to_be_deleted_at": null},
             "accounts": [{"id": "account-id", "name": "Acme Inc.",
                           "roles": ["owner"], "is_delete_allowed": true,
                           "created_at": "2026-06-03T03:54:16Z"}]}
        """
        body = {"email": validate_email(email), "password": self._require_id(password, "Password")}
        return self._call_dict(
            "Failed to login",
            lambda: self._http.post(
                "login",
                json=body,
            ),
        )

    def social_login(
        self,
        provider: str,
        token: str,
        has_accepted_terms: bool,
    ) -> dict[str, Any]:
        """``POST /authentication/social-login`` — exchange a provider token.

        Example request body (JSON)::

            {"provider": "google", "token": "ya29.a0Af...",
             "has_accepted_terms": true}

        Example response (``data`` envelope unwrapped)::

            {"access_token": "synthetic-jwt",
             "user": {"id": "user-id", "name": "Example User",
                      "email": "user@example.com", "telephone": null,
                      "government_id": null, "is_email_verified": true,
                      "has_accepted_terms": true,
                      "created_at": "2026-06-03T03:54:16Z",
                      "to_be_deleted_at": null},
             "accounts": [{"id": "account-id", "name": "Acme Inc.",
                           "roles": ["owner"], "is_delete_allowed": true,
                           "created_at": "2026-06-03T03:54:16Z"}]}
        """
        _validate_social_provider(provider)
        if not isinstance(has_accepted_terms, bool):
            raise ValidationError("has_accepted_terms must be boolean")
        body = {
            "provider": provider,
            "token": self._require_id(token, "Token"),
            "has_accepted_terms": has_accepted_terms,
        }
        return self._call_dict(
            "Failed to complete social login",
            lambda: self._http.post(
                "authentication/social-login",
                json=body,
            ),
        )

    def link_social_login(self, provider: str, token: str) -> None:
        """``POST /auth/link-social-login`` — link a provider to this user.

        Sends ``{"provider": "google", "token": "provider-token"}``. The
        documented success response is ``{"status": 200, "message": ""}``
        with no data payload.
        """
        _validate_social_provider(provider)
        body = {"provider": provider, "token": self._require_id(token, "Token")}
        self._call_void(
            "Failed to link social login",
            lambda: self._http.post(
                "auth/link-social-login",
                json=body,
            ),
        )

    def verify_mfa(self, mfa_token: str, code: str) -> dict[str, Any]:
        """``POST /authentication/mfa/verify`` — complete a two-factor login.

        Exchanges the ``mfa_token`` returned by :meth:`login` for a session.
        ``code`` is the 6-digit authenticator code or one of the recovery codes
        issued at enrollment. The challenge is single-use and expires 5 minutes
        after login; an expired, reused or over-tried challenge raises
        :class:`~assinafy.errors.ApiError` with status ``401``. The operation
        is public: the client sends no API key or bearer token with it.

        Example request body (JSON)::

            {"mfa_token": "synthetic-mfa-token", "code": "123456"}

        Example response (``data`` envelope unwrapped)::

            {"access_token": "synthetic-jwt",
             "user": {"id": "user-id", "name": "Example User",
                      "email": "user@example.com", "telephone": null,
                      "government_id": null, "is_email_verified": true,
                      "has_accepted_terms": true,
                      "created_at": "2026-06-03T03:54:16Z",
                      "to_be_deleted_at": null},
             "accounts": [{"id": "account-id", "name": "Acme Inc.",
                           "roles": ["owner"], "is_delete_allowed": true,
                           "created_at": "2026-06-03T03:54:16Z"}]}
        """
        body = {
            "mfa_token": self._require_id(mfa_token, "MFA token"),
            "code": self._require_id(code, "Code"),
        }
        return self._call_dict(
            "Failed to verify two-factor code",
            lambda: self._http.post("authentication/mfa/verify", json=body),
        )

    def list_mfa_methods(self) -> dict[str, Any]:
        """``GET /users/self/mfa`` — enrolled two-factor methods.

        Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"methods": [{"id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
                          "type": "Totp", "label": "My phone",
                          "confirmed_at": "2026-09-09T14:21:03Z",
                          "last_used_at": "2026-09-09T18:02:44Z"}],
             "recovery_codes_remaining": 8}
        """
        return self._call_dict(
            "Failed to list two-factor methods", lambda: self._http.get("users/self/mfa")
        )

    def start_totp_enrollment(self, label: str | None = None) -> dict[str, Any]:
        """``POST /users/self/mfa/totp`` — start authenticator-app enrollment.

        Creates an unconfirmed method and returns its shared ``secret`` and
        ``provisioning_uri`` (render it as a QR code). The secret is returned
        only by this call. Two-factor authentication stays off until
        :meth:`confirm_totp_enrollment` succeeds.

        Example request body (JSON; ``label`` is optional)::

            {"label": "My phone"}

        Example response (``data`` envelope unwrapped)::

            {"id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
             "secret": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
             "provisioning_uri": "otpauth://totp/user%40example.com?issuer=Assinafy&secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"}
        """
        body = {} if label is None else {"label": self._require_id(label, "Label")}
        return self._call_dict(
            "Failed to start authenticator enrollment",
            lambda: self._http.post("users/self/mfa/totp", json=body),
        )

    def confirm_totp_enrollment(
        self,
        method_id: str,
        code: str,
        *,
        password: str | None = None,
        reauth_code: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /users/self/mfa/totp/confirm`` — activate an authenticator.

        ``code`` is a live code from the new device. Returns the recovery
        codes, which are shown only once; from then on every login needs a
        second factor. Confirming while another authenticator is already
        active replaces it and reissues the recovery codes, so that case also
        needs ``password`` or ``reauth_code`` (a live code from the current
        device, or an existing recovery code). First-time enrollment needs
        neither.

        Example request body (JSON)::

            {"id": "a1b2c3d4e5f60718293a4b5c6d7e8f90", "code": "123456"}

        Example response (``data`` envelope unwrapped)::

            {"recovery_codes": ["ABCD-EFGH-JKMN", "PQRS-TUVW-XYZA"]}
        """
        body: dict[str, Any] = {
            "id": self._require_id(method_id, "Method ID"),
            "code": self._require_id(code, "Code"),
        }
        if password is not None:
            body["password"] = self._require_id(password, "Password")
        if reauth_code is not None:
            body["reauth_code"] = self._require_id(reauth_code, "Re-authentication code")
        return self._call_dict(
            "Failed to confirm authenticator enrollment",
            lambda: self._http.put("users/self/mfa/totp/confirm", json=body),
        )

    def regenerate_recovery_codes(
        self, *, password: str | None = None, code: str | None = None
    ) -> dict[str, Any]:
        """``POST /users/self/mfa/recovery-codes`` — issue ten new recovery codes.

        Invalidates the previous set. Requires ``password`` or ``code`` (a live
        authenticator code, or an existing recovery code, which is consumed).

        Example request body (JSON)::

            {"code": "123456"}

        Example response (``data`` envelope unwrapped)::

            {"recovery_codes": ["ABCD-EFGH-JKMN", "PQRS-TUVW-XYZA"]}
        """
        body = self._reauth_body(password, code)
        return self._call_dict(
            "Failed to regenerate recovery codes",
            lambda: self._http.post("users/self/mfa/recovery-codes", json=body),
        )

    def delete_mfa_method(
        self, method_id: str, *, password: str | None = None, code: str | None = None
    ) -> dict[str, Any]:
        """``DELETE /users/self/mfa/{method_id}`` — remove a two-factor method.

        Requires ``password`` or ``code`` (a live authenticator code, or an
        existing recovery code, which is consumed) so a stolen session cannot
        silently disable two-factor authentication. Removing the last method
        also discards the recovery codes.

        Example request body (JSON)::

            {"password": "secret"}

        Example response (``data`` envelope unwrapped)::

            {"is_mfa_enabled": false}
        """
        mid = self._path_id(method_id, "Method ID")
        body = self._reauth_body(password, code)
        return self._call_dict(
            "Failed to remove two-factor method",
            lambda: self._http.request("DELETE", f"users/self/mfa/{mid}", json=body),
        )

    def _reauth_body(self, password: str | None, code: str | None) -> dict[str, str]:
        if password is None and code is None:
            raise ValidationError("password or code is required")
        body: dict[str, str] = {}
        if password is not None:
            body["password"] = self._require_id(password, "Password")
        if code is not None:
            body["code"] = self._require_id(code, "Code")
        return body

    def create_api_key(self, password: str) -> dict[str, Any]:
        """``POST /users/api-keys`` — create the current user's API key.

        Example request body (JSON)::

            {"password": "secret"}

        Example response (``data`` envelope unwrapped)::

            {"api_key": "sandbox_example_api_key_replace_me"}
        """
        body = {"password": self._require_id(password, "Password")}
        return self._call_dict(
            "Failed to create API key",
            lambda: self._http.post(
                "users/api-keys",
                json=body,
            ),
        )

    def get_api_key(self) -> dict[str, Any] | None:
        """``GET /users/api-keys`` — fetch the current user's masked API key.

        Returns ``None`` while no API key has been generated yet (the API
        returns a ``null`` ``data`` field in that case).

        Example response (``data`` envelope unwrapped)::

            {"api_key": "************************************last4"}

        Request body: none.
        """
        return self._call_nullable_dict(
            "Failed to fetch API key",
            lambda: self._http.get("users/api-keys"),
        )

    def delete_api_key(self) -> None:
        """``DELETE /users/api-keys`` — revoke the current user's API key.

        Request body: none. OpenAPI returns ``data: []`` on success; the SDK
        maps that empty result to ``None``.
        """
        self._call_void(
            "Failed to delete API key",
            lambda: self._http.delete("users/api-keys"),
        )

    def change_password(
        self,
        email: str,
        password: str,
        new_password: str,
    ) -> dict[str, Any]:
        """``PUT /authentication/change-password`` — change a known password.

        Example request body (JSON)::

            {"email": "john@example.com", "password": "old-secret",
             "new_password": "new-secret"}

        Example response (``data`` envelope unwrapped)::

            {"email": "john@example.com"}
        """
        body = {
            "email": validate_email(email),
            "password": self._require_id(password, "Password"),
            "new_password": self._require_id(new_password, "New password"),
        }
        return self._call_dict(
            "Failed to change password",
            lambda: self._http.put(
                "authentication/change-password",
                json=body,
            ),
        )

    def request_password_reset(self, email: str) -> dict[str, Any]:
        """``PUT /authentication/request-password-reset`` — email a reset token.

        Example request body (JSON)::

            {"email": "john@example.com"}

        Example response (``data`` envelope unwrapped)::

            {"email": "john@example.com"}
        """
        body = {"email": validate_email(email)}
        return self._call_dict(
            "Failed to request password reset",
            lambda: self._http.put(
                "authentication/request-password-reset",
                json=body,
            ),
        )

    def reset_password(
        self,
        email: str,
        new_password: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /authentication/reset-password`` — complete a password reset.

        Pass the ``token`` received via the reset email. ``token`` is optional
        in the documented request; omit it only if your flow does not use one.

        Example request body (JSON)::

            {"email": "john@example.com", "token": "b3ac64d6c55...",
             "new_password": "new-secret"}

        Example response (``data`` envelope unwrapped)::

            {"email": "john@example.com"}
        """
        body: dict[str, Any] = {
            "email": validate_email(email),
            "new_password": self._require_id(new_password, "New password"),
        }
        if token is not None:
            body["token"] = self._require_id(token, "Token")
        return self._call_dict(
            "Failed to reset password",
            lambda: self._http.put("authentication/reset-password", json=body),
        )


def _validate_social_provider(provider: str) -> None:
    if not isinstance(provider, str) or provider not in _SOCIAL_PROVIDERS:
        raise ValidationError('provider must be "google"')
