from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.signer_documents import SignerDocumentResource
from tests.conftest import MockResponse, make_envelope, make_response


class MockHttp:
    def __init__(self) -> None:
        self.last_url = ""
        self.last_kwargs: dict[str, object] = {}

    def get(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        if "/download/" in url:
            return MockResponse(content=b"pdf")
        return make_response(make_envelope({"id": "doc-1"} if url.endswith("/document") else []))

    def put(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope([]))


class TestSignerDocumentResource:
    def test_current_uses_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        resource.current("signer-1", "code")

        assert http.last_url == "signers/signer-1/document"
        assert http.last_kwargs["params"] == {"signer-access-code": "code"}

    def test_list_combines_filters_and_access_code(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        resource.list("signer-1", "code", {"per_page": 20})

        assert http.last_url == "signers/signer-1/documents"
        assert http.last_kwargs["params"] == {
            "per-page": 20,
            "signer-access-code": "code",
        }

    @pytest.mark.parametrize("params", [[], {"signer_access_code": "other"}])
    def test_list_rejects_invalid_or_ambiguous_params(self, params: object) -> None:
        with pytest.raises(ValidationError):
            SignerDocumentResource(object()).list(  # type: ignore[arg-type]
                "signer-1",
                "code",
                params,  # type: ignore[arg-type]
            )

    def test_search_hits_lightweight_endpoint_with_access_code(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        resource.search("signer-1", "code", "contract")

        assert http.last_url == "signers/signer-1/documents/search"
        assert http.last_kwargs["params"] == {
            "search": "contract",
            "signer-access-code": "code",
        }

    def test_search_omits_search_term_when_not_given(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        resource.search("signer-1", "code")

        assert http.last_kwargs["params"] == {"signer-access-code": "code"}

    def test_sign_and_decline_multiple_use_documented_endpoints(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        resource.sign_multiple(["doc-1"], "code")
        assert http.last_url == "signers/documents/sign-multiple"
        assert http.last_kwargs["json"] == {"document_ids": ["doc-1"]}

        resource.decline_multiple(["doc-1"], "No", "code")
        assert http.last_url == "signers/documents/decline-multiple"
        assert http.last_kwargs["json"] == {
            "document_ids": ["doc-1"],
            "decline_reason": "No",
        }

    def test_sign_multiple_requires_at_least_one_document_id(self) -> None:
        resource = SignerDocumentResource(MockHttp())
        with pytest.raises(ValidationError, match="document ID"):
            resource.sign_multiple([], "code")

    def test_sign_multiple_rejects_empty_document_id_in_list(self) -> None:
        resource = SignerDocumentResource(MockHttp())
        with pytest.raises(ValidationError, match="document ID"):
            resource.sign_multiple(["doc-1", ""], "code")

    def test_decline_multiple_requires_a_reason(self) -> None:
        resource = SignerDocumentResource(MockHttp())
        with pytest.raises(ValidationError, match="Decline reason"):
            resource.decline_multiple(["doc-1"], "", "code")

    def test_decline_multiple_requires_at_least_one_document_id(self) -> None:
        resource = SignerDocumentResource(MockHttp())
        with pytest.raises(ValidationError, match="document ID"):
            resource.decline_multiple([], "No", "code")

    def test_download_returns_binary_document(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        content = resource.download("signer-1", "doc-1", "code", "original")

        assert http.last_url == "signers/signer-1/documents/doc-1/download/original"
        assert content == b"pdf"

    def test_download_is_public_without_access_code(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        resource.download("signer-1", "doc-1", artifact_name="original")

        assert http.last_kwargs["params"] == {}

    def test_download_supports_pades_and_rejects_unknown_artifacts(self) -> None:
        http = MockHttp()
        resource = SignerDocumentResource(http)

        resource.download("signer-1", "doc-1", artifact_name="pades")
        assert http.last_url.endswith("/download/pades")
        with pytest.raises(ValidationError, match="Unknown document artifact"):
            resource.download("signer-1", "doc-1", artifact_name="unknown")  # type: ignore[arg-type]
