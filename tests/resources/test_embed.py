from __future__ import annotations

import json

import httpx
import pytest

from assinafy import AssinafyClient, NetworkError, ValidationError


@pytest.mark.parametrize("parent_origin", [None, "https://app.example.com"])
def test_exchange_consumes_token_without_workspace_credentials(parent_origin: str | None) -> None:
    seen = []
    payload = {
        "signer_access_code": "synthetic-code",
        "signer_id": "signer-id",
        "document_id": "document-id",
        "verification_method": "Email",
        "embed_origins": ["https://app.example.com"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": 200, "data": payload})

    with AssinafyClient(api_key="workspace-key") as client:
        client._http._transport = httpx.MockTransport(handler)
        assert client.embed.exchange("t" * 64, parent_origin) == payload
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == f"/v1/embed/sessions/{'t' * 64}/exchange"
    assert "X-Api-Key" not in request.headers and "Authorization" not in request.headers
    assert json.loads(request.content) == (
        {} if parent_origin is None else {"parent_origin": parent_origin}
    )


@pytest.mark.parametrize("token", ["", " ", "../token", "token?query=value", "token#fragment"])
def test_exchange_rejects_unsafe_token_before_io(token: str) -> None:
    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
        with pytest.raises(ValidationError):
            client.embed.exchange(token)


def test_exchange_never_retries_or_exposes_token_on_ambiguous_failure() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout(str(request.url), request=request)

    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(handler)
        with pytest.raises(NetworkError) as error:
            client.embed.exchange("synthetic-session-token")
    assert len(seen) == 1
    assert "synthetic-session-token" not in str(error.value)
    assert error.value.__suppress_context__
