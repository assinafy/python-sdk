from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from assinafy.client import AssinafyClient
from assinafy.errors import ApiError, ValidationError
from assinafy.resources.oauth import DEFAULT_ISSUER, OAuthResource

CALLBACK = "https://myapp.example/oauth/callback"


def _client(handler: Any = None) -> AssinafyClient:
    client = AssinafyClient(api_key="workspace-key", account_id="acc")
    if handler is not None:
        client._http._transport = httpx.MockTransport(handler)
    return client


def _oauth(handler: Any = None, secret: str | None = "client-secret") -> OAuthResource:
    return _client(handler).oauth("client-id", secret)


class TestStartAuthorization:
    def test_builds_the_documented_authorization_url(self) -> None:
        start = _oauth().start_authorization(CALLBACK, ["documents:read", "webhooks:write"])

        parsed = urlsplit(start["authorization_url"])
        query = {key: value[0] for key, value in parse_qs(parsed.query).items()}
        assert (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{DEFAULT_ISSUER}/oauth/authorize"
        )
        assert query == {
            "response_type": "code",
            "client_id": "client-id",
            "redirect_uri": CALLBACK,
            "scope": "documents:read webhooks:write",
            "state": start["state"],
            "code_challenge": start["code_challenge"],
            "code_challenge_method": "S256",
            "resource": "https://api.assinafy.com.br",
        }

    def test_encodes_scope_separator_as_rfc3986_space(self) -> None:
        start = _oauth().start_authorization(CALLBACK, ["documents:read", "openid"])

        assert "scope=documents%3Aread%20openid" in start["authorization_url"]
        assert "+openid" not in start["authorization_url"]

    def test_returns_a_transaction_the_later_steps_need(self) -> None:
        start = _oauth().start_authorization(CALLBACK, ["documents:read"])

        assert start["redirect_uri"] == CALLBACK
        assert start["issuer"] == DEFAULT_ISSUER
        assert start["resource"] == "https://api.assinafy.com.br"
        assert 43 <= len(start["code_verifier"]) <= 128
        assert "nonce" not in start

    def test_derives_the_s256_challenge_from_the_verifier(self) -> None:
        start = _oauth().start_authorization(CALLBACK, ["documents:read"])

        digest = hashlib.sha256(start["code_verifier"].encode("ascii")).digest()
        assert start["code_challenge"] == base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def test_mints_fresh_material_for_every_attempt(self) -> None:
        oauth = _oauth()

        first = oauth.start_authorization(CALLBACK, ["documents:read"])
        second = oauth.start_authorization(CALLBACK, ["documents:read"])

        assert first["state"] != second["state"]
        assert first["code_verifier"] != second["code_verifier"]

    def test_adds_a_nonce_only_for_the_openid_scope(self) -> None:
        start = _oauth().start_authorization(CALLBACK, ["openid", "profile"])

        assert start["nonce"]
        assert f"nonce={start['nonce']}" in start["authorization_url"]

    def test_accepts_caller_supplied_session_material(self) -> None:
        verifier = "a" * 43
        start = _oauth().start_authorization(
            CALLBACK,
            ["openid"],
            issuer="https://auth.example.test/",
            authorization_endpoint="https://auth.example.test/custom/authorize",
            state="my-state",
            nonce="my-nonce",
            code_verifier=verifier,
            resource="https://api.example.test",
        )

        assert start["code_verifier"] == verifier
        assert start["state"] == "my-state"
        assert start["nonce"] == "my-nonce"
        assert start["issuer"] == "https://auth.example.test"
        assert start["resource"] == "https://api.example.test"
        assert start["authorization_url"].startswith("https://auth.example.test/custom/authorize?")

    def test_resource_defaults_to_the_configured_api_origin(self) -> None:
        client = AssinafyClient(base_url="https://sandbox.assinafy.com.br/v1")
        start = client.oauth("client-id").start_authorization(CALLBACK, ["documents:read"])

        assert start["resource"] == "https://sandbox.assinafy.com.br"
        client.close()

    @pytest.mark.parametrize(
        "redirect_uri",
        [
            "http://myapp.example/callback",
            "http://localhost:3000/callback",
            "https://myapp.example/callback#fragment",
            "not-a-url",
            "https://[oops/callback",
            "",
            None,
        ],
    )
    def test_rejects_an_unusable_redirect_uri(self, redirect_uri: Any) -> None:
        with pytest.raises(ValidationError, match="Redirect URI"):
            _oauth().start_authorization(redirect_uri, ["documents:read"])

    @pytest.mark.parametrize("scopes", [[], "documents:read", ["documents:read openid"], [""]])
    def test_rejects_an_unusable_scope_list(self, scopes: Any) -> None:
        with pytest.raises(ValidationError, match="scope"):
            _oauth().start_authorization(CALLBACK, scopes)

    @pytest.mark.parametrize("verifier", ["too-short", "a" * 129, "a" * 42, "!" * 43])
    def test_rejects_a_verifier_outside_the_rfc7636_grammar(self, verifier: str) -> None:
        with pytest.raises(ValidationError, match="code verifier"):
            _oauth().start_authorization(CALLBACK, ["documents:read"], code_verifier=verifier)

    def test_rejects_a_plaintext_issuer(self) -> None:
        with pytest.raises(ValidationError, match="https"):
            _oauth().start_authorization(
                CALLBACK, ["documents:read"], issuer="http://auth.example.test"
            )

    def test_rejects_blank_client_credentials(self) -> None:
        client = _client()
        with pytest.raises(ValidationError, match="client_id"):
            client.oauth("  ")
        with pytest.raises(ValidationError, match="client_secret"):
            client.oauth("client-id", "  ")
        client.close()

    def test_repr_never_renders_the_client_secret(self) -> None:
        assert repr(_oauth()) == "OAuthResource(client_id='client-id', client_type='confidential')"
        assert repr(_oauth(secret=None)).endswith("client_type='public')")


