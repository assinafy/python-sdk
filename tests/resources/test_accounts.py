from __future__ import annotations

import json

import httpx
import pytest

from assinafy.errors import ValidationError
from assinafy.resources.accounts import AccountResource


def _resource(handler: httpx.MockTransport) -> tuple[AccountResource, httpx.Client]:
    client = httpx.Client(base_url="https://example.test/v1/", transport=handler)
    return AccountResource(client, "acc-1"), client


class TestAccountResource:
    def test_list_create_get_update_and_theme(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET" and request.url.path == "/v1/accounts":
                data: object = [{"id": "acc-1", "name": "Example"}]
            elif request.method == "POST":
                data = {"id": "acc-2", "name": "Example"}
            elif request.method == "PUT":
                data = {"id": "acc-1", "name": "Renamed"}
            elif request.url.path.endswith("/theme"):
                data = {"account_name": "Example", "logo": None}
            else:
                data = {"id": "acc-1", "name": "Example"}
            return httpx.Response(200, json={"status": 200, "data": data})

        resource, client = _resource(httpx.MockTransport(handler))
        try:
            assert resource.list() == [{"id": "acc-1", "name": "Example"}]
            assert resource.create("Example", "Account")["id"] == "acc-2"
            assert resource.get()["id"] == "acc-1"
            assert resource.update({"name": "Renamed"})["name"] == "Renamed"
            assert resource.theme()["account_name"] == "Example"
        finally:
            client.close()

        assert requests[0].method == "GET"
        assert requests[0].url.path == "/v1/accounts"
        assert requests[1].method == "POST"
        assert requests[1].url.path == "/v1/accounts"
        assert json.loads(requests[1].content) == {
            "name": "Example",
            "notification_sender_type": "Account",
        }
        assert requests[2].method == "GET"
        assert requests[2].url.path == "/v1/accounts/acc-1"
        assert requests[3].method == "PUT"
        assert requests[3].url.path == "/v1/accounts/acc-1"
        assert json.loads(requests[3].content) == {"name": "Renamed"}
        assert requests[4].method == "GET"
        assert requests[4].url.path == "/v1/accounts/acc-1/theme"

    def test_delete_omits_body_unless_force_is_true(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"status": 200, "message": ""})

        resource, client = _resource(httpx.MockTransport(handler))
        try:
            resource.delete()
            resource.delete("acc-2", force=True)
        finally:
            client.close()

        assert [request.method for request in requests] == ["DELETE", "DELETE"]
        assert [request.url.path for request in requests] == [
            "/v1/accounts/acc-1",
            "/v1/accounts/acc-2",
        ]
        assert requests[0].content == b""
        assert json.loads(requests[1].content) == {"force": True}

    def test_delete_rejects_explicit_empty_account_instead_of_using_default(self) -> None:
        client = httpx.Client(
            base_url="https://example.test/v1/",
            transport=httpx.MockTransport(lambda request: pytest.fail("request must not be sent")),
        )
        try:
            with pytest.raises(ValidationError, match="Account ID is required"):
                AccountResource(client, "default-account").delete("")
        finally:
            client.close()

    def test_stats_sends_filters_and_validates_them(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"status": 200, "data": [{"period": "2026-08"}]},
            )

        resource, client = _resource(httpx.MockTransport(handler))
        try:
            assert resource.stats("daily", "2026-08") == [{"period": "2026-08"}]
            with pytest.raises(ValidationError, match="granularity"):
                resource.stats("weekly")
            with pytest.raises(ValidationError, match="YYYY-MM"):
                resource.stats("monthly", "2026-13")
            with pytest.raises(ValidationError, match="month is required"):
                resource.stats("daily")
        finally:
            client.close()

        assert requests[0].url.path == "/v1/accounts/acc-1/stats"
        assert requests[0].method == "GET"
        assert dict(requests[0].url.params) == {
            "granularity": "daily",
            "month": "2026-08",
        }
        assert len(requests) == 1

    def test_logo_download_upload_and_delete(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, content=b"downloaded-logo")
            return httpx.Response(200, json={"status": 200, "message": ""})

        resource, client = _resource(httpx.MockTransport(handler))
        try:
            assert resource.download_logo() == b"downloaded-logo"
            resource.upload_logo({"buffer": b"\x89PNG\r\n\x1a\nimage", "file_name": "logo.png"})
            resource.delete_logo()
        finally:
            client.close()

        assert [request.method for request in requests] == ["GET", "POST", "DELETE"]
        upload = requests[1]
        assert upload.url.path == "/v1/accounts/acc-1/logo"
        assert upload.headers["Content-Type"].startswith("multipart/form-data; boundary=")
        assert b'name="file"' in upload.content
        assert b'filename="logo.png"' in upload.content
        assert b"Content-Type: image/png" in upload.content
        assert b"\x89PNG\r\n\x1a\nimage" in upload.content
        assert requests[2].url.path == "/v1/accounts/acc-1/logo"

    def test_account_input_validation(self) -> None:
        resource, client = _resource(
            httpx.MockTransport(lambda request: httpx.Response(500, request=request))
        )
        try:
            with pytest.raises(ValidationError, match="sender"):
                resource.create("Example", "Unknown")
            with pytest.raises(ValidationError, match="Unknown account fields"):
                resource.update({"typo": True})
            with pytest.raises(ValidationError, match="At least one"):
                resource.update({})
            with pytest.raises(ValidationError, match="mapping"):
                resource.update([])  # type: ignore[arg-type]
            with pytest.raises(ValidationError, match="force must be boolean"):
                resource.delete(force=1)  # type: ignore[arg-type]
        finally:
            client.close()


