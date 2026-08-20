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
            resource.register({"email": "a@b.com"})

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
        ],
    )
    def test_register_validates_exact_request_shape(self, payload: dict[str, object]) -> None:
        resource = WebhookResource(object(), "acc")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            resource.register(payload)  # type: ignore[arg-type]
