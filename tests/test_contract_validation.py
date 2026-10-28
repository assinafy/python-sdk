from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from assinafy import AssinafyClient, NetworkError, ValidationError, WebhookVerifier
from assinafy.resources.assignments import build_assignment_payload
from assinafy.utils import to_sdk_error


@pytest.mark.parametrize(
    "methods",
    [
        {"notification_methods": []},
        {"notification_methods": ["Email", "Whatsapp"]},
        {"verification_method": "Email", "notification_methods": ["Whatsapp"]},
        {"verification_method": "Whatsapp", "notification_methods": ["Email"]},
    ],
)
@pytest.mark.parametrize("operation", ["assignment", "estimate", "template", "template_estimate"])
def test_invalid_notification_pairings_fail_before_http(
    methods: dict[str, Any], operation: str
) -> None:
    with AssinafyClient(account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(
            lambda request: pytest.fail("invalid payload must not leave the client")
        )
        with pytest.raises(ValidationError, match="notification_methods"):
            if operation == "assignment":
                client.assignments.create(
                    "document-id", {"signers": [{"id": "signer-id", **methods}]}
                )
            elif operation == "estimate":
                client.assignments.estimate_cost("document-id", {"signers": [methods]})
            elif operation == "template":
                client.documents.create_from_template(
                    "template-id", [{"role_id": "role-id", "id": "signer-id", **methods}]
                )
            else:
                client.documents.estimate_cost_from_template(
                    "template-id", [{"role_id": "role-id", **methods}]
                )


def test_multiple_certificate_pricing_descriptors_do_not_require_signing_steps() -> None:
    seen = []
    with AssinafyClient() as client:

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"status": 200, "data": {"total_credits": 4}})

        client._http._transport = httpx.MockTransport(handler)
        assert (
            client.assignments.estimate_cost(
                "document-id", {"signers": [{"verification_method": "DigitalCertificate"}] * 2}
            )["total_credits"]
            == 4
        )
        assert len(seen) == 1


def test_large_signing_step_is_rejected_without_allocating_to_the_step_number() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        build_assignment_payload({"signers": [{"id": "signer-id", "step": 10**12}]})


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("length", [2000, 2001])
def test_decline_reason_limit_and_wire_body(bulk: bool, length: int) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": 200, "data": []})

    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(handler)

        def decline() -> None:
            if bulk:
                client.signer_documents.decline_multiple(
                    ["document-id"], "x" * length, "access-code"
                )
            else:
                client.assignments.decline(
                    "document-id", "assignment-id", "x" * length, "access-code"
                )

        if length > 2000:
            with pytest.raises(ValidationError, match="2000"):
                decline()
            assert not seen
        else:
            decline()
            assert json.loads(seen[0].content)["decline_reason"] == "x" * length
            assert seen[0].url.params["signer-access-code"] == "access-code"


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_client_timeout_must_be_finite(value: float) -> None:
    with pytest.raises(ValidationError, match="timeout"):
        AssinafyClient(timeout=value)


@pytest.mark.parametrize("field", ["state", "iss"])
def test_non_ascii_callback_input_raises_sdk_validation_error(field: str) -> None:
    with AssinafyClient() as client:
        oauth = client.oauth("client-id")
        transaction = oauth.start_authorization("https://example.test/callback", ["documents:read"])
        query = {"state": transaction["state"], "iss": transaction["issuer"], "code": "code"}
        query[field] = "não"
        with pytest.raises(ValidationError):
            oauth.handle_callback(query, transaction)


@pytest.mark.parametrize(
    "option,value",
    [
        ("issuer", "https://auth.example.test/path"),
        ("issuer", "https://auth.example.test?query=1"),
        ("issuer", "https://[invalid"),
        ("issuer", "https://auth.example.test:invalid"),
        ("authorization_endpoint", "http://auth.example.test/authorize"),
        ("authorization_endpoint", "https://user:secret@auth.example.test/authorize"),
        ("authorization_endpoint", "https://auth.example.test/authorize#fragment"),
        ("redirect_uri", "https://user:secret@example.test/callback"),
    ],
)
def test_oauth_urls_reject_unsafe_or_malformed_values(option: str, value: str) -> None:
    args: dict[str, Any] = {
        "redirect_uri": "https://example.test/callback",
        "scopes": ["documents:read"],
    }
    args[option] = value
    with AssinafyClient() as client:
        with pytest.raises(ValidationError):
            client.oauth("client-id").start_authorization(**args)