@pytest.mark.parametrize("account_id", [None, "other"])
def test_account_expansion_usage_policy_and_embed_origin_wire_contract(
    account_id: str | None,
) -> None:
    requests: list[httpx.Request] = []
    policy = {"editable": True, "owners_receive_all": True, "events": {"SignerViewed": True}}
    origin = {"id": "origin-id", "origin": "https://app.example.com", "created_at": "now"}
    usage = {"plan": None, "documents_renewal_date": None, "balances": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        data: object = origin
        if request.url.path.endswith("notification-policy"):
            data = policy
        elif request.url.path.endswith("usage"):
            data = usage
        elif request.method == "DELETE":
            data = []
        elif request.method == "GET" and request.url.path.endswith("embed-origins"):
            data = [origin]
        elif request.method == "GET":
            data = {"id": "account-id", "signing_features": {"Embed": True}}
        return httpx.Response(200, json={"status": 200, "data": data})

    resource, client = _resource(httpx.MockTransport(handler))
    with client:
        assert resource.get(account_id, expand="signing_features")["signing_features"] == {
            "Embed": True
        }
        assert resource.usage(account_id) == usage
        assert resource.notification_policy(account_id) == policy
        body = {"events": {"SignerViewed": True}, "owners_receive_all": True}
        assert resource.update_notification_policy(body, account_id) == policy
        assert resource.list_embed_origins(account_id) == [origin]
        assert resource.add_embed_origin("https://app.example.com", account_id) == origin
        assert (
            resource.update_embed_origin("origin-id", "https://app.example.com", account_id)
            == origin
        )
        assert resource.delete_embed_origin("origin-id", account_id) is None
    prefix = f"/v1/accounts/{account_id or 'acc-1'}"
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", prefix),
        ("GET", prefix + "/usage"),
        ("GET", prefix + "/notification-policy"),
        ("PUT", prefix + "/notification-policy"),
        ("GET", prefix + "/embed-origins"),
        ("POST", prefix + "/embed-origins"),
        ("PUT", prefix + "/embed-origins/origin-id"),
        ("DELETE", prefix + "/embed-origins/origin-id"),
    ]
    assert dict(requests[0].url.params) == {"expand": "signing_features"}
    assert json.loads(requests[3].content) == body
    assert (
        json.loads(requests[5].content)
        == json.loads(requests[6].content)
        == {"origin": "https://app.example.com"}
    )
    assert all(not requests[i].content for i in [0, 1, 2, 4, 7])


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "http://example.com",
        "https://example.com/path",
        "https://example.com?",
        "https://example.com#",
        "https://user@example.com",
        "https://@example.com",
        "https://*.example.com",
        "https://example.com:bad",
        "https://example.com:99999",
        "https://example.com:0",
        "https://example.com:",
        "https://[invalid",
        "http://[::1]",
        "https://example.com\n",
        "https://example.com\\other",
        "//example.com",
    ],
)
@pytest.mark.parametrize("operation", ["add_embed_origin", "update_embed_origin"])
def test_embed_origin_rejects_invalid_origins_before_io(origin: object, operation: str) -> None:
    resource, client = _resource(httpx.MockTransport(lambda r: pytest.fail("unexpected I/O")))
    with client, pytest.raises(ValidationError):
        args = (origin,) if operation == "add_embed_origin" else ("origin-id", origin)
        getattr(resource, operation)(*args)


@pytest.mark.parametrize(
    "origin",
    ["https://Example.com:443/", "http://localhost:8080", "http://127.0.0.1", "https://[::1]"],
)
def test_embed_origin_preserves_valid_values_for_server_normalization(origin: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"origin": origin}
        return httpx.Response(200, json={"status": 200, "data": {"origin": origin}})

    resource, client = _resource(httpx.MockTransport(handler))
    with client:
        assert resource.add_embed_origin(origin) == {"origin": origin}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"editable": True},
        {"owners_receive_all": 1},
        {"events": []},
        {"events": {"unknown": True}},
        {"events": {"SignerViewed": 1}},
    ],
)
def test_policy_invalid_updates_do_not_send(payload: object) -> None:
    resource, client = _resource(httpx.MockTransport(lambda r: pytest.fail("unexpected I/O")))
    with client, pytest.raises(ValidationError):
        resource.update_notification_policy(payload)  # type: ignore[arg-type]


def test_new_account_options_validate_path_ids_and_expansion() -> None:
    resource, client = _resource(httpx.MockTransport(lambda r: pytest.fail("unexpected I/O")))
    with client:
        with pytest.raises(ValidationError):
            resource.get(expand="unknown")
        for operation, args in [
            (resource.usage, ("../other",)),
            (resource.notification_policy, ("../other",)),
            (resource.list_embed_origins, ("../other",)),
            (resource.update_embed_origin, ("../other", "https://example.com")),
            (resource.delete_embed_origin, ("../other",)),
        ]:
            with pytest.raises(ValidationError):
                operation(*args)


def test_policy_accepts_empty_event_map_with_an_owner_setting() -> None:
    body = {"events": {}, "owners_receive_all": False}

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == body
        return httpx.Response(200, json={"status": 200, "data": body})

    resource, client = _resource(httpx.MockTransport(handler))
    with client:
        assert resource.update_notification_policy(body) == body
