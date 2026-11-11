from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from assinafy import ApiError, AssinafyClient, AssinafyError, ValidationError


@pytest.fixture
def client() -> Iterator[AssinafyClient]:
    with AssinafyClient(api_key="workspace-key", account_id="account-id") as client:
        yield client


@pytest.mark.parametrize("operation", ["confirm_data", "verify_code", "verify_email"])
@pytest.mark.parametrize("data", [[], {}, {"id": "legacy-signer"}])
def test_signer_success_shapes(client: AssinafyClient, operation: str, data: Any) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert "X-Api-Key" not in request.headers
        assert request.url.params["signer-access-code"] == "code"
        return httpx.Response(200, json={"status": 200, "data": data})

    client._http._transport = httpx.MockTransport(handler)
    if operation == "confirm_data":
        result = client.signers.confirm_data("doc", "code", {"has_accepted_terms": True})
    else:
        result = getattr(client.signers, operation)("code", "123456")
    assert result == ({} if data == [] else data)
    assert len(seen) == 1


@pytest.mark.parametrize("data", [[{"id": "bad"}], None, False, "unexpected"])
def test_empty_success_does_not_accept_other_payloads(client: AssinafyClient, data: Any) -> None:
    client._http._transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": 200, "data": data})
    )
    with pytest.raises(AssinafyError):
        client.signers.verify_code("code", "123456")


