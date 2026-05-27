from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.documents import DocumentResource
from tests.conftest import MockResponse, make_envelope, make_response


class MockHttp:
    def __init__(self) -> None:
        self.last_url = ""
        self.last_kwargs: dict[str, object] = {}

    def post(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"id": "doc-1"}))

    def get(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope([]))

    def put(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"ok": True}))

    def delete(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"detached": True}))


class TestDocumentResource:
    def test_upload_posts_only_multipart_file_to_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.upload({"buffer": b"%PDF-1.4", "file_name": "contract.pdf"})

        assert http.last_url == "accounts/acc/documents"
        assert "files" in http.last_kwargs
        assert "data" not in http.last_kwargs

    def test_list_maps_per_page_to_documented_query_param(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.list({"page": 1, "per_page": 20})

        assert http.last_kwargs["params"] == {"page": 1, "per-page": 20}

    def test_statuses_hits_global_endpoint(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.statuses()

        assert http.last_url == "documents/statuses"

    def test_public_info_and_send_token_use_public_endpoints(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.public_info("doc-1")
        assert http.last_url == "public/documents/doc-1"

        resource.send_token("doc-1", "signer@example.com", "email")
        assert http.last_url == "public/documents/doc-1/send-token"
        assert http.last_kwargs["json"] == {
            "recipient": "signer@example.com",
            "channel": "email",
        }

    def test_document_tag_methods_use_documented_endpoints(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.list_tags("doc-1")
        assert http.last_url == "accounts/acc/documents/doc-1/tags"

        resource.replace_tags("doc-1", [])
        assert http.last_url == "accounts/acc/documents/doc-1/tags"
        assert http.last_kwargs["json"] == {"tags": []}

        resource.append_tags("doc-1", ["Contracts"])
        assert http.last_url == "accounts/acc/documents/doc-1/tags"
        assert http.last_kwargs["json"] == {"tags": ["Contracts"]}

        resource.detach_tag("doc-1", "tag-1")
        assert http.last_url == "accounts/acc/documents/doc-1/tags/tag-1"

    def test_document_tag_append_requires_at_least_one_tag(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")

        with pytest.raises(ValidationError, match="At least one tag name"):
            resource.append_tags("doc-1", [])

    def test_document_binary_and_detail_methods_use_documented_endpoints(self) -> None:
        class BinaryHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                self.last_url = url
                self.last_kwargs = dict(kwargs)
                if (
                    "/download/" in url
                    or url.endswith("/thumbnail")
                    or "/pages/" in url
                ):
                    return MockResponse(content=b"pdf")
                return make_response(make_envelope({"id": "doc-1"}))

        http = BinaryHttp()
        resource = DocumentResource(http, "acc")

        resource.get("doc-1")
        assert http.last_url == "documents/doc-1"

        assert resource.download("doc-1", "original") == b"pdf"
        assert http.last_url == "documents/doc-1/download/original"

        assert resource.thumbnail("doc-1") == b"pdf"
        assert http.last_url == "documents/doc-1/thumbnail"

        assert resource.download_page("doc-1", "page-1") == b"pdf"
        assert http.last_url == "documents/doc-1/pages/page-1/download"

        resource.activities("doc-1")
        assert http.last_url == "documents/doc-1/activities"

        resource.verify("hash-1")
        assert http.last_url == "documents/hash-1/verify"