class TestHandleCallback:
    def test_returns_the_code_from_an_approved_callback(self) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        code = oauth.handle_callback(
            {"code": "auth-code", "state": start["state"], "iss": DEFAULT_ISSUER}, start
        )

        assert code == "auth-code"

    def test_tolerates_a_trailing_slash_on_the_returned_issuer(self) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        assert (
            oauth.handle_callback(
                {"code": "auth-code", "state": start["state"], "iss": f"{DEFAULT_ISSUER}/"}, start
            )
            == "auth-code"
        )

    def test_rejects_a_mismatched_state(self) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        with pytest.raises(ValidationError, match="state does not match"):
            oauth.handle_callback({"code": "c", "state": "other", "iss": DEFAULT_ISSUER}, start)

    def test_rejects_a_missing_state(self) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        with pytest.raises(ValidationError, match="state does not match"):
            oauth.handle_callback({"code": "c", "iss": DEFAULT_ISSUER}, start)

    def test_rejects_a_transaction_without_state(self) -> None:
        with pytest.raises(ValidationError, match="missing its state"):
            _oauth().handle_callback({"code": "c"}, {})

    @pytest.mark.parametrize("issuer", [None, "https://evil.example", ""])
    def test_rejects_a_wrong_or_absent_issuer(self, issuer: str | None) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])
        query: dict[str, Any] = {"code": "c", "state": start["state"]}
        if issuer is not None:
            query["iss"] = issuer

        with pytest.raises(ValidationError, match="issuer does not match"):
            oauth.handle_callback(query, start)

    def test_raises_the_rfc_error_code_when_the_user_declines(self) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        with pytest.raises(ApiError) as excinfo:
            oauth.handle_callback(
                {
                    "error": "access_denied",
                    "error_description": "The user declined.",
                    "state": start["state"],
                    "iss": DEFAULT_ISSUER,
                },
                start,
            )

        assert str(excinfo.value) == "access_denied"
        assert excinfo.value.status_code == 400
        assert excinfo.value.response_data == {
            "error": "access_denied",
            "error_description": "The user declined.",
        }

    def test_rejects_a_callback_without_a_code(self) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        with pytest.raises(ValidationError, match="authorization code"):
            oauth.handle_callback({"state": start["state"], "iss": DEFAULT_ISSUER}, start)

    def test_rejects_non_mapping_input(self) -> None:
        with pytest.raises(ValidationError, match="mappings"):
            _oauth().handle_callback("code=x", {})  # type: ignore[arg-type]