@pytest.mark.parametrize(
    "scope", ["documents:read\topenid", "documents:read\n", 'bad"scope', "bad\\scope", "não"]
)
def test_oauth_scope_grammar(scope: str) -> None:
    with AssinafyClient() as client:
        with pytest.raises(ValidationError, match="scope"):
            client.oauth("client-id").start_authorization("https://example.test/callback", [scope])


def test_oauth_token_exchange_wire_contract() -> None:
    seen = []
    payload = {
        "access_token": "derived-token",
        "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "token_type": "Bearer",
        "expires_in": 300,
        "scope": "documents:read",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    with AssinafyClient(api_key="workspace-key") as client:
        client._http._transport = httpx.MockTransport(handler)
        assert (
            client.oauth("service-id", "service-secret").exchange_token(
                "subject-token", scopes=["documents:read"]
            )
            == payload
        )
    assert len(seen) == 1
    request = seen[0]
    assert request.url.path == "/v1/oauth/token"
    assert "X-Api-Key" not in request.headers and "Authorization" not in request.headers
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "subject_token": ["subject-token"],
        "subject_token_type": ["urn:ietf:params:oauth:token-type:access_token"],
        "resource": ["https://api.assinafy.com.br"],
        "scope": ["documents:read"],
        "client_id": ["service-id"],
        "client_secret": ["service-secret"],
    }


def test_token_exchange_requires_confidential_secret_and_never_retries() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout("subject-token service-secret", request=request)

    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(handler)
        with pytest.raises(ValidationError, match="confidential"):
            client.oauth("public-id").exchange_token("subject-token")
        with pytest.raises(NetworkError) as error:
            client.oauth("service-id", "service-secret").exchange_token("subject-token")
        assert "subject-token" not in str(error.value)
        assert "service-secret" not in str(error.value)
        assert error.value.__suppress_context__
        assert len(seen) == 1


def test_transport_error_messages_do_not_copy_secret_urls() -> None:
    error = httpx.ConnectError("https://example.test/sign?signer-access-code=secret")
    assert "secret" not in str(to_sdk_error(error, "Request failed"))
    assert not WebhookVerifier("shared-secret").verify(b"{}", "não")
    assert not WebhookVerifier("shared-secret").verify(b"{}", "\ud800")


