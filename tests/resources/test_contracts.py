from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal, localcontext
from typing import Any, get_args

import httpx
import pytest

from assinafy import (
    ApiError,
    AssinafyClient,
    ContractRelationType,
    ContractResource,
    ContractStatus,
    NetworkError,
    ValidationError,
)
from assinafy.resources import ContractResource as ExportedContractResource

_CONTRACT = {
    "resource": "document_contract",
    "document_id": "document-id",
    "status": "active",
    "counterparty_name": "Example Company",
    "counterparty_taxpayer_id": None,
    "value": 1200.50,
    "currency": "BRL",
    "start_date": "2026-11-01",
    "end_date": "2027-10-31",
    "auto_renew": False,
    "renewal_term_months": 12,
    "notice_period_days": 30,
    "term": 1,
    "owner_id": None,
    "metadata": None,
    "external_references": [],
    "created_at": "2026-10-28T12:00:00Z",
    "updated_at": "2026-10-28T12:00:00Z",
}
_CALLS = [
    ("list", (), "GET", "contracts", None),
    ("get", ("document-id",), "GET", "documents/document-id/contract", None),
    (
        "update",
        ("document-id", {"value": 1300, "updated_at": "2026-10-28T12:00:00Z"}),
        "PUT",
        "documents/document-id/contract",
        {"value": 1300, "updated_at": "2026-10-28T12:00:00Z"},
    ),
    ("related", ("document-id",), "GET", "documents/document-id/contract/related", None),
    (
        "renew",
        ("document-id", {"term": 1, "value": None}),
        "POST",
        "documents/document-id/contract/renew",
        {"term": 1, "value": None},
    ),
    (
        "terminate",
        ("document-id",),
        "POST",
        "documents/document-id/contract/terminate",
        {},
    ),
]


