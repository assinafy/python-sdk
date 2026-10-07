from __future__ import annotations

import httpx
import pytest

from assinafy.errors import ValidationError
from assinafy.resources.webhooks import WebhookResource
from tests.conftest import MockResponse, make_envelope, make_response


class TestWebhookResource:
    def test_register_complete_contract_body_does_not_require_a_preflight_get(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                raise AssertionError("complete registration must not perform GET")

            def put(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"is_active": True}))

        body = {
            "url": "https://example.com/webhook",
            "email": "ops@example.com",
            "events": ["document_ready"],
            "is_active": True,
        }
        WebhookResource(MockHttp(), "acc").register(body)
        assert captured_body == [body]

    def test_register_defaults_include_document_prepared_when_no_subscription_exists(
        self,
    ) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope(None))

            def put(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"is_active": True}))

        resource = WebhookResource(MockHttp(), "acc")
        resource.register(
            {
                "url": "https://example.com/webhook",
                "email": "ops@example.com",
            }
        )

        assert captured_body[0] == {
            "url": "https://example.com/webhook",
            "email": "ops@example.com",
            "events": [
                "document_ready",
                "document_prepared",
                "signer_signed_document",
                "signer_rejected_document",
                "document_processing_failed",
            ],
            "is_active": True,
        }

    def test_register_preserves_existing_events_and_active_state_on_partial_update(
        self,
    ) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(
                    make_envelope(
                        {
                            "url": "https://old.example.com/webhook",
                            "email": "ops@example.com",
                            "events": ["document_ready"],
                            "is_active": False,
                        }
                    )
                )

            def put(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"is_active": False}))

        resource = WebhookResource(MockHttp(), "acc")
        resource.register({"url": "https://new.example.com/webhook", "email": "ops@example.com"})

        assert captured_body[0] == {
            "url": "https://new.example.com/webhook",
            "email": "ops@example.com",
            "events": ["document_ready"],
            "is_active": False,
        }

    def test_register_explicit_empty_events_clears_instead_of_defaulting(
        self,
    ) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope(None))

            def put(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"is_active": True}))

        resource = WebhookResource(MockHttp(), "acc")
        resource.register(
            {"url": "https://example.com/webhook", "email": "ops@example.com", "events": []}
        )

        assert captured_body[0]["events"] == []

    def test_get_returns_unwrapped_subscription(self) -> None:
        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope({"url": "https://example.com/hook"}))

        resource = WebhookResource(MockHttp(), "acc")
        result = resource.get()
        assert result == {"url": "https://example.com/hook"}

    def test_get_returns_none_on_404(self) -> None:
        class NotFoundResponse(MockResponse):
            def raise_for_status(self) -> None:
                raise httpx.HTTPStatusError(
                    "404",
                    request=httpx.Request("GET", "https://x/webhooks/subscriptions"),
                    response=httpx.Response(404, json={"status": 404, "message": "Not found"}),
                )

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                return NotFoundResponse(json_data={"status": 404, "message": "Not found"})

        resource = WebhookResource(MockHttp(), "acc")
        assert resource.get() is None

    def test_retry_dispatch_hits_documented_endpoint(self) -> None:
        captured_url: list[str] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                return make_response(make_envelope({"id": "dispatch-1"}))

        resource = WebhookResource(MockHttp(), "acc")
        result = resource.retry_dispatch("dispatch-1")

        assert captured_url[0] == "accounts/acc/webhooks/dispatch-1/retry"
        assert result["id"] == "dispatch-1"

    def test_list_event_types_calls_global_endpoint(self) -> None:
        captured_url: list[str] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                return make_response(make_envelope([]))

        resource = WebhookResource(MockHttp())
        resource.list_event_types()
        assert captured_url[0] == "webhooks/event-types"

    def test_list_dispatches_passes_filters_and_parses_pagination(self) -> None:
        captured_url: list[str] = []
        captured_params: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                captured_params.append(kwargs.get("params"))
                return make_response(
                    make_envelope([]),
                    headers={
                        "x-pagination-current-page": "1",
                        "x-pagination-per-page": "20",
                        "x-pagination-total-count": "2",
                        "x-pagination-page-count": "1",
                    },
                )

        resource = WebhookResource(MockHttp(), "acc")
        result = resource.list_dispatches({"delivered": False, "per-page": 20})

        assert captured_url[0] == "accounts/acc/webhooks"
        assert captured_params[0] == {"delivered": False, "per-page": 20}
        assert result["meta"] == {
            "current_page": 1,
            "per_page": 20,
            "total": 2,
            "last_page": 1,
        }

    def test_retry_dispatch_requires_dispatch_id(self) -> None:
        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope({}))

        resource = WebhookResource(MockHttp(), "acc")
        with pytest.raises(ValidationError):
            resource.retry_dispatch("")

    def test_inactivate_hits_correct_endpoint(self) -> None:
        captured_url: list[str] = []

        class MockHttp:
            def put(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                return make_response(make_envelope({"is_active": False}))

        resource = WebhookResource(MockHttp(), "acc")
        resource.inactivate()
        assert captured_url[0] == "accounts/acc/webhooks/inactivate"

    def test_no_delete_method_dead_endpoint_removed(self) -> None:
        # DELETE /accounts/{id}/webhooks/subscriptions returns 404 on the live
        # API; the documented disable path is inactivate(). Lock the removal in.
        assert not hasattr(WebhookResource, "delete")

    def test_register_requires_url(self) -> None:
        resource = WebhookResource(object(), "acc")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            resource.register({"email": "user@example.com"})

        with pytest.raises(ValidationError, match="mapping"):
            resource.register([])  # type: ignore[arg-type]

    def test_register_requires_email(self) -> None:
        resource = WebhookResource(object(), "acc")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            resource.register({"url": "https://example.com"})

    @pytest.mark.parametrize(
        "payload",
        [
            {"url": "https://example.com", "email": "ops@example.com", "typo": True},
            {"url": "https://example.com", "email": "ops@example.com", "events": "event"},
            {"url": "https://example.com", "email": "ops@example.com", "is_active": 1},
            {"url": "/relative", "email": "ops@example.com"},
            {"url": "https://example.com", "email": "not-an-email"},
        ],
    )
    def test_register_validates_exact_request_shape(self, payload: dict[str, object]) -> None:
        resource = WebhookResource(object(), "acc")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            resource.register(payload)  # type: ignore[arg-type]


class _RecordingHttp:
    def __init__(self, data: object) -> None:
        self.data = data
        self.calls: list[tuple[str, str, object]] = []

    def _record(self, method: str, url: str, kwargs: dict[str, object]) -> MockResponse:
        self.calls.append((method, url, kwargs.get("json")))
        return make_response(make_envelope(self.data))

    def get(self, url: str, **kwargs: object) -> MockResponse:
        return self._record("GET", url, kwargs)

    def post(self, url: str, **kwargs: object) -> MockResponse:
        return self._record("POST", url, kwargs)

    def put(self, url: str, **kwargs: object) -> MockResponse:
        return self._record("PUT", url, kwargs)

    def delete(self, url: str, **kwargs: object) -> MockResponse:
        return self._record("DELETE", url, kwargs)


_ENDPOINT = {
    "id": "ep1",
    "url": "https://example.com/hook",
    "email": "ops@example.com",
    "events": ["document_ready"],
    "is_active": True,
    "signing_enabled": True,
}


class TestWebhookEndpoints:
    def test_list_endpoints(self) -> None:
        http = _RecordingHttp([_ENDPOINT])
        assert WebhookResource(http, "acc").list_endpoints() == [_ENDPOINT]
        assert http.calls == [("GET", "accounts/acc/webhooks/endpoints", None)]

    def test_create_endpoint_sends_documented_body(self) -> None:
        http = _RecordingHttp(_ENDPOINT)
        body = {
            "url": "https://example.com/hook",
            "email": "ops@example.com",
            "events": ["document_ready"],
            "name": "ERP",
            "signing_enabled": True,
        }
        assert WebhookResource(http, "acc").create_endpoint(body) == _ENDPOINT
        assert http.calls == [("POST", "accounts/acc/webhooks/endpoints", body)]

    @pytest.mark.parametrize(
        "body",
        [
            {"url": "https://example.com/hook", "email": "ops@example.com"},
            {"url": "ftp://example.com", "email": "ops@example.com", "events": []},
            {"url": "https://example.com", "email": "ops@example.com", "events": [], "x": 1},
            {
                "url": "https://example.com",
                "email": "ops@example.com",
                "events": [],
                "signing_enabled": "yes",
            },
            {"url": "https://example.com", "email": "ops@example.com", "events": [], "name": " "},
        ],
    )
    def test_create_endpoint_rejects_invalid_bodies_before_sending(
        self, body: dict[str, object]
    ) -> None:
        http = _RecordingHttp(_ENDPOINT)
        with pytest.raises(ValidationError):
            WebhookResource(http, "acc").create_endpoint(body)
        assert http.calls == []

    def test_get_update_delete_endpoint_paths(self) -> None:
        http = _RecordingHttp(_ENDPOINT)
        resource = WebhookResource(http, "acc")
        resource.get_endpoint("ep1")
        resource.update_endpoint("ep1", {"is_active": False})
        http.data = []
        assert resource.delete_endpoint("ep1") is None
        assert http.calls == [
            ("GET", "accounts/acc/webhooks/endpoints/ep1", None),
            ("PUT", "accounts/acc/webhooks/endpoints/ep1", {"is_active": False}),
            ("DELETE", "accounts/acc/webhooks/endpoints/ep1", None),
        ]

    def test_update_endpoint_requires_a_field_and_a_safe_id(self) -> None:
        http = _RecordingHttp(_ENDPOINT)
        resource = WebhookResource(http, "acc")
        with pytest.raises(ValidationError):
            resource.update_endpoint("ep1", {})
        with pytest.raises(ValidationError):
            resource.update_endpoint("../x", {"is_active": True})
        assert http.calls == []

    def test_secret_get_and_rotate_return_the_secret(self) -> None:
        http = _RecordingHttp({"secret": "whsec_c2VjcmV0"})
        resource = WebhookResource(http, "acc")
        assert resource.get_endpoint_secret("ep1") == "whsec_c2VjcmV0"
        assert resource.rotate_endpoint_secret("ep1") == "whsec_c2VjcmV0"
        assert http.calls == [
            ("GET", "accounts/acc/webhooks/endpoints/ep1/secret", None),
            ("POST", "accounts/acc/webhooks/endpoints/ep1/secret/rotate", None),
        ]

    def test_secret_missing_from_response_raises(self) -> None:
        from assinafy.errors import AssinafyError

        with pytest.raises(AssinafyError):
            WebhookResource(_RecordingHttp({}), "acc").get_endpoint_secret("ep1")
