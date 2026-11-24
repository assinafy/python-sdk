from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from assinafy import ValidationError
from assinafy.resources.documents import DocumentResource
from tests.resources.test_envelopes import client_for


@pytest.mark.parametrize(
    ("method", "path", "data"),
    [
        ("watchers", "watchers", [{"id": "watcher", "email": "watcher@example.test"}]),
        ("signer_capacities", "signer-capacities", [{"signer_id": "s", "sign_as": "Witness"}]),
        (
            "notification_history",
            "notification-history",
            [
                {
                    "signer_id": "s",
                    "notification_history": [
                        {
                            "event": "signature_request",
                            "status": "opened",
                            "delivered_at": None,
                            "opened_at": "2026-11-24T12:00:00Z",
                        }
                    ],
                }
            ],
        ),
    ],
)
def test_document_lists_preserve_the_response(method: str, path: str, data: Any) -> None:
    requests: list[httpx.Request] = []
    with client_for(data, requests) as http:
        resource = DocumentResource(http)
        assert getattr(resource, method)("doc") == data
        with pytest.raises(ValidationError):
            getattr(resource, method)("../doc")
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == f"/v1/documents/doc/{path}"
    assert not requests[0].content


@pytest.mark.parametrize("ids", [[], ["s"], ["s"] * 11])
def test_replace_watchers_clears_or_deduplicates(ids: list[str]) -> None:
    requests: list[httpx.Request] = []
    with client_for([], requests) as http:
        assert DocumentResource(http).set_watchers("doc", ids) == []
    assert requests[0].method == "PUT"
    assert requests[0].url.path == "/v1/documents/doc/watchers"
    assert json.loads(requests[0].content) == {"watcher_ids": list(dict.fromkeys(ids))}


@pytest.mark.parametrize(
    "ids", [None, {}, "s", [""], [" "], [None], [["s"]], [str(i) for i in range(11)]]
)
def test_invalid_watchers_fail_before_io(ids: Any) -> None:
    requests: list[httpx.Request] = []
    with client_for([], requests) as http:
        with pytest.raises(ValidationError):
            DocumentResource(http).set_watchers("doc", ids)
    assert not requests