@pytest.fixture
def recording_client() -> Iterator[tuple[AssinafyClient, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        data: Any = [_CONTRACT] if request.url.path.endswith("/contracts") else _CONTRACT
        return httpx.Response(200, json={"status": 200, "data": data})

    with AssinafyClient(api_key="workspace-key", account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(handler)
        yield client, requests


def test_contract_resources_and_types_are_public(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
) -> None:
    client, _ = recording_client
    assert isinstance(client.contracts, ContractResource)
    assert ExportedContractResource is ContractResource
    assert client.contracts._http is client.get_http_client()
    assert get_args(ContractStatus) == ("draft", "active", "expired", "terminated")
    assert get_args(ContractRelationType) == ("amendment", "renewal", "termination")


@pytest.mark.parametrize("operation,args,verb,suffix,body", _CALLS)
@pytest.mark.parametrize("account_id", [None, "other-account"])
@pytest.mark.parametrize("credential", ["api_key", "token"])
def test_every_operation_uses_its_workspace_and_documented_wire_request(
    operation: str,
    args: tuple[Any, ...],
    verb: str,
    suffix: str,
    body: dict[str, Any] | None,
    account_id: str | None,
    credential: str,
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        data: Any = [_CONTRACT] if operation == "list" else _CONTRACT
        return httpx.Response(200, json={"status": 200, "data": data})

    with AssinafyClient(account_id="account-id", **{credential: "synthetic-credential"}) as client:
        client._http._transport = httpx.MockTransport(handler)
        result = getattr(client.contracts, operation)(*args, account_id=account_id)

    assert result == ({"data": [_CONTRACT]} if operation == "list" else _CONTRACT)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == verb
    assert request.url.path == f"/v1/accounts/{account_id or 'account-id'}/{suffix}"
    assert not request.url.params
    if credential == "api_key":
        assert request.headers["X-Api-Key"] == "synthetic-credential"
        assert "Authorization" not in request.headers
    else:
        assert request.headers["Authorization"] == "Bearer synthetic-credential"
        assert "X-Api-Key" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body


def test_list_filters_aliases_expansion_and_pagination_headers() -> None:
    requests = []
    expanded = {**_CONTRACT, "document": {"id": "document-id", "has_contract": True}}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": 200, "data": [expanded]},
            headers={
                "X-Pagination-Current-Page": "2",
                "X-Pagination-Per-Page": "20",
                "X-Pagination-Total-Count": "21",
                "X-Pagination-Page-Count": "2",
            },
        )

    params = {
        "status": "active,expired",
        "counterparty": "Example Company",
        "search": "Services",
        "end_date_from": "2026-01-01",
        "end_date_to": "2027-12-31",
        "ending_within_days": 0,
        "external_system": "crm",
        "external_id": "contract-1",
        "sort": "-updated_at",
        "expand": "document",
        "page": 2,
        "per_page": 20,
    }
    with AssinafyClient(token="oauth-token", account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(handler)
        assert client.contracts.list(params) == {
            "data": [expanded],
            "meta": {"current_page": 2, "per_page": 20, "total": 21, "last_page": 2},
        }
    assert dict(requests[0].url.params) == {
        **{key: str(value) for key, value in params.items() if key != "per_page"},
        "per-page": "20",
    }
    assert params["per_page"] == 20


def test_omitted_filters_and_wire_pagination_alias(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
) -> None:
    client, requests = recording_client
    client.contracts.list({"search": None, "per-page": 5, "end_date_from": "0999-01-01"})
    assert dict(requests[0].url.params) == {"per-page": "5", "end_date_from": "0999-01-01"}


@pytest.mark.parametrize(
    "field",
    [
        "counterparty_name",
        "counterparty_taxpayer_id",
        "value",
        "currency",
        "start_date",
        "end_date",
        "auto_renew",
        "renewal_term_months",
        "notice_period_days",
        "owner_id",
        "metadata",
        "external_references",
        "parent_document_id",
        "updated_at",
    ],
)
def test_update_preserves_each_documented_null(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], field: str
) -> None:
    client, requests = recording_client
    payload = {field: None}
    client.contracts.update("document-id", payload)
    assert json.loads(requests[0].content) == payload == {field: None}


def test_full_terms_keep_numbers_currency_and_references_unchanged(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
) -> None:
    client, requests = recording_client
    payload = {
        "status": "active",
        "counterparty_name": "Example Company",
        "counterparty_taxpayer_id": "11.222.333/0001-81",
        "value": 9999999999999.99,
        "currency": "USD",
        "start_date": "2024-02-29",
        "end_date": "2024-02-29",
        "auto_renew": True,
        "renewal_term_months": 600,
        "notice_period_days": 3650,
        "owner_id": "member-id",
        "metadata": {"department": "sales", "revision_at": "2026-10-28T12:00:00Z"},
        "external_references": [
            {"system": "CRM", "id": "Contract-1"},
            {"system": "crm", "id": "contract-1"},
        ],
        "updated_at": "2026-10-28T12:00:00.123-03:00",
    }
    client.contracts.update("document-id", payload)
    assert len(requests) == 1
    assert json.loads(requests[0].content) == payload


@pytest.mark.parametrize("value", [0, 0.01, 12, 1200.50])
def test_update_sends_valid_money_without_coercion(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], value: int | float
) -> None:
    client, requests = recording_client
    client.contracts.update("document-id", {"value": value, "currency": "brl"})
    assert json.loads(requests[0].content) == {"value": value, "currency": "brl"}


def test_money_validation_is_independent_of_application_decimal_precision(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
) -> None:
    client, requests = recording_client
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(ValidationError):
            client.contracts.update("document-id", {"value": 1.001})
        assert not requests
        client.contracts.update("document-id", {"value": 1234.56})
    assert json.loads(requests[0].content) == {"value": 1234.56}


@pytest.mark.parametrize("status", ["draft", "active", "expired", "terminated"])
def test_initial_status_and_state_dependent_rules_are_left_to_the_api(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], status: str
) -> None:
    client, requests = recording_client
    client.contracts.update("document-id", {"status": status, "end_date": "2020-01-01"})
    assert json.loads(requests[0].content) == {"status": status, "end_date": "2020-01-01"}


def test_documented_term_limits_accept_boundary_values(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
) -> None:
    client, requests = recording_client
    payload = {
        "counterparty_name": "x" * 255,
        "start_date": "1000-01-01",
        "end_date": "9999-12-31",
        "renewal_term_months": 1,
        "notice_period_days": 0,
        "metadata": {f"field{i}": "x" * 500 for i in range(50)},
        "external_references": [
            {"system": "C" * 64, "id": f"{i:03}" + "x" * 252} for i in range(20)
        ],
    }
    client.contracts.update("document-id", payload)
    assert json.loads(requests[0].content) == payload


@pytest.mark.parametrize("relation", ["amendment", "renewal", "termination"])
def test_link_and_read_preserve_amendment_response(relation: str) -> None:
    amendment = {
        "resource": "document_contract_amendment",
        "document_id": "instrument-id",
        "document_name": "Instrument.pdf",
        "parent_document_id": "document-id",
        "relation_type": relation,
        "number": None,
        "status": "pending",
        "document_status": "pending_signature",
        "apply_error": None,
        "currency": None,
        "terms": None,
        "changes": None,
        "applied_at": None,
        "created_at": "2026-10-28T12:00:00Z",
        "updated_at": "2026-10-28T12:00:00Z",
    }
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": 200, "data": amendment})

    payload = {"parent_document_id": "document-id", "relation_type": relation}
    if relation == "amendment":
        payload["end_date"] = "2028-10-31"
    with AssinafyClient(account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(handler)
        assert client.contracts.update("instrument-id", payload) == amendment
        assert client.contracts.get("instrument-id") == amendment
    assert json.loads(requests[0].content) == payload
    assert requests[1].url.path.endswith("/documents/instrument-id/contract")


@pytest.mark.parametrize("end_date", [None, ""])
def test_term_renewal_keeps_null_and_empty_end_date(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], end_date: str | None
) -> None:
    client, requests = recording_client
    payload = {"term": 1, "end_date": end_date, "value": None, "updated_at": None}
    client.contracts.renew("document-id", payload)
    assert json.loads(requests[0].content) == payload


def test_explicit_date_renewal_omits_term_and_termination_preserves_reason(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
) -> None:
    client, requests = recording_client
    client.contracts.renew("document-id", {"end_date": "2028-10-31"})
    client.contracts.terminate("document-id", {"reason": "<b>Replaced</b>", "updated_at": None})
    client.contracts.terminate("document-id", {"reason": None})
    assert [json.loads(request.content) for request in requests] == [
        {"end_date": "2028-10-31"},
        {"reason": "<b>Replaced</b>", "updated_at": None},
        {"reason": None},
    ]


@pytest.mark.parametrize(
    "operation,payload", [("update", {"value": 1}), ("renew", {"term": 1}), ("terminate", {})]
)
def test_changed_contract_preserves_conflict_without_retry(
    operation: str, payload: dict[str, Any]
) -> None:
    requests = []
    conflict = {"status": 409, "message": "Contract changed", "code": "ContractChanged"}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(409, json=conflict)

    precondition = "2026-10-28T12:00:00Z"
    with AssinafyClient(account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(handler)
        with pytest.raises(ApiError) as error:
            getattr(client.contracts, operation)(
                "document-id", {**payload, "updated_at": precondition}
            )
    assert error.value.status_code == 409
    assert error.value.response_data == conflict
    assert len(requests) == 1
    assert json.loads(requests[0].content)["updated_at"] == precondition


@pytest.mark.parametrize("failure", ["timeout", "server", "repeated-term"])
def test_renewal_never_retries_an_ambiguous_or_replayed_request(failure: str) -> None:
    requests = []
    response = {
        "status": 400,
        "message": "Already renewed",
        "errors": [{"field": "term", "code": "TermMismatch", "message": "Already renewed"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(500 if failure == "server" else 400, json=response)

    with AssinafyClient(account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(handler)
        with pytest.raises(NetworkError if failure == "timeout" else ApiError):
            client.contracts.renew("document-id", {"term": 1})
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"term": 1}


def test_repeated_explicit_update_is_sent_once_per_call(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
) -> None:
    client, requests = recording_client
    payload = {"value": 100, "external_references": []}
    client.contracts.update("document-id", payload)
    client.contracts.update("document-id", payload)
    assert len(requests) == 2
    assert [json.loads(request.content) for request in requests] == [payload, payload]


@pytest.mark.parametrize("operation", ["list", "get", "related", "update", "renew", "terminate"])
def test_scope_failures_surface_without_changing_authentication(operation: str) -> None:
    requests = []
    body = {"status": 403, "message": "Insufficient scope"}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            403, json=body, headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'}
        )

    args = next(args for name, args, *_ in _CALLS if name == operation)
    with AssinafyClient(token="oauth-token", account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(handler)
        with pytest.raises(ApiError) as error:
            getattr(client.contracts, operation)(*args)
    assert error.value.status_code == 403
    assert error.value.response_data == body
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer oauth-token"


@pytest.mark.parametrize("code", [None, "NoContractTerms"])
def test_missing_document_and_missing_contract_remain_distinguishable(code: str | None) -> None:
    body = {"status": 404, "message": "Not found"}
    if code:
        body["code"] = code
    with AssinafyClient(account_id="account-id") as client:
        client._http._transport = httpx.MockTransport(
            lambda request: httpx.Response(404, json=body)
        )
        with pytest.raises(ApiError) as error:
            client.contracts.get("document-id")
    assert error.value.status_code == 404
    assert error.value.response_data == body


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "invalid",
        {},
        {"unknown": 1},
        {"status": None},
        {"status": "pending"},
        {"relation_type": None},
        {"relation_type": "other"},
        {"value": True},
        {"value": -0.01},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": 10000000000000},
        {"value": 1.001},
        {"value": "100"},
        {"value": Decimal("1.00")},
        {"currency": "US"},
        {"currency": "123"},
        {"currency": []},
        {"auto_renew": 1},
        {"auto_renew": "false"},
        {"start_date": "0999-12-31"},
        {"start_date": "2026-02-29"},
        {"end_date": "2026-02-30"},
        {"end_date": "2026-1-1"},
        {"end_date": "2026-10-28T12:00:00Z"},
        {"end_date": ""},
        {"start_date": "2027-01-02", "end_date": "2027-01-01"},
        {"updated_at": "2026-10-28"},
        {"updated_at": "2026-10-28T12:00:00+00:60"},
        {"renewal_term_months": 0},
        {"renewal_term_months": 601},
        {"renewal_term_months": True},
        {"notice_period_days": -1},
        {"notice_period_days": 3651},
        {"notice_period_days": 1.5},
        {"counterparty_name": "x" * 256},
        {"counterparty_name": "<b>Example</b>"},
        {"counterparty_taxpayer_id": "x" * 21},
        {"owner_id": " "},
        {"parent_document_id": 1},
        {"metadata": []},
        {"metadata": {str(i): "x" for i in range(51)}},
        {"metadata": {"": "x"}},
        {"metadata": {"x" * 41: "x"}},
        {"metadata": {"bad key": "x"}},
        {"metadata": {"x": None}},
        {"metadata": {"x": 1}},
        {"metadata": {"x": "x" * 501}},
        {"metadata": {"x": "<script>bad</script>"}},
        {"metadata": {"0": "a", "1": "b"}},
        {"metadata": {"0": "a"}},
        {"external_references": {}},
        {"external_references": [{"system": "crm", "id": str(i)} for i in range(21)]},
        {"external_references": [None]},
        {"external_references": [{"system": "crm"}]},
        {"external_references": [{"id": "id"}]},
        {"external_references": [{"system": "crm", "id": "id", "unknown": 1}]},
        {"external_references": [{"system": "bad system", "id": "id"}]},
        {"external_references": [{"system": "x" * 65, "id": "id"}]},
        {"external_references": [{"system": "crm", "id": " "}]},
        {"external_references": [{"system": "crm", "id": "x" * 256}]},
        {"external_references": [{"system": "crm", "id": "contract-😀"}]},
    ],
)
def test_invalid_terms_fail_before_http(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], payload: Any
) -> None:
    client, requests = recording_client
    with pytest.raises(ValidationError):
        client.contracts.update("document-id", payload)
    assert not requests


@pytest.mark.parametrize(
    "params",
    [
        [],
        "invalid",
        {"unknown": 1},
        {"status": []},
        {"status": "active,"},
        {"status": "pending"},
        {"page": 0},
        {"per_page": True},
        {"per_page": 101},
        {"ending_within_days": -1},
        {"ending_within_days": 3651},
        {"ending_within_days": "30"},
        {"search": []},
        {"end_date_from": "2026-02-30"},
        {"end_date_to": "2026-10-28T00:00:00Z"},
        {"sort": "value"},
        {"expand": "owner"},
        {"per_page": 20, "per-page": 40},
    ],
)
def test_invalid_filters_fail_before_http(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], params: Any
) -> None:
    client, requests = recording_client
    with pytest.raises(ValidationError):
        client.contracts.list(params)
    assert not requests


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"end_date": None},
        {"end_date": ""},
        {"term": None},
        {"term": 0},
        {"term": True},
        {"term": 1.0},
        {"term": "1"},
        {"term": 1, "status": "active"},
    ],
)
def test_invalid_renewal_guards_fail_before_http(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], payload: dict[str, Any]
) -> None:
    client, requests = recording_client
    with pytest.raises(ValidationError):
        client.contracts.renew("document-id", payload)
    assert not requests


