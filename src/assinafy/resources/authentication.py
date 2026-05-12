from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from .base import BaseResource


class AuthenticationResource(BaseResource):
    """Authentication endpoints (login, API keys, password management)."""

    def login(self, email: str, password: str) -> dict[str, Any]:
        """``POST /login`` — exchange email+password for an access token."""
        return self._call(
            "Failed to login",
            lambda: self._http.post(
                "login",
                json={
                    "email": _required(email, "Email"),
                    "password": _required(password, "Password"),
                },
            ),
        )

    def social_login(
        self,
        provider: str,
        token: str,
        has_accepted_terms: bool,
    ) -> dict[str, Any]:
        """``POST /authentication/social-login`` — exchange a provider token."""
        return self._call(
            "Failed to complete social login",
            lambda: self._http.post(
                "authentication/social-login",
                json={
                    "provider": _required(provider, "Provider"),
                    "token": _required(token, "Token"),
                    "has_accepted_terms": has_accepted_terms,
                },
            ),
        )

    def create_api_key(self, password: str) -> dict[str, Any]:
        """``POST /users/api-keys`` — create the current user's API key."""
        return self._call(
            "Failed to create API key",
            lambda: self._http.post(
                "users/api-keys",
                json={"password": _required(password, "Password")},
            ),
        )

    def get_api_key(self) -> dict[str, Any]:
        """``GET /users/api-keys`` — fetch the current user's masked API key."""
        return self._call(
            "Failed to fetch API key",
            lambda: self._http.get("users/api-keys"),
        )

    def delete_api_key(self) -> None:
        """``DELETE /users/api-keys`` — revoke the current user's API key."""
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
        """``PUT /authentication/change-password``."""
        return self._call(
            "Failed to change password",
            lambda: self._http.put(
                "authentication/change-password",
                json={
                    "email": _required(email, "Email"),
                    "password": _required(password, "Password"),
                    "new_password": _required(new_password, "New password"),
                },
            ),
        )

    def request_password_reset(self, email: str) -> dict[str, Any]:
        """``PUT /authentication/request-password-reset`` — email reset token."""
        return self._call(
            "Failed to request password reset",
            lambda: self._http.put(
                "authentication/request-password-reset",
                json={"email": _required(email, "Email")},
            ),
        )

    def reset_password(
        self,
        email: str,
        new_password: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /authentication/reset-password`` — complete password reset.

        Pass the ``token`` received via the reset email; omit to use legacy
        flows where the API derives the user from the session.
        """
        body: dict[str, Any] = {
            "email": _required(email, "Email"),
            "new_password": _required(new_password, "New password"),
        }
        if token is not None:
            body["token"] = _required(token, "Token")
        return self._call(
            "Failed to reset password",
            lambda: self._http.put("authentication/reset-password", json=body),
        )


def _required(value: str, name: str) -> str:
    if not value:
        raise ValidationError(f"{name} is required")
    return value
