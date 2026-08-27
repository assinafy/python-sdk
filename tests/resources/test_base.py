from __future__ import annotations

import httpx
import pytest

from assinafy.errors import AssinafyError, ValidationError
from assinafy.resources.documents import DocumentResource


@pytest.mark.parametrize("value", ["../users/self", "a/b", "a?admin=true", "a#x", "a%2Fb", "."])
def test_path_ids_reject_path_and_query_injection(value: str) -> None:
    client = httpx.Client(
        base_url="https://example.test/v1/",
        transport=httpx.MockTransport(lambda request: pytest.fail("request must not be sent")),
    )
    try:
        with pytest.raises(ValidationError, match="invalid path characters"):
            DocumentResource(client, "acc").get(value)
    finally:
        client.close()


def test_path_ids_reject_non_strings() -> None:
    client = httpx.Client(base_url="https://example.test/v1/")
    try:
        with pytest.raises(ValidationError, match="Document ID is required"):
            DocumentResource(client, "acc").get(123)  # type: ignore[arg-type]
    finally:
        client.close()


def test_required_ids_reject_whitespace_only_strings() -> None:
    client = httpx.Client(base_url="https://example.test/v1/")
    try:
        with pytest.raises(ValidationError, match="Document ID is required"):
            DocumentResource(client, "acc").get("   ")
    finally:
        client.close()


def test_object_and_list_response_helpers_reject_wrong_shapes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        data: object = [] if request.url.path.endswith("/doc-1") else {"not": "a list"}
        return httpx.Response(200, json={"status": 200, "data": data})

    client = httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(handler)
    )
    resource = DocumentResource(client, "acc")
    try:
        with pytest.raises(AssinafyError, match="non-object"):
            resource.get("doc-1")
        with pytest.raises(AssinafyError, match="non-list"):
            resource.statuses()
    finally:
        client.close()
