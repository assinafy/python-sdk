from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from assinafy import ApiError, AssinafyClient, ValidationError


@pytest.fixture
def client() -> Iterator[AssinafyClient]:
    with AssinafyClient(api_key="workspace-key", account_id="account-id") as client:
        yield client


@pytest.mark.parametrize(
    ("verification", "notification"),
    [
        ("Email", "Email"),
        ("Whatsapp", "Whatsapp"),
        ("DigitalCertificate", "Email"),
        ("DigitalCertificate", "Whatsapp"),
        ("IdDocumentFaceMatchBasic", "Email"),
        ("IdDocumentFaceMatchBasic", "Whatsapp"),
    ],
)
@pytest.mark.parametrize("operation", ["assignment", "estimate", "template", "template_estimate"])
def test_signature_methods_reach_every_creation_and_pricing_route(
    client: AssinafyClient, verification: str, notification: str, operation: str
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": 200, "data": {}})

    client._http._transport = httpx.MockTransport(handler)
    signer = {
        "verification_method": verification,
        "notification_methods": [notification],
    }
    if operation == "assignment":
        signer["id"] = "signer-id"
        client.assignments.create("document-id", {"signers": [signer]})
        path = "/v1/documents/document-id/assignments"
    elif operation == "estimate":
        client.assignments.estimate_cost("document-id", {"signers": [signer]})
        path = "/v1/documents/document-id/assignments/estimate-cost"
    elif operation == "template":
        signer.update(role_id="role-id", id="signer-id")
        client.documents.create_from_template("template-id", [signer])
        path = "/v1/accounts/account-id/templates/template-id/documents"
    else:
        signer["role_id"] = "role-id"
        client.documents.estimate_cost_from_template("template-id", [signer])
        path = "/v1/accounts/account-id/templates/template-id/documents/estimate-cost"
    assert len(seen) == 1
    assert seen[0].url.path == path
    assert json.loads(seen[0].content)["signers"] == [signer]


@pytest.mark.parametrize("credentials", [{"api_key": "key"}, {"token": "token"}])
def test_signer_verification_wire_body_and_credential_scoping(credentials: dict[str, str]) -> None:
    seen: list[httpx.Request] = []
    state = {
        "can_start": False,
        "status": "InReview",
        "url": None,
        "expires_at": None,
        "completed_at": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": 200, "data": state})

    with AssinafyClient(**credentials) as client:
        client._http._transport = httpx.MockTransport(handler)
        assert client.signers.identity_verification("signer-code") == state
        assert client.signers.start_identity_verification("signer-code", consent=True) == state
    assert [request.method for request in seen] == ["GET", "POST"]
    for request in seen:
        assert request.url.path == "/v1/signers/identity-verification"
        assert dict(request.url.params) == {"signer-access-code": "signer-code"}
        assert "X-Api-Key" not in request.headers
        assert "Authorization" not in request.headers
    assert seen[0].content == b""
    assert json.loads(seen[1].content) == {"consent": True}


@pytest.mark.parametrize("consent", [False, None, 0, 1, "true"])
def test_consent_is_explicit_before_http(client: AssinafyClient, consent: Any) -> None:
    client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
    with pytest.raises(ValidationError, match="consent"):
        client.signers.start_identity_verification("code", consent=consent)


@pytest.mark.parametrize("code", [None, "", " "])
def test_identity_verification_requires_a_code(client: AssinafyClient, code: Any) -> None:
    client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
    with pytest.raises(ValidationError, match="Signer access code"):
        client.signers.identity_verification(code)
    with pytest.raises(ValidationError, match="Signer access code"):
        client.signers.start_identity_verification(code, consent=True)


@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
@pytest.mark.parametrize("note", [None, "", "x" * 2000], ids=["omitted", "empty", "maximum"])
def test_owner_review_and_evidence_wire_format(
    client: AssinafyClient, decision: str, note: str | None
) -> None:
    seen: list[httpx.Request] = []
    review = {"id": "review-id", "status": "InReview", "images": ["face"]}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/images/" in request.url.path:
            return httpx.Response(200, content=b"image-bytes")
        return httpx.Response(200, json={"status": 200, "data": review})

    client._http._transport = httpx.MockTransport(handler)
    args = ("document-id", "assignment-id", "signer-id")
    assert client.assignments.identity_verification(*args) == review
    assert client.assignments.download_identity_verification_image(*args, "face") == b"image-bytes"
    assert client.assignments.review_identity_verification(*args, decision, note=note) == review
    path = (
        "/v1/documents/document-id/assignments/assignment-id/signers/"
        "signer-id/identity-verification"
    )
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", path),
        ("GET", path + "/images/face"),
        ("POST", path + "/review"),
    ]
    assert all(r.headers["X-Api-Key"] == "workspace-key" for r in seen)
    body = {"decision": decision}
    if note is not None:
        body["note"] = note
    assert json.loads(seen[-1].content) == body


@pytest.mark.parametrize("image", ["document_front", "document_back", "document_pdf", "face"])
def test_all_evidence_names(client: AssinafyClient, image: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/" + image)
        return httpx.Response(200, content=b"evidence")

    client._http._transport = httpx.MockTransport(handler)
    assert (
        client.assignments.download_identity_verification_image("d", "a", "s", image) == b"evidence"
    )


def test_invalid_review_arguments_fail_before_http(client: AssinafyClient) -> None:
    client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
    for decision in (None, "Declined", "approved", []):
        with pytest.raises(ValidationError, match="decision"):
            client.assignments.review_identity_verification("d", "a", "s", decision)
    for note in (False, 12, "x" * 2001):
        with pytest.raises(ValidationError, match="note"):
            client.assignments.review_identity_verification("d", "a", "s", "Approved", note=note)
    for name in (None, "", "../face", "selfie", []):
        with pytest.raises(ValidationError, match="image"):
            client.assignments.download_identity_verification_image("d", "a", "s", name)
    for ids in (("../d", "a", "s"), ("d", "", "s"), ("d", "a", "s?code=x")):
        with pytest.raises(ValidationError):
            client.assignments.identity_verification(*ids)


def test_closed_review_404_is_preserved(client: AssinafyClient) -> None:
    client._http._transport = httpx.MockTransport(lambda request: httpx.Response(404))
    with pytest.raises(ApiError) as error:
        client.assignments.download_identity_verification_image("d", "a", "s", "face")
    assert error.value.status_code == 404


def test_delete_webhook_by_exact_url(client: AssinafyClient) -> None:
    url = "https://example.com/hook?channel=one&tenant=two"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/v1/accounts/other-account/webhooks/endpoints"
        assert request.url.params["url"] == url
        assert request.content == b""
        assert request.headers["X-Api-Key"] == "workspace-key"
        return httpx.Response(200, json={"status": 200, "data": []})

    client._http._transport = httpx.MockTransport(handler)
    assert client.webhooks.delete_endpoint_by_url(url, account_id="other-account") is None
    with pytest.raises(ValidationError):
        client.webhooks.delete_endpoint_by_url("invalid")


@pytest.mark.parametrize("estimate", [False, True])
def test_template_signer_optional_none_fields_are_omitted(
    client: AssinafyClient, estimate: bool
) -> None:
    signer = {"role_id": "role-id", "verification_method": None, "notification_methods": None}
    if not estimate:
        signer.update(id="signer-id", step=None)

    def handler(request: httpx.Request) -> httpx.Response:
        expected = {"role_id": "role-id"}
        if not estimate:
            expected["id"] = "signer-id"
        assert json.loads(request.content)["signers"] == [expected]
        return httpx.Response(200, json={"status": 200, "data": {}})

    client._http._transport = httpx.MockTransport(handler)
    if estimate:
        client.documents.estimate_cost_from_template("template-id", [signer])
    else:
        client.documents.create_from_template("template-id", [signer])
    assert signer["verification_method"] is None
