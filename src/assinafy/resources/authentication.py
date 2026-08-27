from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import validate_email
from .base import BaseResource

_SOCIAL_PROVIDERS = frozenset({"google"})


class AuthenticationResource(BaseResource):
    """Authentication endpoints (login, API keys, password management).

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
        return self._call_dict(
            "Failed to login",
            lambda: self._http.post(
                "login",
                json={
                    "email": validate_email(email),
                    "password": self._require_id(password, "Password"),
                },
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

        Returns the same ``{access_token, user, accounts}`` shape as
        :meth:`login` (``data`` envelope unwrapped).
        """
        _validate_social_provider(provider)
        if not isinstance(has_accepted_terms, bool):
            raise ValidationError("has_accepted_terms must be boolean")
        return self._call_dict(
            "Failed to complete social login",
            lambda: self._http.post(
                "authentication/social-login",
                json={
                    "provider": self._require_id(provider, "Provider"),
                    "token": self._require_id(token, "Token"),
                    "has_accepted_terms": has_accepted_terms,
                },
            ),
        )

    def link_social_login(self, provider: str, token: str) -> None:
        """``POST /auth/link-social-login`` — link a provider to this user.

        Sends ``{"provider": "google", "token": "provider-token"}``. The
        documented success response is ``{"status": 200, "message": ""}``
        with no data payload.
        """
        _validate_social_provider(provider)
        self._call_void(
            "Failed to link social login",
            lambda: self._http.post(
                "auth/link-social-login",
                json={
                    "provider": self._require_id(provider, "Provider"),
                    "token": self._require_id(token, "Token"),
                },
            ),
        )

    def create_api_key(self, password: str) -> dict[str, Any]:
        """``POST /users/api-keys`` — create the current user's API key.

        Example request body (JSON)::

            {"password": "secret"}

        Example response (``data`` envelope unwrapped)::

            {"api_key": "sandbox_example_api_key_replace_me"}
        """
        return self._call_dict(
            "Failed to create API key",
            lambda: self._http.post(
                "users/api-keys",
                json={"password": self._require_id(password, "Password")},
            ),
        )

    def get_api_key(self) -> dict[str, Any] | None:
        """``GET /users/api-keys`` — fetch the current user's masked API key.

        Returns ``None`` while no API key has been generated yet (the API
        returns a ``null`` ``data`` field in that case).

        Example response (``data`` envelope unwrapped)::

            {"api_key": "************************************last4"}
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
        return self._call_dict(
            "Failed to change password",
            lambda: self._http.put(
                "authentication/change-password",
                json={
                    "email": validate_email(email),
                    "password": self._require_id(password, "Password"),
                    "new_password": self._require_id(new_password, "New password"),
                },
            ),
        )

    def request_password_reset(self, email: str) -> dict[str, Any]:
        """``PUT /authentication/request-password-reset`` — email a reset token.

        Example request body (JSON)::

            {"email": "john@example.com"}

        Example response (``data`` envelope unwrapped)::

            {"email": "john@example.com"}
        """
        return self._call_dict(
            "Failed to request password reset",
            lambda: self._http.put(
                "authentication/request-password-reset",
                json={"email": validate_email(email)},
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
