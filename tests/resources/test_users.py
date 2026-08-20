from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from assinafy.errors import ValidationError
from assinafy.resources.users import UserResource

PREFERENCES = {
    "DocumentCompleted": True,
    "SignerDeclined": False,
    "DocumentCancelled": True,
    "DocumentAboutToExpire": False,
    "DocumentExpired": True,
    "DocumentExpirationReset": False,
    "DocumentProcessingFailed": True,
    "TemplateProcessingFailed": False,
    "SignerWhatsappFailed": True,
}


def _resource(handler: httpx.MockTransport) -> tuple[UserResource, httpx.Client]:
    client = httpx.Client(base_url="https://example.test/v1/", transport=handler)
    return UserResource(client), client


class TestUserResource:
    def test_me_and_stats_use_authenticated_user_endpoints(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            data: object
            if request.url.path.endswith("/stats"):
                data = [{"period": "2026-08"}]
            else:
                data = {"id": "user-1", "name": "Example User"}
            return httpx.Response(200, json={"status": 200, "data": data})

        resource, client = _resource(httpx.MockTransport(handler))
        try:
            assert resource.me()["id"] == "user-1"
            assert resource.stats("daily", "2026-08") == [{"period": "2026-08"}]
        finally:
            client.close()

        assert requests[0].url.path == "/v1/users/self"
        assert requests[1].url.path == "/v1/users/self/stats"
        assert dict(requests[1].url.params) == {
            "granularity": "daily",
            "month": "2026-08",
        }

    def test_notification_preferences_get_and_update_exact_payloads(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"status": 200, "data": PREFERENCES})

        resource, client = _resource(httpx.MockTransport(handler))
        try:
            assert resource.notification_preferences() == PREFERENCES
            updated = resource.update_notification_preferences({"DocumentCompleted": False})
            assert updated == PREFERENCES
        finally:
            client.close()

        assert requests[0].method == "GET"
        assert requests[0].url.path == "/v1/users/self/notification-preferences"
        assert requests[1].method == "PUT"
        assert requests[1].url.path == "/v1/users/self/notification-preferences"
        assert json.loads(requests[1].content) == {"DocumentCompleted": False}

    @pytest.mark.parametrize(
        ("preferences", "message"),
        [
            ([], "mapping"),
            ({}, "At least one"),
            ({"UnknownPreference": True}, "Unknown notification preference"),
            ({"DocumentCompleted": 1}, "must be boolean"),
        ],
    )
    def test_update_notification_preferences_validates_input(
        self,
        preferences: Any,
        message: str,
    ) -> None:
        resource, client = _resource(
            httpx.MockTransport(lambda request: httpx.Response(500, request=request))
        )
        try:
            with pytest.raises(ValidationError, match=message):
                resource.update_notification_preferences(preferences)  # type: ignore[arg-type]
        finally:
            client.close()

    def test_user_stats_reuses_stats_validation(self) -> None:
        resource, client = _resource(
            httpx.MockTransport(lambda request: httpx.Response(500, request=request))
        )
        try:
            with pytest.raises(ValidationError, match="month is required"):
                resource.stats("daily")
            with pytest.raises(ValidationError, match="YYYY-MM"):
                resource.stats("monthly", "August 2026")
        finally:
            client.close()