@pytest.mark.parametrize(
    "key,value",
    [("left", -1), ("width", 0), ("height", float("nan")), ("fontSize", True), ("fontSize", None)],
)
def test_collect_geometry_is_validated_before_request(key: str, value: Any) -> None:
    settings = {"left": 0, "top": 0, "width": 100, "height": 40, "fontSize": 12}
    settings[key] = value
    with pytest.raises(ValidationError, match="display_settings"):
        build_assignment_payload(
            {
                "method": "collect",
                "signers": ["signer-id"],
                "entries": [
                    {
                        "page_id": "page-id",
                        "fields": [
                            {
                                "signer_id": "signer-id",
                                "field_id": "field-id",
                                "display_settings": settings,
                            }
                        ],
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "entry",
    [
        {"page_id": "page-id", "fields": [], "unexpected": True},
        {"fields": []},
        {"page_id": "page-id", "fields": {}},
        {"page_id": "page-id", "fields": [None]},
        {"page_id": "page-id", "fields": [{"field_id": "field-id"}]},
        {"page_id": "page-id", "fields": [{"signer_id": "signer-id", "field_id": "field-id"}]},
    ],
)
def test_collect_entry_structure_fails_before_transport(entry: dict[str, Any]) -> None:
    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(
            lambda request: pytest.fail("invalid collect entry must not leave the client")
        )
        with pytest.raises(ValidationError):
            client.assignments.create(
                "document-id", {"method": "collect", "signers": ["signer-id"], "entries": [entry]}
            )


def test_collect_request_preserves_valid_geometry_and_optional_presentation() -> None:
    seen = []
    settings = {
        "left": 0,
        "top": 1.5,
        "width": 100,
        "height": 40,
        "fontSize": 12,
        "fontFamily": "Arial",
        "backgroundColor": "#D5EBFF",
    }
    payload = {
        "method": "collect",
        "signers": [{"id": "signer-id"}],
        "entries": [
            {
                "page_id": "page-id",
                "fields": [
                    {"signer_id": "signer-id", "field_id": "field-id", "display_settings": settings}
                ],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": 200, "data": {"id": "assignment-id"}})

    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(handler)
        assert client.assignments.create("document-id", payload)["id"] == "assignment-id"
    assert json.loads(seen[0].content) == payload


@pytest.mark.parametrize("field", ["fontFamily", "backgroundColor"])
def test_collect_presentation_requires_strings(field: str) -> None:
    settings = {"left": 0, "top": 0, "width": 100, "height": 40, "fontSize": 12, field: True}
    with pytest.raises(ValidationError, match=field):
        build_assignment_payload(
            {
                "method": "collect",
                "signers": ["signer-id"],
                "entries": [
                    {
                        "page_id": "page-id",
                        "fields": [
                            {
                                "signer_id": "signer-id",
                                "field_id": "field-id",
                                "display_settings": settings,
                            }
                        ],
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    ("signer_ids", "field_signers"),
    [
        (["signer-1", "signer-1"], ["signer-1"]),
        (["signer-1", "signer-2"], ["signer-1"]),
        (["signer-1"], ["unlisted-signer"]),
        (["signer-1"], []),
    ],
)
def test_collect_signers_must_be_unique_and_own_the_placed_fields(
    signer_ids: list[str], field_signers: list[str]
) -> None:
    entries = [
        {
            "page_id": "page-id",
            "fields": [
                {
                    "signer_id": signer_id,
                    "field_id": "field-id",
                    "display_settings": {
                        "left": 0,
                        "top": 0,
                        "width": 100,
                        "height": 40,
                        "fontSize": 12,
                    },
                }
                for signer_id in field_signers
            ],
        }
    ]
    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(lambda request: pytest.fail("unexpected I/O"))
        with pytest.raises(ValidationError, match="[Cc]ollect"):
            client.assignments.create(
                "document-id", {"method": "collect", "signers": signer_ids, "entries": entries}
            )


def test_collect_allows_multiple_fields_owned_by_one_signer() -> None:
    entries = [
        {
            "page_id": "page-id",
            "fields": [
                {
                    "signer_id": "signer-id",
                    "field_id": field_id,
                    "display_settings": {
                        "left": 0,
                        "top": 0,
                        "width": 100,
                        "height": 40,
                        "fontSize": 12,
                    },
                }
                for field_id in ("first-field", "second-field")
            ],
        }
    ]
    body = build_assignment_payload(
        {
            "method": "collect",
            "signers": ["signer-id"],
            "entries": entries,
        }
    )
    assert body["entries"] == entries


def test_collect_estimate_does_not_apply_field_ownership_rules() -> None:
    payload = {"method": "collect", "signers": [{}, {}], "entries": [{"count": 3}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == payload
        return httpx.Response(200, json={"status": 200, "data": {"total_credits": 0}})

    with AssinafyClient() as client:
        client._http._transport = httpx.MockTransport(handler)
        assert client.assignments.estimate_cost("document-id", payload) == {"total_credits": 0}


@pytest.mark.parametrize(
    "expiration", ["2030-12-31", "2030-12-31T20:00:00", "2030-12-31T20:00:00-03:00"]
)
@pytest.mark.parametrize("operation", ["assignment", "reset", "template"])
def test_documented_expiration_forms_are_sent_unchanged(expiration: str, operation: str) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert json.loads(request.content)["expires_at"] == expiration
        return httpx.Response(200, json={"status": 200, "data": {}})

    with AssinafyClient(account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(handler)
        if operation == "assignment":
            client.assignments.create(
                "document-id", {"signers": ["signer-id"], "expires_at": expiration}
            )
        elif operation == "reset":
            client.assignments.reset_expiration("document-id", "assignment-id", expiration)
        else:
            client.documents.create_from_template(
                "template-id",
                [{"role_id": "role-id", "id": "signer-id"}],
                {"expires_at": expiration},
            )
    assert len(seen) == 1