@pytest.mark.parametrize(
    "payload", [[], {"reason": 1}, {"reason": "x" * 501}, {"status": "terminated"}]
)
def test_invalid_termination_fails_before_http(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], payload: Any
) -> None:
    client, requests = recording_client
    with pytest.raises(ValidationError):
        client.contracts.terminate("document-id", payload)
    assert not requests


@pytest.mark.parametrize("operation,args,verb,suffix,body", _CALLS)
@pytest.mark.parametrize(
    "bad_id", ["../other", "a/b", "a\\b", "a?x=y", "a#x", "a%2Fb", ".", "..", "", None]
)
def test_every_operation_rejects_invalid_account_ids_before_http(
    recording_client: tuple[AssinafyClient, list[httpx.Request]],
    operation: str,
    args: tuple[Any, ...],
    verb: str,
    suffix: str,
    body: dict[str, Any] | None,
    bad_id: Any,
) -> None:
    client, requests = recording_client
    if bad_id is None:
        client.contracts._default_account_id = None
    with pytest.raises(ValidationError):
        getattr(client.contracts, operation)(*args, account_id=bad_id)
    assert not requests


@pytest.mark.parametrize("operation", ["get", "related", "update", "renew", "terminate"])
@pytest.mark.parametrize(
    "bad_id", ["../other", "a/b", "a?x=y", "a#x", "a%2Fb", ".", "..", "", None, 1]
)
def test_every_document_operation_rejects_invalid_path_ids_before_http(
    recording_client: tuple[AssinafyClient, list[httpx.Request]], operation: str, bad_id: Any
) -> None:
    client, requests = recording_client
    args = next(args for name, args, *_ in _CALLS if name == operation)
    with pytest.raises(ValidationError):
        getattr(client.contracts, operation)(bad_id, *args[1:])
    assert not requests
