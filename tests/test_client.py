import httpx
import pytest

from assinafy.client import AssinafyClient
from assinafy.errors import ValidationError


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

    def test_constructor_accepts_kwargs_dict(self) -> None:
        client = AssinafyClient(**{"api_key": "k", "account_id": "acc", "webhook_secret": "s"})
        assert client.documents is not None
        client.close()

    def test_sends_x_api_key_header_when_api_key_provided(self) -> None:
        client = AssinafyClient(api_key="my-key", account_id="acc")
        assert client.get_http_client().headers["X-Api-Key"] == "my-key"
        client.close()

    def test_does_not_set_global_content_type_header(self) -> None:
        client = AssinafyClient(api_key="my-key", account_id="acc")
        assert "Content-Type" not in client.get_http_client().headers
        client.close()

    def test_sends_bearer_authorization_when_only_token_provided(self) -> None:
        client = AssinafyClient(token="legacy", account_id="acc")
        assert client.get_http_client().headers["Authorization"] == "Bearer legacy"
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

    def test_upload_and_request_signatures_chains_all_three_calls(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
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
        assert result["assignment"]["id"] == "assignment-1"
        assert result["signer_ids"] == ["signer-1"]
        assert any(c.endswith("/documents") for c in calls)
        assert any(c.endswith("/signers") for c in calls)
        assert any(c.endswith("/assignments") for c in calls)
        client.close()
