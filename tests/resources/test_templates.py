from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.documents import DocumentResource
from assinafy.resources.templates import TemplateResource
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
        return make_response(make_envelope({"id": "doc-1"}))


class TestTemplateResource:
    def test_list_hits_documented_endpoint_with_aliased_params(self) -> None:
        http = MockHttp()
        resource = TemplateResource(http, "acc")

        resource.list({"per_page": 20, "search": "nda"})

        assert http.last_url == "accounts/acc/templates"
        assert http.last_kwargs["params"] == {"per-page": 20, "search": "nda"}

    def test_get_hits_single_template_endpoint(self) -> None:
        http = MockHttp()
        resource = TemplateResource(http, "acc")

        resource.get("tpl-1")

        assert http.last_url == "accounts/acc/templates/tpl-1"

    def test_get_requires_template_id(self) -> None:
        resource = TemplateResource(MockHttp(), "acc")

        with pytest.raises(ValidationError):
            resource.get("")


class TestCreateFromTemplate:
    def test_create_from_template_posts_signers_and_options(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.create_from_template(
            "tpl-1",
            [{"role_id": "role-1", "id": "signer-1"}],
            {"name": "NDA - John Doe"},
        )

        assert http.last_url == "accounts/acc/templates/tpl-1/documents"
        assert http.last_kwargs["json"] == {
            "name": "NDA - John Doe",
            "signers": [{"role_id": "role-1", "id": "signer-1"}],
        }

    def test_create_from_template_requires_at_least_one_signer(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")

        with pytest.raises(ValidationError, match="signer"):
            resource.create_from_template("tpl-1", [])

    def test_create_from_template_signers_win_over_options_signers_key(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.create_from_template(
            "tpl-1",
            [{"role_id": "role-1", "id": "signer-1"}],
            {"signers": []},
        )

        assert http.last_kwargs["json"] == {"signers": [{"role_id": "role-1", "id": "signer-1"}]}

    def test_estimate_cost_from_template_posts_signers(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.estimate_cost_from_template("tpl-1", [{"role_id": "role-1"}])

        assert http.last_url == "accounts/acc/templates/tpl-1/documents/estimate-cost"
        assert http.last_kwargs["json"] == {"signers": [{"role_id": "role-1"}]}

    def test_estimate_cost_from_template_requires_at_least_one_signer(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")

        with pytest.raises(ValidationError, match="signer"):
            resource.estimate_cost_from_template("tpl-1", [])
