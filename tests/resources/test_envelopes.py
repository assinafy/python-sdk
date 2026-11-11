from __future__ import annotations

from copy import deepcopy
from typing import Any

import httpx
import pytest

from assinafy import ApiError, AssinafyClient, ValidationError
from assinafy.resources.envelopes import EnvelopeResource


def payload() -> dict[str, Any]:
    return {
        "name": "Example agreement",
        "signers": [{"id": "signer", "verification_method": "Email"}],
        "documents": [{"id": "doc", "signer_ids": ["signer"]}],
    }


def client_for(data: Any, requests: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": 200, "data": data})

    return httpx.Client(
        base_url="https://api.example.test/v1/", transport=httpx.MockTransport(handler)
    )


def test_create_preserves_body_and_idempotency_header() -> None:
    import json

    requests: list[httpx.Request] = []
    body = {**payload(), "max_total_credits": "1.25"}
    original = deepcopy(body)
    with client_for({"id": "env"}, requests) as http:
        resource = EnvelopeResource(http, "account")
        assert resource.create(body, idempotency_key="new-envelope") == {"id": "env"}
    assert body == original
    assert str(requests[0].url) == "https://api.example.test/v1/accounts/account/envelopes"
    assert requests[0].headers["Idempotency-Key"] == "new-envelope"
    assert json.loads(requests[0].content) == body


def test_estimate_ignores_ceiling_and_sends_no_idempotency_header() -> None:
    import json

    requests: list[httpx.Request] = []
    with client_for({"has_sufficient_resources": True}, requests) as http:
        resource = EnvelopeResource(http, "account")
        result = resource.estimate_cost({**payload(), "max_total_credits": "ignored"})
    assert result == {"has_sufficient_resources": True}
    assert requests[0].url.path.endswith("/envelopes/estimate-cost")
    assert json.loads(requests[0].content) == payload()
    assert "Idempotency-Key" not in requests[0].headers


@pytest.mark.parametrize(
    ("method", "args", "verb", "path", "data"),
    [
        ("get", ("env",), "GET", "/env", {"id": "env"}),
        (
            "update",
            ("env", {"message": None, "document_ids": ["doc"]}),
            "PATCH",
            "/env",
            {"id": "env"},
        ),
        ("delete", ("env",), "DELETE", "/env", []),
        (
            "cancel",
            ("env",),
            "PUT",
            "/env/cancel",
            [{"id": "doc", "status": "rejected_by_user", "cancelled": True}],
        ),
        (
            "resend_notification",
            ("env", "signer"),
            "PUT",
            "/env/signers/signer/resend",
            {"is_sent": True},
        ),
        (
            "add_document",
            ("env", {"id": "doc", "signer_ids": ["signer"], "max_total_credits": 0}),
            "POST",
            "/env/documents",
            {"id": "env"},
        ),
        ("remove_document", ("env", "doc"), "DELETE", "/env/documents/doc", {"id": "env"}),
    ],
)
def test_lifecycle_wire_shapes(
    method: str, args: tuple[Any, ...], verb: str, path: str, data: Any
) -> None:
    import json

    requests: list[httpx.Request] = []
    with client_for(data, requests) as http:
        resource = EnvelopeResource(http, "account")
        result = getattr(resource, method)(*args)
    assert result == (None if method == "delete" else data)
    assert requests[0].method == verb
    assert requests[0].url.path == "/v1/accounts/account/envelopes" + path
    if method == "update":
        assert json.loads(requests[0].content) == args[1]


def test_list_and_activities_use_pagination_and_query_aliases() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": 200, "data": [{"id": "item"}]},
            headers={"X-Pagination-Total-Count": "3"},
        )

    with httpx.Client(
        base_url="https://api.example.test/v1/", transport=httpx.MockTransport(handler)
    ) as http:
        resource = EnvelopeResource(http, "account")
        assert resource.list({"per_page": 2, "status": "open", "search": "Example"}) == {
            "data": [{"id": "item"}],
            "meta": {"total": 3},
        }
        assert resource.activities("env", {"per_page": 2, "sort": "id"})["meta"] == {"total": 3}
    assert requests[0].url.params["per-page"] == "2"
    assert requests[1].url.path.endswith("/env/activities")
    assert requests[1].url.params["sort"] == "id"