class TestTokenEndpoints:
    def _recording_oauth(self, secret: str | None = "client-secret") -> tuple[Any, list[Any]]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/oauth/revoke"):
                return httpx.Response(200, content=b"")
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "documents:read",
                    "refresh_token": "new-refresh-token",
                },
            )

        return _oauth(handler, secret), seen

    def test_exchange_code_posts_the_documented_form_body(self) -> None:
        oauth, seen = self._recording_oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        tokens = oauth.exchange_code("auth-code", start)

        assert tokens["access_token"] == "new-access-token"
        assert str(seen[0].url) == "https://api.assinafy.com.br/v1/oauth/token"
        assert seen[0].headers["content-type"] == "application/x-www-form-urlencoded"
        assert {k: v[0] for k, v in parse_qs(seen[0].content.decode()).items()} == {
            "grant_type": "authorization_code",
            "code": "auth-code",
            "redirect_uri": CALLBACK,
            "code_verifier": start["code_verifier"],
            "resource": "https://api.assinafy.com.br",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }

    def test_public_clients_omit_the_client_secret(self) -> None:
        oauth, seen = self._recording_oauth(secret=None)
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        oauth.exchange_code("auth-code", start)

        assert "client_secret" not in parse_qs(seen[0].content.decode())

    def test_refresh_posts_the_documented_form_body(self) -> None:
        oauth, seen = self._recording_oauth()

        tokens = oauth.refresh("current-refresh-token")

        assert tokens["refresh_token"] == "new-refresh-token"
        assert {k: v[0] for k, v in parse_qs(seen[0].content.decode()).items()} == {
            "grant_type": "refresh_token",
            "refresh_token": "current-refresh-token",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }

    def test_revoke_posts_the_documented_form_body_and_returns_none(self) -> None:
        oauth, seen = self._recording_oauth()

        assert oauth.revoke("the-token", "refresh_token") is None
        assert str(seen[0].url) == "https://api.assinafy.com.br/v1/oauth/revoke"
        assert {k: v[0] for k, v in parse_qs(seen[0].content.decode()).items()} == {
            "token": "the-token",
            "token_type_hint": "refresh_token",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }

    def test_revoke_omits_an_absent_hint(self) -> None:
        oauth, seen = self._recording_oauth()

        oauth.revoke("the-token")

        assert "token_type_hint" not in parse_qs(seen[0].content.decode())

    def test_token_requests_never_carry_the_workspace_credentials(self) -> None:
        oauth, seen = self._recording_oauth()

        oauth.refresh("rt")
        oauth.revoke("rt")

        for request in seen:
            assert "X-Api-Key" not in request.headers
            assert "Authorization" not in request.headers

    def test_surfaces_the_flat_oauth_error_code_as_the_message(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": "The authorization code has expired.",
                },
            )

        with pytest.raises(ApiError) as excinfo:
            _oauth(handler).refresh("stale-token")

        assert str(excinfo.value) == "invalid_grant"
        assert excinfo.value.status_code == 400
        assert excinfo.value.response_data["error_description"] == (
            "The authorization code has expired."
        )

    @pytest.mark.parametrize("token", ["", "   "])
    def test_rejects_an_empty_refresh_token(self, token: str) -> None:
        with pytest.raises(ValidationError, match="Refresh token"):
            _oauth().refresh(token)

    def test_rejects_an_empty_revocation_token(self) -> None:
        with pytest.raises(ValidationError, match="Token is required"):
            _oauth().revoke("")

    def test_rejects_an_unknown_token_type_hint(self) -> None:
        with pytest.raises(ValidationError, match="token_type_hint"):
            _oauth().revoke("t", "id_token")  # type: ignore[arg-type]

    def test_rejects_an_empty_authorization_code(self) -> None:
        oauth = _oauth()
        start = oauth.start_authorization(CALLBACK, ["documents:read"])

        with pytest.raises(ValidationError, match="Authorization code"):
            oauth.exchange_code("", start)

    @pytest.mark.parametrize(
        ("transaction", "expected"),
        [
            ({}, "code verifier"),
            ({"code_verifier": "a" * 43}, "redirect URI"),
        ],
    )
    def test_rejects_an_incomplete_transaction(
        self, transaction: dict[str, Any], expected: str
    ) -> None:
        with pytest.raises(ValidationError, match=expected):
            _oauth().exchange_code("code", transaction)

    def test_rejects_a_non_mapping_transaction(self) -> None:
        with pytest.raises(ValidationError, match="transaction must be a mapping"):
            _oauth().exchange_code("code", "code_verifier=x")  # type: ignore[arg-type]

    def test_falls_back_to_the_api_origin_when_the_transaction_omits_resource(self) -> None:
        oauth, seen = self._recording_oauth()

        oauth.exchange_code("code", {"code_verifier": "a" * 43, "redirect_uri": CALLBACK})

        body = parse_qs(seen[0].content.decode())
        assert body["resource"] == ["https://api.assinafy.com.br"]


