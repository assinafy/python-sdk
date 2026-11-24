from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
import pytest

from assinafy import ApiError, AssinafyClient, ScheduledSendResource, ValidationError
from tests.resources.test_envelopes import client_for, payload


@pytest.mark.parametrize("envelope", [False, True])
@pytest.mark.parametrize("send_at", [1806580800, "2027-04-01T12:00:00Z", "2027-04-01T12:00:00"])
def test_schedule_reuses_creation_body_without_mutating_input(envelope: bool, send_at: Any) -> None:
    requests: list[httpx.Request] = []
    body = (
        payload()
        if envelope
        else {
            "method": "virtual",
            "signers": [{"id": "signer", "sign_as": "Witness"}],
            "expires_at": "2027-04-04",
            "max_total_credits": "1.25",
        }
    )
    body["send_at"] = send_at
    original = deepcopy(body)
    with client_for({"id": "send", "status": "pending"}, requests) as http:
        resource = ScheduledSendResource(http, "account")
        result = (
            resource.create_envelope(body, "other")
            if envelope
            else resource.create_assignment("doc", body)
        )
    assert result == {"id": "send", "status": "pending"}
    assert body == original
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == (
        "/v1/accounts/other/scheduled-sends" if envelope else "/v1/documents/doc/scheduled-sends"
    )
    assert json.loads(request.content) == body
    assert "Idempotency-Key" not in request.headers


@pytest.mark.parametrize("operation", ["cancel", "send"])
def test_state_changes_use_put_without_a_body(operation: str) -> None:
    requests: list[httpx.Request] = []
    with client_for({"status": "sent"}, requests) as http:
        resource = ScheduledSendResource(http, "account")
        assert getattr(resource, operation)("send-id", "other") == {"status": "sent"}
    assert requests[0].method == "PUT"
    assert requests[0].url.path == f"/v1/accounts/other/scheduled-sends/send-id/{operation}"
    assert not requests[0].content


def test_list_returns_pagination_and_keeps_workspace_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": 200, "data": [{"id": "send"}]},
            headers={"X-Pagination-Total-Count": "1"},
        )

    with AssinafyClient(api_key="test-key", account_id="account") as client:
        client._http._transport = httpx.MockTransport(handler)
        assert isinstance(client.scheduled_sends, ScheduledSendResource)
        assert client.scheduled_sends.list({"per_page": 5, "document_id": "doc"}) == {
            "data": [{"id": "send"}],
            "meta": {"total": 1},
        }
    assert requests[0].headers["X-Api-Key"] == "test-key"
    assert dict(requests[0].url.params) == {"per-page": "5", "document_id": "doc"}


@pytest.mark.parametrize(
    "send_at",
    [None, "", True, [], {}, 1.5, "tomorrow", "2027-04-01", "2027-02-30T12:00:00Z", 0, -1],
)
@pytest.mark.parametrize("envelope", [False, True])
def test_bad_schedule_rejected_before_io(send_at: Any, envelope: bool) -> None:
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        resource = ScheduledSendResource(http, "account")
        with pytest.raises(ValidationError):
            if envelope:
                resource.create_envelope({**payload(), "send_at": send_at})
            else:
                resource.create_assignment("doc", {"signers": ["s"], "send_at": send_at})
    assert not requests


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("create_assignment", ("doc", [])),
        ("create_assignment", ("../doc", {"send_at": 1806580800, "signers": ["s"]})),
        ("create_assignment", ("doc", {"send_at": 1806580800, "signers": ["s"], "typo": 1})),
        ("create_envelope", ({"send_at": 1806580800, "name": "x"},)),
        ("cancel", ("../send",)),
        ("send", ("",)),
        ("list", ({"status": "pending"},)),
        ("list", ({"document_id": ""},)),
    ],
)
def test_invalid_requests_never_reach_transport(method: str, args: tuple[Any, ...]) -> None:
    requests: list[httpx.Request] = []
    with client_for({}, requests) as http:
        with pytest.raises(ValidationError):
            getattr(ScheduledSendResource(http, "account"), method)(*args)
    assert not requests


@pytest.mark.parametrize("status", [409, 429, 500])
def test_failed_send_is_not_retried_and_preserves_error_details(status: int) -> None:
    requests: list[httpx.Request] = []
    body = {"status": status, "message": "Unable to send", "code": "CreditCeilingExceeded"}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Retry-After": "5"})

    with httpx.Client(
        base_url="https://api.example.test/v1/", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ApiError) as caught:
            ScheduledSendResource(http, "account").send("send")
    assert caught.value.response_data == body
    assert caught.value.retry_after == 5
    assert len(requests) == 1