def test_download_returns_zip_bytes_and_account_override() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"PK\x03\x04")

    with httpx.Client(
        base_url="https://api.example.test/v1/", transport=httpx.MockTransport(handler)
    ) as http:
        assert EnvelopeResource(http, "default").download("env", "pades", "other") == b"PK\x03\x04"
    assert requests[0].url.path == "/v1/accounts/other/envelopes/env/download/pades"


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"name": "<script>"},
        {"name": "a" * 256},
        {"message": 1},
        {"signers": []},
        {"signers": [{"id": "signer"}] * 21},
        {"documents": []},
        {"signers": [{"id": "signer", "step": 1}]},
        {
            "signers": [
                {"id": "signer", "embedded": True, "verification_method": "DigitalCertificate"}
            ]
        },
        {"signers": [{"id": "signer"}, {"id": "signer"}]},
        {"signers": [{"id": "signer"}, {"id": "unused"}]},
        {"documents": [{"id": "doc", "signer_ids": ["unknown"]}]},
        {"documents": [{"id": "doc", "signer_ids": ["signer", "signer"]}]},
        {"documents": [{"id": "doc", "signer_ids": ["signer"]}] * 2},
        {"documents": [{"id": "doc", "signer_ids": ["signer"], "max_total_credits": 0}]},
        {
            "documents": [
                {"id": "doc", "signer_ids": ["signer"], "method": "collect", "entries": []}
            ]
        },
        {"max_total_credits": float("nan")},
        {"max_total_credits": -1},
        {"extra": True},
    ],
)
def test_invalid_create_payload_fails_before_io(change: dict[str, Any]) -> None:
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        with pytest.raises(ValidationError):
            EnvelopeResource(http, "account").create({**payload(), **change})
    assert requests == []


def test_certificate_signer_must_be_alone_on_each_document() -> None:
    requests: list[httpx.Request] = []
    body = payload()
    body["signers"] = [
        {"id": "signer", "verification_method": "DigitalCertificate"},
        {"id": "other"},
    ]
    body["documents"][0]["signer_ids"] = ["signer", "other"]
    with client_for({}, requests) as http:
        resource = EnvelopeResource(http, "account")
        with pytest.raises(ValidationError, match="alone"):
            resource.create(body)
        body["documents"] = [
            {"id": "doc", "signer_ids": ["signer"]},
            {"id": "doc2", "signer_ids": ["other"]},
        ]
        resource.create(body)
    assert len(requests) == 1


def test_collect_geometry_and_owners_are_checked() -> None:
    requests: list[httpx.Request] = []
    body = payload()
    body["documents"][0].update(
        {
            "method": "collect",
            "entries": [
                {
                    "page_id": "page",
                    "fields": [
                        {
                            "signer_id": "signer",
                            "field_id": "field",
                            "display_settings": {
                                "left": 0,
                                "top": 0,
                                "width": 20,
                                "height": 10,
                                "fontSize": 12,
                            },
                        }
                    ],
                }
            ],
        }
    )
    with client_for({}, requests) as http:
        resource = EnvelopeResource(http, "account")
        resource.create(body)
        body["documents"][0]["entries"][0]["fields"][0]["signer_id"] = "other"
        with pytest.raises(ValidationError, match="field"):
            resource.create(body)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "args",
    [
        ("get", ("../other",)),
        ("download", ("env", "bad")),
        ("list", ({"status": []},)),
        ("list", ({"search": 1},)),
        ("update", ("env", {"document_ids": ["doc", "doc"]})),
        ("add_document", ("env", {"id": "doc", "signer_ids": []})),
        ("remove_document", ("env", "a/b")),
    ],
)
def test_invalid_arguments_fail_before_io(args: tuple[str, tuple[Any, ...]]) -> None:
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        with pytest.raises(ValidationError):
            getattr(EnvelopeResource(http, "account"), args[0])(*args[1])
    assert requests == []


