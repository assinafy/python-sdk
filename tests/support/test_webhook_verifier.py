from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from assinafy.support.webhook_verifier import WebhookVerifier


def _generate_signature(secret: str, payload: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# A real documented webhook envelope (signer_signed_document), per the
# Payload Reference at https://api.assinafy.com.br/v1/docs.
_REAL_EVENT = {
    "id": 7,
    "event": "signer_signed_document",
    "message": "Signer 1 signed",
    "payload": {"signer_full_name": "Signer 1"},
    "origin": {"ip": "172.19.0.1", "user-agent": "Mozilla/5.0"},
    "created_at": 1705312200,
    "subject": {"id": "customid1", "full_name": "Signer 1", "type": "Signer"},
    "object": {"id": "doc2", "name": "2.pdf", "status": "partially_signed", "type": "Document"},
    "account_id": "1a",
}


class TestWebhookVerifier:
    def setup_method(self) -> None:
        self.secret = "super-secret"
        self.payload = json.dumps(_REAL_EVENT)
        self.signature = _generate_signature(self.secret, self.payload)

    def test_verify_returns_true_for_matching_hmac_sha256_signature(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.verify(self.payload, self.signature) is True

    def test_verify_returns_false_for_mismatched_signature(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.verify(self.payload, "deadbeef") is False

    def test_verify_returns_false_when_no_secret_is_configured(self) -> None:
        verifier = WebhookVerifier(None)
        assert verifier.verify(self.payload, self.signature) is False

    def test_verify_accepts_bytes_payload(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.verify(self.payload.encode("utf-8"), self.signature) is True

    def test_verify_returns_false_for_empty_signature(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.verify(self.payload, "") is False

    def test_extract_event_parses_json_payloads(self) -> None:
        verifier = WebhookVerifier(self.secret)
        result = verifier.extract_event(self.payload)
        assert result == _REAL_EVENT

    def test_extract_event_parses_bytes_payload(self) -> None:
        verifier = WebhookVerifier(self.secret)
        result = verifier.extract_event(self.payload.encode("utf-8"))
        assert result == _REAL_EVENT

    def test_extract_event_returns_none_on_malformed_payload(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.extract_event("{not json") is None

    def test_get_event_type_returns_documented_event_field(self) -> None:
        verifier = WebhookVerifier(self.secret)
        event = verifier.extract_event(self.payload)
        assert verifier.get_event_type(event) == "signer_signed_document"

    def test_get_event_type_returns_none_for_none_event(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.get_event_type(None) is None

    def test_get_event_payload_returns_event_specific_params(self) -> None:
        verifier = WebhookVerifier(self.secret)
        event = verifier.extract_event(self.payload)
        assert verifier.get_event_payload(event) == {"signer_full_name": "Signer 1"}

    def test_get_event_payload_returns_empty_dict_when_payload_null(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.get_event_payload({"event": "document_ready", "payload": None}) == {}
        assert verifier.get_event_payload(None) == {}

    def test_get_event_subject_returns_actor_entity(self) -> None:
        verifier = WebhookVerifier(self.secret)
        event = verifier.extract_event(self.payload)
        subject = verifier.get_event_subject(event)
        assert subject["id"] == "customid1"
        assert subject["type"] == "Signer"

    def test_get_event_object_returns_target_entity(self) -> None:
        verifier = WebhookVerifier(self.secret)
        event = verifier.extract_event(self.payload)
        obj = verifier.get_event_object(event)
        assert obj["id"] == "doc2"
        assert obj["type"] == "Document"

    def test_get_event_data_is_alias_of_get_event_object(self) -> None:
        verifier = WebhookVerifier(self.secret)
        event = verifier.extract_event(self.payload)
        assert verifier.get_event_data(event) == verifier.get_event_object(event)

    def test_get_event_object_and_subject_return_empty_dict_for_none_event(self) -> None:
        verifier = WebhookVerifier(self.secret)
        assert verifier.get_event_object(None) == {}
        assert verifier.get_event_subject(None) == {}


# Reference vector from the Standard Webhooks specification test suite.
_SW_SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
_SW_BODY = b'{"test": 2432232314}'
_SW_HEADERS = {
    "webhook-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
    "webhook-timestamp": "1614265330",
    "webhook-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
}


class TestVerifyDelivery:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("assinafy.support.webhook_verifier.time.time", lambda: 1614265330 + 10)

    def test_accepts_reference_signature(self) -> None:
        assert WebhookVerifier(_SW_SECRET).verify_delivery(_SW_BODY, _SW_HEADERS)
        assert WebhookVerifier(_SW_SECRET).verify_delivery(_SW_BODY.decode(), _SW_HEADERS)

    def test_header_names_are_case_insensitive_and_any_v1_entry_matches(self) -> None:
        headers = {k.title(): v for k, v in _SW_HEADERS.items()}
        headers["Webhook-Signature"] = "v1,bm90LWl0 v2,ignored " + _SW_HEADERS["webhook-signature"]
        assert WebhookVerifier(_SW_SECRET).verify_delivery(_SW_BODY, headers)

    @pytest.mark.parametrize(
        "change",
        [
            {"webhook-signature": "v1,bm90LWl0"},
            {"webhook-signature": "v2," + _SW_HEADERS["webhook-signature"][3:]},
            {"webhook-signature": "v1,ção"},
            {"webhook-id": "msg_other"},
            {"webhook-timestamp": "1614265331"},
            {"webhook-timestamp": "not-a-number"},
            {"webhook-id": ""},
        ],
    )
    def test_rejects_altered_or_malformed_headers(self, change: dict[str, str]) -> None:
        assert not WebhookVerifier(_SW_SECRET).verify_delivery(_SW_BODY, {**_SW_HEADERS, **change})

    def test_rejects_altered_body_missing_header_and_bad_secret(self) -> None:
        assert not WebhookVerifier(_SW_SECRET).verify_delivery(b'{"test": 1}', _SW_HEADERS)
        missing = {k: v for k, v in _SW_HEADERS.items() if k != "webhook-signature"}
        assert not WebhookVerifier(_SW_SECRET).verify_delivery(_SW_BODY, missing)
        assert not WebhookVerifier("whsec_***").verify_delivery(_SW_BODY, _SW_HEADERS)
        assert not WebhookVerifier("whsec_").verify_delivery(_SW_BODY, _SW_HEADERS)
        assert not WebhookVerifier().verify_delivery(_SW_BODY, _SW_HEADERS)

    def test_rejects_timestamps_outside_tolerance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        verifier = WebhookVerifier(_SW_SECRET)
        monkeypatch.setattr("assinafy.support.webhook_verifier.time.time", lambda: 1614265330 + 301)
        assert not verifier.verify_delivery(_SW_BODY, _SW_HEADERS)
        assert verifier.verify_delivery(_SW_BODY, _SW_HEADERS, tolerance=600)

    @pytest.mark.parametrize("tolerance", [0, -1, float("inf"), float("nan"), True])
    def test_rejects_invalid_tolerance(self, tolerance: float) -> None:
        with pytest.raises(ValueError):
            WebhookVerifier(_SW_SECRET).verify_delivery(_SW_BODY, _SW_HEADERS, tolerance=tolerance)

    def test_rejects_future_timestamps_outside_tolerance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        verifier = WebhookVerifier(_SW_SECRET)
        monkeypatch.setattr("assinafy.support.webhook_verifier.time.time", lambda: 1614265330 - 301)
        assert not verifier.verify_delivery(_SW_BODY, _SW_HEADERS)