class TestUserinfo:
    def test_sends_the_supplied_bearer_token_and_drops_the_api_key(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "sub": "d6zqpbyog2v3xvxerwn8la94",
                    "name": "Example User",
                    "email": "person@example.com",
                    "email_verified": True,
                },
            )

        claims = _oauth(handler).userinfo("the-access-token")

        assert claims["sub"] == "d6zqpbyog2v3xvxerwn8la94"
        assert str(seen[0].url) == "https://api.assinafy.com.br/v1/oauth/userinfo"
        assert seen[0].headers["Authorization"] == "Bearer the-access-token"
        assert "X-Api-Key" not in seen[0].headers

    def test_rejects_an_empty_access_token(self) -> None:
        with pytest.raises(ValidationError, match="Access token"):
            _oauth().userinfo("")

    def test_surfaces_an_enveloped_insufficient_scope_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403, json={"status": 403, "data": None, "message": "Escopo insuficiente."}
            )

        with pytest.raises(ApiError) as excinfo:
            _oauth(handler).userinfo("the-access-token")

        assert excinfo.value.status_code == 403
        assert str(excinfo.value) == "Escopo insuficiente."


class TestDiscovery:
    def test_reads_the_protected_resource_metadata_from_the_api_origin(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "resource": "https://api.assinafy.com.br",
                    "authorization_servers": ["https://auth.assinafy.com.br"],
                    "scopes_supported": ["documents:read"],
                    "bearer_methods_supported": ["header"],
                },
            )

        metadata = _oauth(handler).protected_resource_metadata()

        assert metadata["authorization_servers"] == ["https://auth.assinafy.com.br"]
        assert str(seen[0].url) == (
            "https://api.assinafy.com.br/.well-known/oauth-protected-resource"
        )
        assert "X-Api-Key" not in seen[0].headers

    def test_reads_the_authorization_server_metadata_from_the_issuer(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"issuer": DEFAULT_ISSUER})

        oauth = _oauth(handler)

        assert oauth.authorization_server_metadata()["issuer"] == DEFAULT_ISSUER
        assert str(seen[0].url) == (
            "https://auth.assinafy.com.br/.well-known/oauth-authorization-server"
        )
        assert "X-Api-Key" not in seen[0].headers

        oauth.authorization_server_metadata("https://auth.example.test/")
        assert str(seen[1].url) == (
            "https://auth.example.test/.well-known/oauth-authorization-server"
        )

    @pytest.mark.parametrize("issuer", ["http://auth.example.test", "", "auth.example.test", 7])
    def test_rejects_an_unusable_issuer(self, issuer: Any) -> None:
        with pytest.raises(ValidationError, match="OAuth issuer"):
            _oauth().authorization_server_metadata(issuer)

    def test_sandbox_deployments_surface_the_404(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"status": 404, "message": "Página não encontrada."})

        client = AssinafyClient(base_url="https://sandbox.assinafy.com.br/v1")
        client._http._transport = httpx.MockTransport(handler)

        with pytest.raises(ApiError) as excinfo:
            client.oauth("client-id").protected_resource_metadata()

        assert excinfo.value.status_code == 404
        client.close()


class TestPkceHelpers:
    def test_code_verifier_and_state_are_url_safe_and_long_enough(self) -> None:
        for value in (OAuthResource.create_code_verifier(), OAuthResource.create_state()):
            assert len(value) == 43
            assert set(value) <= set(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            )

    def test_code_challenge_is_the_base64url_sha256_of_the_verifier(self) -> None:
        verifier = "b" * 50

        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        assert OAuthResource.code_challenge(verifier) == (
            base64.urlsafe_b64encode(digest).decode().rstrip("=")
        )

    def test_code_challenge_rejects_a_malformed_verifier(self) -> None:
        with pytest.raises(ValidationError, match="code verifier"):
            OAuthResource.code_challenge("short")