@pytest.mark.parametrize("operation", ["assignment", "template"])
@pytest.mark.parametrize("ceiling", [0, 1.5, "1.50", None])
@pytest.mark.parametrize("embedded", [True, False, None])
def test_create_preserves_embedded_and_credit_ceiling(
    client: AssinafyClient, operation: str, ceiling: Any, embedded: Any
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("max_total_credits") == ceiling
        assert body["signers"][0].get("embedded") == embedded
        assert ("embedded" in body["signers"][0]) == (embedded is not None)
        assert ("max_total_credits" in body) == (ceiling is not None)
        assert request.headers["X-Api-Key"] == "workspace-key"
        return httpx.Response(200, json={"status": 200, "data": {}})

    client._http._transport = httpx.MockTransport(handler)
    signer = {"id": "signer", "embedded": embedded}
    if operation == "assignment":
        client.assignments.create("doc", {"signers": [signer], "max_total_credits": ceiling})
    else:
        signer["role_id"] = "role"
        client.documents.create_from_template("template", [signer], {"max_total_credits": ceiling})


@pytest.mark.parametrize("operation", ["assignment", "template"])
@pytest.mark.parametrize("bad", [True, -1, "-1", "no", "NaN", float("inf"), [], {}])
def test_credit_ceiling_rejected_before_io(
    client: AssinafyClient, operation: str, bad: Any
) -> None:
    client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
    with pytest.raises(ValidationError, match="max_total_credits"):
        if operation == "assignment":
            client.assignments.create("doc", {"signers": ["signer"], "max_total_credits": bad})
        else:
            client.documents.create_from_template(
                "template", [{"id": "signer", "role_id": "role"}], {"max_total_credits": bad}
            )


@pytest.mark.parametrize("operation", ["assignment", "template"])
@pytest.mark.parametrize(
    "signer",
    [
        {"embedded": 1},
        {"embedded": "true"},
        {"embedded": True, "verification_method": "DigitalCertificate"},
        {"embedded": True, "verification_method": "IdDocumentFaceMatchBasic"},
    ],
)
def test_embedded_validation_before_io(
    client: AssinafyClient, operation: str, signer: dict[str, Any]
) -> None:
    client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
    with pytest.raises(ValidationError, match="embedded"):
        if operation == "assignment":
            client.assignments.create("doc", {"signers": [{"id": "signer", **signer}]})
        else:
            client.documents.create_from_template(
                "template", [{"id": "signer", "role_id": "role", **signer}]
            )


def test_create_embed_session(client: AssinafyClient) -> None:
    result = {"url": "https://app.example/embed/test-token", "expires_at": "2030-01-01T12:05:00Z"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/documents/d/assignments/a/signers/s/embed-sessions"
        assert request.content == b""
        assert request.headers["X-Api-Key"] == "workspace-key"
        return httpx.Response(200, json={"status": 200, "data": result})

    client._http._transport = httpx.MockTransport(handler)
    assert client.assignments.create_embed_session("d", "a", "s") == result
    with pytest.raises(ValidationError):
        client.assignments.create_embed_session("d", "a", "../s")


@pytest.mark.parametrize("operation", ["theme", "logo", "request_certified_copy"])
def test_signing_brand_and_copy_routes(client: AssinafyClient, operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = "certified-copy" if operation == "request_certified_copy" else operation
        assert request.url.path == f"/v1/sign/{path}"
        assert request.method == ("POST" if operation == "request_certified_copy" else "GET")
        assert dict(request.url.params) == {"signer-access-code": "code"}
        assert request.content == b""
        assert "X-Api-Key" not in request.headers
        if operation == "logo":
            return httpx.Response(200, content=b"image")
        return httpx.Response(200, json={"status": 200, "data": {"available": True}})

    client._http._transport = httpx.MockTransport(handler)
    result = getattr(client.signer_documents, operation)("code")
    assert result == (b"image" if operation == "logo" else {"available": True})
    with pytest.raises(ValidationError):
        getattr(client.signer_documents, operation)(" ")


def test_request_copy_for_envelope_document(client: AssinafyClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"document_id": "other-doc"}
        return httpx.Response(200, json={"status": 200, "data": {"sent_to": "s***@example.com"}})

    client._http._transport = httpx.MockTransport(handler)
    client.signer_documents.request_certified_copy("code", document_id="other-doc")
    with pytest.raises(ValidationError):
        client.signer_documents.request_certified_copy("code", document_id="")


@pytest.mark.parametrize("operation", ["download", "pades", "resend"])
def test_certified_link_routes(client: AssinafyClient, operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        suffix = "" if operation == "download" else "/" + operation
        assert request.url.path == "/v1/signers/downloads/link-token" + suffix
        assert request.method == ("POST" if operation == "resend" else "GET")
        assert request.content == b""
        assert not request.url.params
        assert "X-Api-Key" not in request.headers
        assert "Authorization" not in request.headers
        if operation == "resend":
            return httpx.Response(200, json={"status": 200, "data": {"resends_left": 0}})
        return httpx.Response(200, content=b"pdf")

    client._http._transport = httpx.MockTransport(handler)
    if operation == "resend":
        assert client.signer_documents.resend_certified_copy("link-token") == {"resends_left": 0}
    else:
        assert (
            client.signer_documents.download_certified_copy(
                "link-token", pades=operation == "pades"
            )
            == b"pdf"
        )


@pytest.mark.parametrize("status", [302, 403, 404, 409, 410, 429, 503])
def test_copy_errors_remain_errors_without_following_redirects(
    client: AssinafyClient, status: int
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://example.com/expired"})

    client._http._transport = httpx.MockTransport(handler)
    with pytest.raises(ApiError) as error:
        client.signer_documents.download_certified_copy("private-token")
    assert error.value.status_code == status
    assert "private-token" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("token", [None, "", " ", "../token", "token?key=value"])
def test_copy_token_validation(client: AssinafyClient, token: Any) -> None:
    client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
    with pytest.raises(ValidationError):
        client.signer_documents.download_certified_copy(token)
    with pytest.raises(ValidationError):
        client.signer_documents.resend_certified_copy(token)
    with pytest.raises(ValidationError):
        client.signer_documents.download_certified_copy("token", pades=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("operation", ["get", "current", "sign", "rename"])
def test_document_expansions(client: AssinafyClient, operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["expand"] == (
            "envelope,envelope_id"
            if operation == "get"
            else "assignment,pages"
            if operation == "rename"
            else "envelope"
        )
        if operation in {"current", "sign"}:
            assert request.url.params["signer-access-code"] == "code"
            assert "X-Api-Key" not in request.headers
        else:
            assert request.headers["X-Api-Key"] == "workspace-key"
        if operation == "sign":
            assert request.url.params["document_id"] == "other-doc"
        return httpx.Response(200, json={"status": 200, "data": {}})

    client._http._transport = httpx.MockTransport(handler)
    if operation == "get":
        client.documents.get("doc", expand=["envelope", "envelope_id"])
    elif operation == "current":
        client.signer_documents.current("signer", "code", expand="envelope")
    elif operation == "sign":
        client.assignments.get_for_signer("code", expand="envelope", document_id="other-doc")
    else:
        client.documents.rename("doc", "Name.pdf", expand=["assignment", "pages"])


@pytest.mark.parametrize("operation", ["get", "download", "thumbnail", "download_page"])
def test_document_signer_access(client: AssinafyClient, operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["signer-access-code"] == "code"
        assert "X-Api-Key" not in request.headers
        if operation == "get":
            return httpx.Response(200, json={"status": 200, "data": {}})
        return httpx.Response(200, content=b"binary")

    client._http._transport = httpx.MockTransport(handler)
    args = (
        ("doc", "page")
        if operation == "download_page"
        else ("doc", "original")
        if operation == "download"
        else ("doc",)
    )
    getattr(client.documents, operation)(*args, signer_access_code="code")
    with pytest.raises(ValidationError):
        getattr(client.documents, operation)(*args, signer_access_code=" ")


@pytest.mark.parametrize("operation", ["thumbnail", "download_page"])
def test_signed_render_query(client: AssinafyClient, operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"artifact": "certificated"}
        assert request.headers["X-Api-Key"] == "workspace-key"
        return httpx.Response(200, content=b"signed-render")

    client._http._transport = httpx.MockTransport(handler)
    args = ("doc", "page") if operation == "download_page" else ("doc",)
    assert getattr(client.documents, operation)(*args, artifact="certificated") == b"signed-render"
    with pytest.raises(ValidationError):
        getattr(client.documents, operation)(*args, artifact=1)


@pytest.mark.parametrize("expiration", [0, 1, 1900000000.5, "1900000000", ""])
@pytest.mark.parametrize("operation", ["assignment", "template", "reset"])
def test_expiration_numeric_and_empty_values_are_preserved(
    client: AssinafyClient, expiration: Any, operation: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["expires_at"] == expiration
        return httpx.Response(200, json={"status": 200, "data": {}})

    client._http._transport = httpx.MockTransport(handler)
    if operation == "assignment":
        client.assignments.create("doc", {"signers": ["signer"], "expires_at": expiration})
    elif operation == "template":
        client.documents.create_from_template(
            "template", [{"id": "signer", "role_id": "role"}], {"expires_at": expiration}
        )
    else:
        client.assignments.reset_expiration("doc", "assignment", expiration)


@pytest.mark.parametrize("key", [None, "", "Case-Sensitive-Key"])
def test_template_idempotency_header_preserves_body_and_legacy_arguments(
    client: AssinafyClient, key: str | None
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/v1/accounts/other/templates/template/documents"
        assert json.loads(request.content) == {
            "name": "Example.pdf",
            "signers": [{"role_id": "role", "id": "signer"}],
        }
        assert request.headers.get("Idempotency-Key") == key
        assert ("Idempotency-Key" in request.headers) == (key is not None)
        return httpx.Response(200, json={"status": 200, "data": {"id": "created"}})

    client._http._transport = httpx.MockTransport(handler)
    assert client.documents.create_from_template(
        "template",
        [{"role_id": "role", "id": "signer"}],
        {"name": "Example.pdf"},
        "other",
        idempotency_key=key,
    ) == {"id": "created"}
    assert len(seen) == 1


@pytest.mark.parametrize("key", ["key\r\nX-Other: injected", "\x00", "\x7f", "não-ascii", 12])
def test_template_idempotency_rejects_invalid_header_before_io(
    client: AssinafyClient, key: Any
) -> None:
    client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
    with pytest.raises(ValidationError, match="idempotency_key"):
        client.documents.create_from_template(
            "template", [{"role_id": "role", "id": "signer"}], idempotency_key=key
        )


def test_template_idempotency_conflict_is_not_retried(client: AssinafyClient) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(409, json={"status": 409, "code": "IdempotencyKeyInUse"})

    client._http._transport = httpx.MockTransport(handler)
    with pytest.raises(ApiError) as error:
        client.documents.create_from_template(
            "template", [{"role_id": "role", "id": "signer"}], idempotency_key="example-request"
        )
    assert error.value.status_code == 409
    assert error.value.response_data["code"] == "IdempotencyKeyInUse"
    assert len(seen) == 1


@pytest.mark.parametrize("workspace", [False, True])
def test_signer_document_search_can_filter_envelope(
    client: AssinafyClient, workspace: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        expected = {"search": "agreement", "envelope_id": "envelope"}
        if not workspace:
            expected["signer-access-code"] = "code"
        assert dict(request.url.params) == expected
        assert ("X-Api-Key" in request.headers) == workspace
        return httpx.Response(200, json={"status": 200, "data": []})

    client._http._transport = httpx.MockTransport(handler)
    if workspace:
        assert client.signer_documents.search_as_workspace(
            "signer", "agreement", envelope_id="envelope"
        ) == {"data": []}
        with pytest.raises(ValidationError):
            client.signer_documents.search_as_workspace("signer", envelope_id="")
    else:
        assert client.signer_documents.search(
            "signer", "code", "agreement", envelope_id="envelope"
        ) == {"data": []}
        with pytest.raises(ValidationError):
            client.signer_documents.search("signer", "code", envelope_id="")
