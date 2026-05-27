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
        client = AssinafyClient(
            **{"api_key": "k", "account_id": "acc", "webhook_secret": "s"}
        )
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
