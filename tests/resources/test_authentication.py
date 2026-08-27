from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.authentication import AuthenticationResource
from tests.conftest import make_envelope, make_response


class MockHttp:
    def __init__(self) -> None:
        self.last_url = ""
        self.last_kwargs: dict[str, object] = {}

    def post(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"ok": True}))

    def get(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"api_key": "***"}))

    def put(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"ok": True}))

    def delete(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope([]))


class TestAuthenticationResource:
    def test_login_posts_to_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = AuthenticationResource(http)

        resource.login("user@example.com", "secret")

        assert http.last_url == "login"
        assert http.last_kwargs["json"] == {
            "email": "user@example.com",
            "password": "secret",
        }

    def test_api_key_methods_hit_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = AuthenticationResource(http)

        resource.create_api_key("secret")
        assert http.last_url == "users/api-keys"
        assert http.last_kwargs["json"] == {"password": "secret"}

        resource.get_api_key()
        assert http.last_url == "users/api-keys"

        resource.delete_api_key()
        assert http.last_url == "users/api-keys"

    def test_get_api_key_returns_none_when_not_generated(self) -> None:
        class NullHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                self.last_url = url
                return make_response(make_envelope(None))

        resource = AuthenticationResource(NullHttp())
        assert resource.get_api_key() is None

    def test_social_login_posts_to_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = AuthenticationResource(http)

        resource.social_login("google", "provider-token", True)

        assert http.last_url == "authentication/social-login"
        assert http.last_kwargs["json"] == {
            "provider": "google",
            "token": "provider-token",
            "has_accepted_terms": True,
        }

    def test_link_social_login_posts_documented_no_data_request(self) -> None:
        http = MockHttp()
        resource = AuthenticationResource(http)

        resource.link_social_login("google", "provider-token")

        assert http.last_url == "auth/link-social-login"
        assert http.last_kwargs["json"] == {"provider": "google", "token": "provider-token"}

    def test_social_methods_validate_current_provider_and_boolean(self) -> None:
        resource = AuthenticationResource(MockHttp())
        with pytest.raises(ValidationError, match="provider"):
            resource.link_social_login("github", "token")
        with pytest.raises(ValidationError, match="provider"):
            resource.link_social_login([], "token")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="boolean"):
            resource.social_login("google", "token", 1)  # type: ignore[arg-type]

    def test_change_password_posts_to_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = AuthenticationResource(http)

        resource.change_password("user@example.com", "old-secret", "new-secret")

        assert http.last_url == "authentication/change-password"
        assert http.last_kwargs["json"] == {
            "email": "user@example.com",
            "password": "old-secret",
            "new_password": "new-secret",
        }

    def test_request_password_reset_posts_email_only(self) -> None:
        http = MockHttp()
        resource = AuthenticationResource(http)

        resource.request_password_reset("user@example.com")

        assert http.last_url == "authentication/request-password-reset"
        assert http.last_kwargs["json"] == {"email": "user@example.com"}

    def test_password_reset_omits_missing_token(self) -> None:
        http = MockHttp()
        resource = AuthenticationResource(http)

        resource.reset_password("user@example.com", "new-secret")

        assert http.last_url == "authentication/reset-password"
        assert http.last_kwargs["json"] == {
            "email": "user@example.com",
            "new_password": "new-secret",
        }

    def test_password_reset_includes_token_when_given(self) -> None:
        http = MockHttp()
        AuthenticationResource(http).reset_password("user@example.com", "new-secret", "reset-token")
        assert http.last_kwargs["json"] == {
            "email": "user@example.com",
            "new_password": "new-secret",
            "token": "reset-token",
        }

    @pytest.mark.parametrize(
        "call",
        [
            lambda resource: resource.login("invalid", "secret"),
            lambda resource: resource.change_password("invalid", "old", "new"),
            lambda resource: resource.request_password_reset("invalid"),
            lambda resource: resource.reset_password("invalid", "new"),
        ],
    )
    def test_email_flows_reject_invalid_addresses(self, call: object) -> None:
        resource = AuthenticationResource(MockHttp())
        with pytest.raises(ValidationError, match="email"):
            call(resource)  # type: ignore[operator]
