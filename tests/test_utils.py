from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from assinafy.errors import ApiError, AssinafyError, NetworkError, ValidationError
from assinafy.utils import clean_params, handle_assinafy_response, to_sdk_error


class TestHandleAssinafyResponse:
    def test_returns_data_on_2xx_envelope(self) -> None:
        result = handle_assinafy_response({"status": 200, "data": {"id": "123"}})
        assert result == {"id": "123"}

    def test_throws_api_error_on_non_2xx_envelope(self) -> None:
        with pytest.raises(ApiError):
            handle_assinafy_response({"status": 400, "message": "Bad", "data": {}})

    def test_passes_through_when_no_envelope_present(self) -> None:
        result = handle_assinafy_response({"foo": "bar"})
        assert result == {"foo": "bar"}

    def test_passes_through_list_response(self) -> None:
        result = handle_assinafy_response([{"id": "1"}, {"id": "2"}])
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_raises_api_error_with_message_from_response(self) -> None:
        with pytest.raises(ApiError) as exc_info:
            handle_assinafy_response({"status": 422, "message": "Unprocessable", "data": {}})
        assert "Unprocessable" in str(exc_info.value)


class TestToSdkError:
    def test_passes_assinafy_error_through_unchanged(self) -> None:
        original = ValidationError("bad", {"field": "x"})
        assert to_sdk_error(original, "ignored") is original

    def test_wraps_plain_errors_in_assinafy_error(self) -> None:
        result = to_sdk_error(Exception("boom"), "failed")
        assert isinstance(result, AssinafyError)
        assert "failed" in str(result)
        assert "boom" in str(result)

    def test_returns_network_error_for_httpx_request_errors(self) -> None:
        fake = httpx.ConnectError("connect ECONNREFUSED")
        result = to_sdk_error(fake, "upload")
        assert isinstance(result, NetworkError)

    def test_converts_http_status_error_to_api_error(self) -> None:
        mock_request = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "Not found"}
        error = httpx.HTTPStatusError("404", request=mock_request, response=mock_response)
        result = to_sdk_error(error, "fetch")
        assert isinstance(result, ApiError)
        assert result.status_code == 404

    def test_http_status_error_uses_error_or_fallback_message(self) -> None:
        request = httpx.Request("GET", "https://example.test")
        for body, expected in [({"error": "Denied"}, "Denied"), ([], "API request failed")]:
            response = httpx.Response(403, request=request, json=body)
            result = to_sdk_error(
                httpx.HTTPStatusError("403", request=request, response=response), "fetch"
            )
            assert isinstance(result, ApiError)
            assert str(result) == expected


class TestCleanParams:
    def test_drops_none_values(self) -> None:
        result = clean_params({"a": 1, "b": None, "c": None, "d": "x"})
        assert result == {"a": 1, "d": "x"}

    def test_keeps_falsy_non_none_values(self) -> None:
        result = clean_params({"a": 0, "b": False, "c": "", "d": None})
        assert result == {"a": 0, "b": False, "c": ""}

    def test_returns_empty_dict_for_all_none(self) -> None:
        assert clean_params({"a": None, "b": None}) == {}

    def test_applies_aliases_after_dropping_none_values(self) -> None:
        result = clean_params(
            {"per_page": 20, "signer_access_code": "abc", "empty": None},
            {"per_page": "per-page", "signer_access_code": "signer-access-code"},
        )
        assert result == {"per-page": 20, "signer-access-code": "abc"}

    def test_rejects_conflicting_aliases(self) -> None:
        with pytest.raises(ValidationError, match="Conflicting"):
            clean_params({"per_page": 20, "per-page": 50}, {"per_page": "per-page"})
