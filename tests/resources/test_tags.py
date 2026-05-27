from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.tags import TagResource
from tests.conftest import make_envelope, make_response


class MockHttp:
    def __init__(self) -> None:
        self.last_url = ""
        self.last_kwargs: dict[str, object] = {}

    def get(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope([]))

    def post(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"id": "tag-1"}))

    def put(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"id": "tag-1"}))

    def delete(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"deleted": True}))


class TestTagResource:
    def test_list_uses_workspace_tag_endpoint_and_search_param(self) -> None:
        http = MockHttp()
        resource = TagResource(http, "acc")

        result = resource.list({"search": "contract", "per_page": 5})

        assert http.last_url == "accounts/acc/tags"
        assert http.last_kwargs["params"] == {"search": "contract", "per-page": 5}
        assert result == {"data": []}

    def test_create_posts_documented_body(self) -> None:
        http = MockHttp()
        resource = TagResource(http, "acc")

        resource.create({"name": "Contracts", "color": "#ff8800"})

        assert http.last_url == "accounts/acc/tags"
        assert http.last_kwargs["json"] == {"name": "Contracts", "color": "#ff8800"}

    def test_update_preserves_null_color_to_clear_server_side(self) -> None:
        http = MockHttp()
        resource = TagResource(http, "acc")

        resource.update("tag-1", {"color": None})

        assert http.last_url == "accounts/acc/tags/tag-1"
        assert http.last_kwargs["json"] == {"color": None}

    def test_delete_sends_force_only_when_true(self) -> None:
        http = MockHttp()
        resource = TagResource(http, "acc")

        resource.delete("tag-1")
        assert http.last_kwargs["params"] == {}

        resource.delete("tag-1", force=True)
        assert http.last_url == "accounts/acc/tags/tag-1"
        assert http.last_kwargs["params"] == {"force": True}

    def test_create_requires_name(self) -> None:
        resource = TagResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Tag name"):
            resource.create({"color": "ff8800"})

    def test_rejects_invalid_color(self) -> None:
        resource = TagResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Tag color"):
            resource.create({"name": "Contracts", "color": "orange"})
