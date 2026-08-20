from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.fields import FieldResource
from tests.conftest import make_envelope, make_response


class MockHttp:
    def __init__(self) -> None:
        self.last_url = ""
        self.last_kwargs: dict[str, object] = {}

    def post(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"id": "field-1"}))

    def get(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        data: object = [] if url == "field-types" or url.endswith("/fields") else {"id": "field-1"}
        return make_response(make_envelope(data))

    def put(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"id": "field-1"}))

    def delete(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope([]))


class TestFieldResource:
    def test_create_requires_type_and_name(self) -> None:
        resource = FieldResource(MockHttp(), "acc")

        with pytest.raises(ValidationError):
            resource.create({"type": "text"})

    def test_crud_methods_use_documented_field_endpoints(self) -> None:
        http = MockHttp()
        resource = FieldResource(http, "acc")

        resource.create({"type": "text", "name": "CPF"})
        assert http.last_url == "accounts/acc/fields"

        resource.get("field-1")
        assert http.last_url == "accounts/acc/fields/field-1"

        resource.update("field-1", {"name": "CPF updated"})
        assert http.last_url == "accounts/acc/fields/field-1"

        resource.delete("field-1")
        assert http.last_url == "accounts/acc/fields/field-1"

        resource.list({"include_standard": True})
        assert http.last_url == "accounts/acc/fields"
        assert http.last_kwargs["params"] == {"include_standard": True}

    def test_create_and_update_reject_undocumented_or_invalid_attributes(self) -> None:
        resource = FieldResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="mapping"):
            resource.create([])  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="Unknown field attributes"):
            resource.create({"type": "text", "name": "CPF", "is_visible": False})
        with pytest.raises(ValidationError, match="is_required must be boolean"):
            resource.create({"type": "text", "name": "CPF", "is_required": 1})
        with pytest.raises(ValidationError, match="Unknown field attributes"):
            resource.update("field-1", {"type": "date"})
        with pytest.raises(ValidationError, match="is_active must be boolean"):
            resource.update("field-1", {"is_active": 1})
        with pytest.raises(ValidationError, match="regex"):
            resource.update("field-1", {"regex": 1})

    def test_update_preserves_explicit_none_to_clear_regex(self) -> None:
        http = MockHttp()
        resource = FieldResource(http, "acc")

        resource.update("field-1", {"name": "CPF", "regex": None})

        assert http.last_kwargs["json"] == {"name": "CPF", "regex": None}

    def test_update_requires_at_least_one_field(self) -> None:
        resource = FieldResource(MockHttp(), "acc")

        with pytest.raises(ValidationError):
            resource.update("field-1", {})

    def test_validate_uses_hyphenated_signer_access_code_param(self) -> None:
        http = MockHttp()
        resource = FieldResource(http, "acc")

        resource.validate("field-1", "123", signer_access_code="code")

        assert http.last_url == "accounts/acc/fields/field-1/validate"
        assert http.last_kwargs["params"] == {"signer-access-code": "code"}
        assert http.last_kwargs["json"] == {"value": "123"}

    def test_validate_multiple_posts_documented_endpoint(self) -> None:
        class ListHttp(MockHttp):
            def post(self, url: str, **kwargs: object) -> object:
                self.last_url = url
                self.last_kwargs = dict(kwargs)
                return make_response(make_envelope([{"field_id": "field-1", "success": True}]))

        http = ListHttp()
        resource = FieldResource(http, "acc")

        result = resource.validate_multiple([{"field_id": "field-1", "value": "hi"}])

        assert http.last_url == "accounts/acc/fields/validate-multiple"
        assert http.last_kwargs["json"] == [{"field_id": "field-1", "value": "hi"}]
        assert result == [{"field_id": "field-1", "success": True}]

    def test_validate_multiple_requires_at_least_one_value(self) -> None:
        resource = FieldResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="field value"):
            resource.validate_multiple([])
        with pytest.raises(ValidationError, match="field value"):
            resource.validate_multiple([{"field_id": "field-1"}])

    def test_list_types_hits_global_endpoint(self) -> None:
        http = MockHttp()
        resource = FieldResource(http, "acc")

        resource.list_types()

        assert http.last_url == "field-types"
