import json

import httpx
import pytest

from assinafy import __version__
from assinafy.client import AssinafyClient
from assinafy.errors import AssinafyError, ValidationError


class TestAssinafyClient:
    def test_allows_public_client_without_credentials(self) -> None:
        client = AssinafyClient(account_id="acc")
        assert "X-Api-Key" not in client.get_http_client().headers
        assert "Authorization" not in client.get_http_client().headers
        client.close()

    def test_accepts_api_key_credentials(self) -> None:
        client = AssinafyClient(api_key="k", account_id="acc")
        assert client.documents is not None
        assert client.signers is not None
        assert client.assignments is not None
        assert client.webhooks is not None
        assert client.authentication is not None
        assert client.fields is not None
        assert client.tags is not None
        assert client.signer_documents is not None
        assert client.webhook_verifier is not None
        client.close()

    def test_accepts_legacy_token_credentials(self) -> None:
        client = AssinafyClient(token="t", account_id="acc")
        assert client.documents is not None
        client.close()

    def test_api_key_takes_precedence_when_both_credentials_are_provided(self) -> None:
        client = AssinafyClient(api_key="key", token="token")
        assert client.get_http_client().headers["X-Api-Key"] == "key"
        assert "Authorization" not in client.get_http_client().headers
        client.close()

    def test_rejects_blank_credentials(self) -> None:
        with pytest.raises(ValidationError, match="api_key"):
            AssinafyClient(api_key="   ")
        with pytest.raises(ValidationError, match="account_id"):
            AssinafyClient(account_id="   ")

    def test_constructor_accepts_kwargs_dict(self) -> None:
        client = AssinafyClient(**{"api_key": "k", "account_id": "acc", "webhook_secret": "s"})
        assert client.documents is not None
        client.close()

    def test_sends_x_api_key_header_when_api_key_provided(self) -> None:
        client = AssinafyClient(api_key="my-key", account_id="acc")
        assert client.get_http_client().headers["X-Api-Key"] == "my-key"
        assert (
            client.get_http_client().headers["User-Agent"] == f"Assinafy-Python-SDK/v{__version__}"
        )
        client.close()

    @pytest.mark.parametrize(
        "base_url",
        ["https://api.assinafy.com.br/v1", "https://sandbox.assinafy.com.br/v1"],
    )
    def test_every_request_uses_versioned_sdk_user_agent(self, base_url: str) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"status": 200, "data": {}})

        client = AssinafyClient(api_key="secret", account_id="acc", base_url=base_url)
        client._http._transport = httpx.MockTransport(handler)
        client.get_http_client().headers["User-Agent"] = "overridden"
        client.get_http_client().get("accounts/acc", headers={"User-Agent": "also-overridden"})
        client.get_http_client().get("public/documents/doc")

        assert [request.headers["User-Agent"] for request in requests] == [
            f"Assinafy-Python-SDK/v{__version__}",
            f"Assinafy-Python-SDK/v{__version__}",
        ]
        client.close()

    def test_does_not_set_global_content_type_header(self) -> None:
        client = AssinafyClient(api_key="my-key", account_id="acc")
        assert "Content-Type" not in client.get_http_client().headers
        assert client.get_http_client().headers["Accept"] == "*/*"
        client.close()

    def test_sends_bearer_authorization_when_only_token_provided(self) -> None:
        client = AssinafyClient(token="legacy", account_id="acc")
        assert client.get_http_client().headers["Authorization"] == "Bearer legacy"
        client.close()

    @pytest.mark.parametrize(
        "credentials",
        [{"api_key": "secret"}, {"token": "secret"}],
    )
    def test_omits_client_credentials_from_public_and_signer_routes(
        self, credentials: dict[str, str]
    ) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"status": 200, "data": {}})

        client = AssinafyClient(account_id="acc", **credentials)
        client._http._transport = httpx.MockTransport(handler)
        http = client.get_http_client()
        public_routes = [
            ("POST", "login"),
            ("PUT", "authentication/request-password-reset"),
            ("PUT", "authentication/reset-password"),
            ("POST", "authentication/social-login"),
            ("GET", "documents/hash/verify"),
            ("GET", "public/documents/doc"),
            ("PUT", "public/documents/doc/send-token"),
            ("GET", "signers/self"),
            ("GET", "signers/signer/document"),
            ("GET", "sign"),
            ("POST", "documents/doc/assignments/assignment"),
            ("PUT", "documents/doc/assignments/assignment/reject"),
            ("PUT", "signers/documents/sign-multiple"),
            ("PUT", "signers/documents/decline-multiple"),
            ("POST", "verify"),
            ("PUT", "documents/doc/signers/confirm-data"),
            ("PUT", "signers/accept-terms"),
            ("POST", "signature"),
            ("GET", "signature/signature"),
            ("GET", "signers/signer/documents"),
            ("GET", "signers/signer/documents/search"),
            ("GET", "signers/signer/documents/doc/download/original"),
        ]
        for method, path in public_routes:
            http.request(method, path)
        http.get("https://other.example.test/accounts/acc")
        http.get("https://api.assinafy.com.br/outside-v1")
        http.post("documents/doc/assignments/estimate-cost")
        http.get("accounts/acc")

        credential_header = "X-Api-Key" if "api_key" in credentials else "Authorization"
        for request in requests[: len(public_routes)]:
            assert credential_header not in request.headers, request.url.path
            assert request.headers["User-Agent"] == f"Assinafy-Python-SDK/v{__version__}"
        assert credential_header not in requests[len(public_routes)].headers
        assert credential_header not in requests[len(public_routes) + 1].headers
        assert credential_header in requests[-2].headers
        assert credential_header in requests[-1].headers
        client.close()

    def test_strips_trailing_slash_from_base_url(self) -> None:
        client = AssinafyClient(
            api_key="k",
            account_id="acc",
            base_url="https://sandbox.assinafy.com.br/v1/",
        )
        base_url_str = str(client.get_http_client().base_url).rstrip("/")
        assert base_url_str == "https://sandbox.assinafy.com.br/v1"
        client.close()

    @pytest.mark.parametrize("base_url", ["", "   ", "ftp://example.com", "https:///v1"])
    def test_rejects_invalid_explicit_base_url(self, base_url: str) -> None:
        with pytest.raises(ValidationError, match="base_url"):
            AssinafyClient(base_url=base_url)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"api_key": ""}, "api_key"),
            ({"token": ""}, "token"),
            ({"account_id": ""}, "account_id"),
            ({"timeout": 0}, "timeout"),
            ({"timeout": True}, "timeout"),
        ],
    )
    def test_rejects_invalid_constructor_values(
        self, kwargs: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValidationError, match=message):
            AssinafyClient(**kwargs)  # type: ignore[arg-type]

    def test_context_manager_closes_client(self) -> None:
        with AssinafyClient(api_key="k", account_id="acc") as client:
            assert client.documents is not None

    def test_upload_and_request_signatures_requires_signers(self) -> None:
        client = AssinafyClient(api_key="k", account_id="acc")
        with pytest.raises(ValidationError, match="At least one signer"):
            client.upload_and_request_signatures(
                source={"file_path": "contract.pdf"},
                signers=[],
            )
        client.close()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"signers": [{"full_name": "Valid"}, {"full_name": "Bad", "email": "bad"}]},
            {"signers": [{"full_name": "No contact"}]},
            {"signers": [{"full_name": "Valid"}], "message": 1},
            {"signers": [{"full_name": "Valid"}], "expires_at": 1},
            {"signers": [{"full_name": "Valid"}], "copy_receivers": [1]},
            {"signers": [{"full_name": "Valid"}], "wait_timeout": 0},
            {"signers": [{"full_name": "Valid"}], "wait_for_ready": "yes"},
        ],
    )
    def test_upload_and_request_signatures_preflights_before_writes(
        self, kwargs: dict[str, object]
    ) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(500)

        client = AssinafyClient(api_key="k", account_id="acc")
        client._http._transport = httpx.MockTransport(handler)
        with pytest.raises(ValidationError):
            client.upload_and_request_signatures(
                source={"buffer": b"%PDF-1.4", "file_name": "contract.pdf"},
                **kwargs,  # type: ignore[arg-type]
            )
        assert calls == []
        client.close()

    def test_upload_and_request_signatures_rejects_malformed_resource_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/documents"):
                return httpx.Response(200, json={"status": 200, "data": {"id": "doc-1"}})
            assert request.method == "GET" and request.url.path.endswith("/documents/doc-1")
            return httpx.Response(
                200,
                json={"status": 200, "data": {"status": "metadata_ready"}},
            )

        client = AssinafyClient(api_key="k", account_id="acc")
        client._http._transport = httpx.MockTransport(handler)

        with pytest.raises(AssinafyError, match="missing a resource ID"):
            client.upload_and_request_signatures(
                source={"buffer": b"%PDF-1.4", "file_name": "contract.pdf"},
                signers=[{"full_name": "John Doe", "email": "john@example.com"}],
                wait_timeout=1.0,
                wait_poll_interval=0.01,
            )
        client.close()

    def test_upload_and_request_signatures_chains_all_three_calls(self) -> None:
        calls: list[str] = []
        assignment_body: dict[str, object] | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal assignment_body
            calls.append(f"{request.method} {request.url.path}")
            if request.method == "POST" and request.url.path.endswith("/documents"):
                return httpx.Response(200, json={"status": 200, "data": {"id": "doc-1"}})
            if request.method == "GET" and request.url.path.endswith("/documents/doc-1"):
                return httpx.Response(
                    200,
                    json={
                        "status": 200,
                        "data": {"id": "doc-1", "status": "metadata_ready"},
                    },
                )
            if request.method == "POST" and request.url.path.endswith("/signers"):
                return httpx.Response(200, json={"status": 200, "data": {"id": "signer-1"}})
            if request.method == "POST" and request.url.path.endswith("/assignments"):
                assignment_body = json.loads(request.content)
                return httpx.Response(200, json={"status": 200, "data": {"id": "assignment-1"}})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        client = AssinafyClient(api_key="k", account_id="acc")
        client._http._transport = httpx.MockTransport(handler)

        result = client.upload_and_request_signatures(
            source={"buffer": b"%PDF-1.4", "file_name": "contract.pdf"},
            signers=[{"full_name": "John Doe", "email": "john@example.com"}],
            wait_for_ready=True,
            wait_timeout=1.0,
            wait_poll_interval=0.01,
        )

        assert result["document"]["id"] == "doc-1"
        assert result["document"]["status"] == "metadata_ready"
        assert result["assignment"]["id"] == "assignment-1"
        assert result["signer_ids"] == ["signer-1"]
        assert assignment_body == {
            "method": "virtual",
            "signers": [
                {
                    "id": "signer-1",
                    "verification_method": "Email",
                    "notification_methods": ["Email"],
                }
            ],
        }
        assert any(c.endswith("/documents") for c in calls)
        assert any(c.endswith("/signers") for c in calls)
        assert any(c.endswith("/assignments") for c in calls)
        client.close()

    def test_upload_and_request_signatures_uses_whatsapp_for_phone_only_signer(self) -> None:
        assignment_body: dict[str, object] | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal assignment_body
            if request.url.path.endswith("/documents"):
                return httpx.Response(200, json={"status": 200, "data": {"id": "doc-1"}})
            if request.url.path.endswith("/signers"):
                return httpx.Response(200, json={"status": 200, "data": {"id": "signer-1"}})
            if request.url.path.endswith("/assignments"):
                assignment_body = json.loads(request.content)
                return httpx.Response(200, json={"status": 200, "data": {"id": "assignment-1"}})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        client = AssinafyClient(api_key="k", account_id="acc")
        client._http._transport = httpx.MockTransport(handler)
        client.upload_and_request_signatures(
            source={"buffer": b"%PDF-1.4", "file_name": "contract.pdf"},
            signers=[{"full_name": "John Doe", "whatsapp_phone_number": "+5511999999999"}],
            wait_for_ready=False,
        )

        assert assignment_body == {
            "method": "virtual",
            "signers": [
                {
                    "id": "signer-1",
                    "verification_method": "Whatsapp",
                    "notification_methods": ["Whatsapp"],
                }
            ],
        }
        client.close()
