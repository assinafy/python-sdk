from __future__ import annotations

import httpx
import pytest

from assinafy.errors import ApiError, ValidationError
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

    def patch(self, url: str, **kwargs: object) -> object:
        self.last_url = url
        self.last_kwargs = dict(kwargs)
        return make_response(make_envelope({"id": "doc-1", "name": "New name.pdf"}))


class TestDocumentResource:
    def test_upload_posts_only_multipart_file_to_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.upload({"buffer": b"%PDF-1.4", "file_name": "contract.pdf"})

        assert http.last_url == "accounts/acc/documents"
        assert "files" in http.last_kwargs
        assert "data" not in http.last_kwargs

    def test_upload_allows_account_id_override(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "default-acc")

        resource.upload({"buffer": b"%PDF-1.4", "file_name": "contract.pdf"}, "other-acc")

        assert http.last_url == "accounts/other-acc/documents"

    def test_upload_rejects_non_pdf_extension(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="PDF"):
            resource.upload({"buffer": b"hello", "file_name": "contract.txt"})

    def test_upload_rejects_empty_buffer(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="empty"):
            resource.upload({"buffer": b"", "file_name": "contract.pdf"})

    def test_upload_rejects_oversized_buffer(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="25MB"):
            resource.upload({"buffer": b"x" * (25 * 1024 * 1024 + 1), "file_name": "big.pdf"})

    def test_upload_requires_file_name_for_buffer_source(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="file_name"):
            resource.upload({"buffer": b"%PDF-1.4"})

    def test_upload_requires_file_path_or_buffer(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="file_path"):
            resource.upload({})

    def test_upload_raises_when_response_has_no_id(self) -> None:
        class NoIdHttp(MockHttp):
            def post(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope({}))

        resource = DocumentResource(NoIdHttp(), "acc")
        with pytest.raises(ValidationError, match="no document ID"):
            resource.upload({"buffer": b"%PDF-1.4", "file_name": "contract.pdf"})

    def test_delete_hits_documented_endpoint(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.delete("doc-1")

        assert http.last_url == "documents/doc-1"

    def test_delete_requires_document_id(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="Document ID"):
            resource.delete("")

    def test_list_maps_per_page_to_documented_query_param(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.list({"page": 1, "per_page": 20})

        assert http.last_kwargs["params"] == {"page": 1, "per-page": 20}

    def test_rename_patches_document_with_name_body(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        result = resource.rename("doc-1", "New name.pdf")

        assert http.last_url == "documents/doc-1"
        assert http.last_kwargs["json"] == {"name": "New name.pdf"}
        assert result["name"] == "New name.pdf"

    def test_rename_requires_non_empty_name(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")

        with pytest.raises(ValidationError, match="Document name is required"):
            resource.rename("doc-1", "")

    def test_rename_rejects_name_over_255_chars(self) -> None:
        resource = DocumentResource(MockHttp(), "acc")

        with pytest.raises(ValidationError, match="255 characters"):
            resource.rename("doc-1", "x" * 256)

    def test_search_hits_lightweight_endpoint_with_aliased_params(self) -> None:
        http = MockHttp()
        resource = DocumentResource(http, "acc")

        resource.search({"search": "nda", "per_page": 5})

        assert http.last_url == "accounts/acc/documents/search"
        assert http.last_kwargs["params"] == {"search": "nda", "per-page": 5}

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
                if "/download/" in url or url.endswith("/thumbnail") or "/pages/" in url:
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


class TestWaitUntilReady:
    def test_returns_document_once_ready(self) -> None:
        class ReadyHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope({"id": "doc-1", "status": "metadata_ready"}))

        resource = DocumentResource(ReadyHttp(), "acc")
        result = resource.wait_until_ready("doc-1", timeout=1.0, poll_interval=0.01)
        assert result["status"] == "metadata_ready"

    def test_raises_on_terminal_failure_status(self) -> None:
        class FailedHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope({"id": "doc-1", "status": "failed"}))

        resource = DocumentResource(FailedHttp(), "acc")
        with pytest.raises(ValidationError, match="failed"):
            resource.wait_until_ready("doc-1", timeout=1.0, poll_interval=0.01)

    def test_raises_timeout_when_status_never_settles(self) -> None:
        class PendingHttp(MockHttp):
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(
                    make_envelope({"id": "doc-1", "status": "metadata_processing"})
                )

        resource = DocumentResource(PendingHttp(), "acc")
        with pytest.raises(ValidationError, match="Timeout"):
            resource.wait_until_ready("doc-1", timeout=0.05, poll_interval=0.01)

    def test_retries_through_transient_errors_then_succeeds(self) -> None:
        class FlakyHttp(MockHttp):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def get(self, url: str, **kwargs: object) -> object:
                self.calls += 1
                if self.calls < 2:
                    raise RuntimeError("transient network blip")
                return make_response(make_envelope({"id": "doc-1", "status": "metadata_ready"}))

        http = FlakyHttp()
        resource = DocumentResource(http, "acc")
        result = resource.wait_until_ready("doc-1", timeout=1.0, poll_interval=0.01)
        assert result["status"] == "metadata_ready"
        assert http.calls >= 2

    def test_raises_immediately_on_404_instead_of_retrying_until_timeout(self) -> None:
        class NotFoundResponse(MockResponse):
            def raise_for_status(self) -> None:
                raise httpx.HTTPStatusError(
                    "404",
                    request=httpx.Request("GET", "https://x/documents/doc-1"),
                    response=httpx.Response(404, json={"status": 404, "message": "Not found"}),
                )

        class NotFoundHttp(MockHttp):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def get(self, url: str, **kwargs: object) -> object:
                self.calls += 1
                return NotFoundResponse(json_data={"status": 404, "message": "Not found"})

        http = NotFoundHttp()
        resource = DocumentResource(http, "acc")
        with pytest.raises(ApiError) as exc_info:
            resource.wait_until_ready("doc-1", timeout=1.0, poll_interval=0.01)
        assert exc_info.value.status_code == 404
        assert http.calls == 1