@pytest.mark.parametrize("envelope_id", [None, "", " ", "../other"])
@pytest.mark.parametrize(
    ("operation", "args"),
    [
        ("get", ()),
        ("update", ({"message": None},)),
        ("delete", ()),
        ("cancel", ()),
        ("resend_notification", ("signer",)),
        ("add_document", ({"id": "doc", "signer_ids": ["signer"]},)),
        ("remove_document", ("doc",)),
        ("activities", ()),
        ("download", ()),
    ],
)
def test_required_envelope_id_is_validated_before_io(
    envelope_id: Any, operation: str, args: tuple[Any, ...]
) -> None:
    with httpx.Client(
        base_url="https://api.example.test/v1/",
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected I/O")),
    ) as http:
        with pytest.raises(ValidationError, match="envelope_id"):
            getattr(EnvelopeResource(http, "account"), operation)(envelope_id, *args)


def test_server_refusal_retains_code_without_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            409, json={"status": 409, "code": "CreditCeilingExceeded", "total_credits": 2}
        )

    with httpx.Client(
        base_url="https://api.example.test/v1/", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ApiError) as error:
            EnvelopeResource(http, "account").create({**payload(), "max_total_credits": 1})
    assert len(calls) == 1
    assert error.value.response_data["code"] == "CreditCeilingExceeded"


def test_envelopes_share_client_transport() -> None:
    with AssinafyClient(account_id="account") as client:
        assert isinstance(client.envelopes, EnvelopeResource)
        assert client.envelopes._http is client._http


@pytest.mark.parametrize(("count", "allowed"), [(100, True), (101, False)])
def test_envelope_copy_receiver_limit(count: int, allowed: bool) -> None:
    body = payload()
    body["documents"][0]["copy_receiver_ids"] = [f"copy-{index}" for index in range(count)]
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        resource = EnvelopeResource(http, "account")
        if allowed:
            resource.create(body)
        else:
            with pytest.raises(ValidationError, match="100 copy receivers"):
                resource.create(body)
    assert len(requests) == int(allowed)


@pytest.mark.parametrize(("count", "allowed"), [(2000, True), (2001, False)])
def test_envelope_field_limit(count: int, allowed: bool) -> None:
    body = payload()
    body["documents"][0].update(
        {
            "method": "collect",
            "entries": [
                {
                    "page_id": "page",
                    "fields": [
                        {
                            "signer_id": "signer",
                            "field_id": f"field-{index}",
                            "display_settings": {
                                "left": 0,
                                "top": 0,
                                "width": 20,
                                "height": 10,
                                "fontSize": 12,
                            },
                        }
                        for index in range(count)
                    ],
                }
            ],
        }
    )
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        resource = EnvelopeResource(http, "account")
        if allowed:
            resource.create(body)
        else:
            with pytest.raises(ValidationError, match="2000 fields"):
                resource.create(body)
    assert len(requests) == int(allowed)


@pytest.mark.parametrize("expiration", [0, "", 2000000000.5, "2000000000", "2033-05-18"])
def test_envelope_expiration_passes_unchanged(expiration: Any) -> None:
    import json

    body = payload()
    body["documents"][0]["expires_at"] = expiration
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        EnvelopeResource(http, "account").create(body)
    assert json.loads(requests[0].content)["documents"][0]["expires_at"] == expiration


@pytest.mark.parametrize("key", ["key\r\nX-Api-Key: injected", "\x00", "não-ascii", 12])
def test_idempotency_header_rejects_invalid_values(key: Any) -> None:
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        with pytest.raises(ValidationError, match="idempotency_key"):
            EnvelopeResource(http, "account").create(payload(), idempotency_key=key)
    assert requests == []
