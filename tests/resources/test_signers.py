from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.signers import SignerResource
from tests.conftest import MockResponse, make_envelope, make_response


class MockHttp:
    def __init__(self) -> None:
        self.last_url = ""
        self.last_kwargs: dict[str, object] = {}
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        self.calls.append(("POST", url, dict(kwargs)))
        return make_response(make_envelope({"id": "123"}))

    def get(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        self.calls.append(("GET", url, dict(kwargs)))
        return make_response(make_envelope([] if url.endswith("/signers") else {"id": "signer-1"}))

    def put(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        self.calls.append(("PUT", url, dict(kwargs)))
        return make_response(make_envelope({"id": "123"}))

    def delete(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        self.calls.append(("DELETE", url, dict(kwargs)))
        return make_response(status_code=200)


class TestSignerResource:
    def test_create_requires_full_name(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="full_name is required"):
            resource.create({"email": "test@example.com"})

    def test_create_rejects_invalid_email(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Invalid email"):
            resource.create({"full_name": "Test", "email": "not-an-email"})

    def test_create_rejects_unknown_or_invalid_fields(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Unknown signer fields"):
            resource.create({"full_name": "Test", "government_id": "123"})
        with pytest.raises(ValidationError, match="full_name"):
            resource.create({"full_name": 123})  # type: ignore[dict-item]
        with pytest.raises(ValidationError, match="whatsapp_phone_number"):
            resource.create({"full_name": "Test", "whatsapp_phone_number": 123})

    def test_create_requires_account_id(self) -> None:
        resource = SignerResource(MockHttp())
        with pytest.raises(ValidationError, match="Account ID"):
            resource.create({"full_name": "Test", "email": "test@example.com"})

    def test_update_requires_signer_id(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Signer ID"):
            resource.update("", {"full_name": "Test"})

    def test_update_requires_at_least_one_field(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="At least one signer field"):
            resource.update("signer-1", {})

    def test_delete_requires_signer_id(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Signer ID"):
            resource.delete("")

    def test_delete_hits_documented_endpoint(self) -> None:
        http = MockHttp()
        SignerResource(http, "acc").delete("signer-1")
        assert http.last_url == "accounts/acc/signers/signer-1"

    def test_get_fetches_single_signer_by_id(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.get("signer-1")

        assert http.last_url == "accounts/acc/signers/signer-1"

    def test_get_requires_signer_id(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Signer ID"):
            resource.get("")

    def test_create_posts_only_documented_fields(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.create(
            {
                "full_name": "John",
                "email": "john@example.com",
                "whatsapp_phone_number": "+5548999990000",
            }
        )

        assert http.last_url == "accounts/acc/signers"
        assert http.last_kwargs["json"] == {
            "full_name": "John",
            "email": "john@example.com",
            "whatsapp_phone_number": "+5548999990000",
        }

    def test_create_does_not_search_before_posting(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.create({"full_name": "John", "email": "john@example.com"})

        methods = [method for method, _, _ in http.calls]
        assert methods == ["POST"]

    def test_create_allows_whatsapp_only_signer(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.create({"full_name": "John", "whatsapp_phone_number": "+5548999990000"})

        assert http.last_kwargs["json"] == {
            "full_name": "John",
            "whatsapp_phone_number": "+5548999990000",
        }

    def test_uses_custom_account_id_when_provided(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "default-account")

        resource.create({"full_name": "John", "email": "john@example.com"}, "custom-account")

        assert http.last_url == "accounts/custom-account/signers"

    def test_list_passes_search_via_params(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.list({"search": "john@example.com"})

        assert http.last_url == "accounts/acc/signers"
        assert http.last_kwargs["params"] == {"search": "john@example.com"}

    def test_list_maps_per_page_alias(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.list({"per_page": 50})

        assert http.last_kwargs["params"] == {"per-page": 50}

    def test_list_returns_meta_parsed_from_pagination_headers(self) -> None:
        class TrackingHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(
                    make_envelope([]),
                    headers={
                        "x-pagination-current-page": "2",
                        "x-pagination-per-page": "20",
                        "x-pagination-total-count": "45",
                        "x-pagination-page-count": "3",
                    },
                )

        resource = SignerResource(TrackingHttp(), "acc")
        result = resource.list({"page": 2})
        assert result["meta"] == {
            "current_page": 2,
            "per_page": 20,
            "total": 45,
            "last_page": 3,
        }

    def test_find_by_email_returns_none_when_no_match(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        assert resource.find_by_email("nobody@example.com") is None

    def test_find_by_email_returns_matching_signer_case_insensitive(self) -> None:
        class TrackingHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(
                    make_envelope([{"id": "1", "full_name": "John", "email": "JOHN@EXAMPLE.COM"}])
                )

        resource = SignerResource(TrackingHttp(), "acc")
        result = resource.find_by_email("john@example.com")
        assert result is not None
        assert result["id"] == "1"

    def test_get_self_uses_signer_access_code_query_alias(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.get_self("code")

        assert http.last_url == "signers/self"
        assert http.last_kwargs["params"] == {"signer-access-code": "code"}

    def test_accept_terms_sends_access_code_in_query(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.accept_terms("code")

        assert http.last_url == "signers/accept-terms"
        assert http.last_kwargs["params"] == {"signer-access-code": "code"}
        assert "json" not in http.last_kwargs

    def test_verify_email_posts_documented_hyphenated_body(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.verify_email("code", "123456")

        assert http.last_url == "verify"
        assert http.last_kwargs["params"] == {"signer-access-code": "code"}
        assert http.last_kwargs["json"] == {"verification-code": "123456"}

        resource.verify_code("code", "654321")
        assert http.last_kwargs["json"] == {"verification-code": "654321"}

    def test_update_forwards_government_id(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.update("signer-1", {"government_id": "39053344705"})

        assert http.last_kwargs["json"] == {"government_id": "39053344705"}

    def test_confirm_data_uses_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.confirm_data(
            "doc-1",
            "code",
            {"email": "john@example.com", "has_accepted_terms": True},
        )

        assert http.last_url == "documents/doc-1/signers/confirm-data"
        assert http.last_kwargs["params"] == {"signer-access-code": "code"}
        assert http.last_kwargs["json"] == {
            "email": "john@example.com",
            "has_accepted_terms": True,
        }

    def test_upload_signature_sends_query_and_content_type(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.upload_signature("code", b"binary-png")

        assert http.last_url == "signature"
        assert http.last_kwargs["params"] == {
            "signer-access-code": "code",
            "type": "signature",
        }
        assert http.last_kwargs["content"] == b"binary-png"
        assert http.last_kwargs["headers"] == {"Content-Type": "image/png"}

    def test_upload_signature_forwards_reuse_flag(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.upload_signature("code", b"binary-png", reuse=True)

        assert http.last_kwargs["params"] == {
            "signer-access-code": "code",
            "type": "signature",
            "reuse": True,
        }

    def test_upload_signature_omits_reuse_when_not_given(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.upload_signature("code", b"binary-png")

        assert "reuse" not in http.last_kwargs["params"]

    def test_confirm_data_accepts_full_name_and_government_id(self) -> None:
        http = MockHttp()
        resource = SignerResource(http, "acc")

        resource.confirm_data("doc-1", "code", {"full_name": "John Doe", "government_id": "12345"})

        assert http.last_kwargs["json"] == {
            "full_name": "John Doe",
            "government_id": "12345",
        }

    def test_confirm_data_requires_at_least_one_field(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="signer-data field"):
            resource.confirm_data("doc-1", "code", {})

    def test_mapping_and_binary_inputs_raise_typed_validation_errors(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="mapping"):
            resource.create([])  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="mapping"):
            resource.confirm_data("doc-1", "code", [])  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="content"):
            resource.upload_signature("code", "not-bytes")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="reuse"):
            resource.upload_signature("code", b"binary", reuse=1)  # type: ignore[arg-type]

    def test_upload_signature_rejects_invalid_type(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Signature type"):
            resource.upload_signature("code", b"binary", signature_type="bad")

    def test_upload_signature_rejects_unpublished_media_type(self) -> None:
        resource = SignerResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="content type"):
            resource.upload_signature("code", b"binary", content_type="application/pdf")

    def test_download_signature_uses_query_alias(self) -> None:
        class BinaryHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                self.last_url = url
                self.last_kwargs = dict(kwargs)
                return MockResponse(content=b"png-bytes")

        http = BinaryHttp()
        resource = SignerResource(http, "acc")
        result = resource.download_signature("code", "initial")

        assert http.last_url == "signature/initial"
        assert http.last_kwargs["params"] == {"signer-access-code": "code"}
        assert result == b"png-bytes"
