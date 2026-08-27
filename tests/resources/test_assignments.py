from __future__ import annotations

import pytest

from assinafy.errors import ValidationError
from assinafy.resources.assignments import AssignmentResource, build_assignment_payload
from tests.conftest import make_envelope, make_response


class TestBuildAssignmentPayload:
    def test_normalises_string_signer_ids_into_id_objects(self) -> None:
        body = build_assignment_payload({"signers": ["a", "b"]})
        assert body == {"method": "virtual", "signers": [{"id": "a"}, {"id": "b"}]}

    def test_accepts_legacy_signer_ids_payload(self) -> None:
        assert build_assignment_payload({"signer_ids": ["a"]}) == {
            "method": "virtual",
            "signers": [{"id": "a"}],
        }

    def test_accepts_objects_with_id_or_signer_id(self) -> None:
        body = build_assignment_payload({"signers": [{"id": "a"}, {"signer_id": "b"}]})
        assert body["signers"] == [{"id": "a"}, {"id": "b"}]

    def test_forwards_step_for_sequential_signing(self) -> None:
        body = build_assignment_payload(
            {
                "signers": [
                    {"id": "a", "step": 1},
                    {"id": "b", "verification_method": "Email", "step": 2},
                ]
            }
        )
        assert body["signers"] == [
            {"id": "a", "step": 1},
            {"id": "b", "verification_method": "Email", "step": 2},
        ]

    @pytest.mark.parametrize(
        "signers",
        [
            [{"id": "a", "step": 1}, {"id": "b"}],
            [{"id": "a", "step": 1}, {"id": "b", "step": 3}],
            [
                {"id": "a", "step": 1, "verification_method": "DigitalCertificate"},
                {"id": "b", "step": 1},
            ],
        ],
    )
    def test_rejects_invalid_signing_order(self, signers: list[dict[str, object]]) -> None:
        with pytest.raises(ValidationError, match="step"):
            build_assignment_payload({"signers": signers})  # type: ignore[arg-type]

    def test_omits_step_when_not_provided(self) -> None:
        body = build_assignment_payload({"signers": [{"id": "a"}]})
        assert body["signers"] == [{"id": "a"}]
        assert "step" not in body["signers"][0]

    def test_allows_estimation_payloads_without_signer_ids(self) -> None:
        body = build_assignment_payload(
            {"signers": [{"verification_method": "Whatsapp"}, {}]},
            allow_signers_without_id=True,
        )
        assert body == {
            "method": "virtual",
            "signers": [{"verification_method": "Whatsapp"}, {}],
        }

    def test_includes_optional_fields_when_provided(self) -> None:
        body = build_assignment_payload(
            {
                "signers": ["a"],
                "message": "hi",
                "expires_at": "2024-12-31T23:59:59Z",
                "copy_receivers": ["c"],
            }
        )
        assert body["message"] == "hi"
        assert body["expires_at"] == "2024-12-31T23:59:59Z"
        assert body["copy_receivers"] == ["c"]

    def test_omits_missing_optional_fields(self) -> None:
        body = build_assignment_payload({"signers": ["a"]})
        assert "message" not in body
        assert "expires_at" not in body

    def test_throws_on_empty_signers_array(self) -> None:
        with pytest.raises(ValidationError):
            build_assignment_payload({"signers": []})

    def test_throws_on_invalid_signer_reference(self) -> None:
        with pytest.raises(ValidationError):
            build_assignment_payload({"signers": [{}]})

    @pytest.mark.parametrize(
        "payload",
        [
            {"signers": ["a"], "signer_ids": ["b"]},
            {"signers": [{"id": "a", "signer_id": "b"}]},
        ],
    )
    def test_rejects_ambiguous_signer_aliases(self, payload: dict[str, object]) -> None:
        with pytest.raises(ValidationError, match="not both"):
            build_assignment_payload(payload)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "expires_at",
        ["2030-12-31", "not-a-date", "2030-02-30T00:00:00Z", 1],
    )
    def test_rejects_invalid_expiration(self, expires_at: object) -> None:
        with pytest.raises(ValidationError, match="RFC 3339"):
            build_assignment_payload(  # type: ignore[arg-type]
                {"signers": ["a"], "expires_at": expires_at}
            )

    def test_collect_assignment_requires_signers_and_entries(self) -> None:
        with pytest.raises(ValidationError, match="signer"):
            build_assignment_payload(
                {
                    "method": "collect",
                    "entries": [{"page_id": "page-1", "fields": []}],
                }
            )
        with pytest.raises(ValidationError, match="entry"):
            build_assignment_payload({"method": "collect", "signers": ["signer-1"]})


class TestAssignmentResource:
    def test_create_posts_to_correct_url_with_normalised_body(self) -> None:
        captured_url: list[str] = []
        captured_body: list[object] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"id": "assignment-1"}))

        resource = AssignmentResource(MockHttp(), "acc")
        result = resource.create("doc-1", {"signers": ["s1", "s2"]})

        assert captured_url[0] == "documents/doc-1/assignments"
        assert captured_body[0] == {
            "method": "virtual",
            "signers": [{"id": "s1"}, {"id": "s2"}],
        }
        assert result["id"] == "assignment-1"

    def test_create_requires_signers_even_for_collect_method(self) -> None:
        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope({"id": "assignment-1"}))

        resource = AssignmentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError, match="signer"):
            resource.create(
                "doc-1",
                {"method": "collect", "entries": [{"page_id": "page-1", "fields": []}]},
            )

    def test_list_adds_default_account_context_for_sandbox_compatibility(self) -> None:
        captured_url: list[str] = []
        captured_params: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                captured_params.append(kwargs.get("params"))
                return make_response(make_envelope([{"id": "assignment-1"}]))

        resource = AssignmentResource(MockHttp(), "acc")
        result = resource.list({"per_page": 5})

        assert captured_url[0] == "assignments"
        assert captured_params[0] == {"per-page": 5, "accountId": "acc"}
        assert result["data"] == [{"id": "assignment-1"}]

    def test_list_allows_account_id_override(self) -> None:
        captured_params: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                captured_params.append(kwargs.get("params"))
                return make_response(make_envelope([]))

        resource = AssignmentResource(MockHttp(), "acc")
        resource.list(account_id="other-acc")

        assert captured_params[0] == {"accountId": "other-acc"}

    def test_list_works_without_an_sdk_account_id(self) -> None:
        captured_params: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                captured_params.append(kwargs.get("params"))
                return make_response(make_envelope([]))

        AssignmentResource(MockHttp()).list({"per_page": 5})
        assert captured_params[0] == {"per-page": 5}

    def test_list_rejects_non_mapping_params(self) -> None:
        with pytest.raises(ValidationError, match="mapping"):
            AssignmentResource(object()).list("bad")  # type: ignore[arg-type]

    def test_resend_notification_requires_all_three_ids(self) -> None:
        class MockHttp:
            def put(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope({}))

        resource = AssignmentResource(MockHttp(), "acc")
        with pytest.raises(ValidationError):
            resource.resend_notification("", "a", "s")
        with pytest.raises(ValidationError):
            resource.resend_notification("d", "", "s")
        with pytest.raises(ValidationError):
            resource.resend_notification("d", "a", "")

    def test_resend_notification_uses_documented_endpoint(self) -> None:
        captured_url: list[str] = []

        class MockHttp:
            def put(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                return make_response(make_envelope({}))

        AssignmentResource(MockHttp(), "acc").resend_notification("doc", "assignment", "signer")
        assert captured_url[0] == "documents/doc/assignments/assignment/signers/signer/resend"

    def test_estimate_cost_accepts_signer_descriptors_without_ids(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"total_credits": 0.45}))

        resource = AssignmentResource(MockHttp(), "acc")
        resource.estimate_cost("doc-1", {"signers": [{"verification_method": "Whatsapp"}]})

        assert captured_body[0] == {
            "method": "virtual",
            "signers": [{"verification_method": "Whatsapp"}],
        }

    def test_estimate_cost_accepts_legacy_ids_but_omits_them_from_wire_body(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({}))

        AssignmentResource(MockHttp(), "acc").estimate_cost(
            "doc", {"signers": [{"id": "signer-1"}]}
        )
        assert captured_body[0] == {"method": "virtual", "signers": [{}]}

    def test_estimate_cost_accepts_contract_valid_empty_payload(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({}))

        AssignmentResource(MockHttp(), "acc").estimate_cost("doc", {})
        assert captured_body[0] == {"method": "virtual"}

    @pytest.mark.parametrize(
        "payload",
        [
            {"message": "not supported for estimates"},
            {"expires_at": "2030-01-01T00:00:00Z"},
            {"copy_receivers": ["signer-1"]},
            {"signers": [{"step": 1}]},
        ],
    )
    def test_estimate_cost_rejects_create_only_fields(self, payload: dict[str, object]) -> None:
        resource = AssignmentResource(object(), "acc")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="estimate"):
            resource.estimate_cost("doc", payload)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "payload",
        [
            {"method": "paper", "signers": ["s"]},
            {"signers": "s"},
            {"signers": [{"id": "s", "verification_method": "SMS"}]},
            {"signers": [{"id": "s", "notification_methods": ["SMS"]}]},
            {"method": "collect", "entries": "entry"},
        ],
    )
    def test_assignment_payload_rejects_invalid_contract_values(
        self, payload: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            build_assignment_payload(payload)  # type: ignore[arg-type]

    def test_get_for_signer_maps_signer_access_code_query_param(self) -> None:
        captured_url: list[str] = []
        captured_params: list[object] = []

        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                captured_params.append(kwargs.get("params"))
                return make_response(make_envelope({"id": "doc-1"}))

        resource = AssignmentResource(MockHttp(), "acc")
        resource.get_for_signer("code", has_accepted_terms=True)

        assert captured_url[0] == "sign"
        assert captured_params[0] == {
            "signer-access-code": "code",
            "has_accepted_terms": True,
        }

        with pytest.raises(ValidationError, match="boolean"):
            resource.get_for_signer("code", has_accepted_terms=1)  # type: ignore[arg-type]

    def test_sign_and_decline_use_signer_assignment_endpoints(self) -> None:
        captured_calls: list[tuple[str, object, object]] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_calls.append((url, kwargs.get("params"), kwargs.get("json")))
                return make_response(make_envelope({"ok": True}))

            def put(self, url: str, **kwargs: object) -> object:
                captured_calls.append((url, kwargs.get("params"), kwargs.get("json")))
                return make_response(make_envelope([]))

        resource = AssignmentResource(MockHttp(), "acc")
        entry = {
            "itemId": "item-1",
            "fieldId": "field-1",
            "pageId": "page-1",
            "value": "John Doe",
        }
        resource.sign("doc-1", "assignment-1", [entry], "code")
        resource.decline("doc-1", "assignment-1", "No", "code")

        assert captured_calls[0] == (
            "documents/doc-1/assignments/assignment-1",
            {"signer-access-code": "code"},
            [entry],
        )
        assert captured_calls[1] == (
            "documents/doc-1/assignments/assignment-1/reject",
            {"signer-access-code": "code"},
            {"decline_reason": "No"},
        )

    def test_sign_allows_documented_empty_string_value(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({}))

        entry = {"itemId": "item", "fieldId": "field", "pageId": "page", "value": ""}
        AssignmentResource(MockHttp(), "acc").sign("doc", "assignment", [entry], "code")
        assert captured_body == [[entry]]

    def test_sign_sends_empty_array_for_virtual_assignment(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({}))

        AssignmentResource(MockHttp(), "acc").sign("doc", "assignment", [], "code")
        assert captured_body == [[]]

    def test_sign_rejects_incomplete_entries(self) -> None:
        resource = AssignmentResource(object(), "acc")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="entry"):
            resource.sign("doc", "assignment", [{"itemId": "item"}], "code")

    def test_whatsapp_notifications_returns_list(self) -> None:
        class MockHttp:
            def get(self, url: str, **kwargs: object) -> object:
                return make_response(make_envelope([{"sent_at": 1}]))

        resource = AssignmentResource(MockHttp(), "acc")
        assert resource.whatsapp_notifications("doc-1", "assignment-1") == [{"sent_at": 1}]

    def test_reset_expiration_sends_iso_timestamp(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def put(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"id": "a"}))

        resource = AssignmentResource(MockHttp(), "acc")
        resource.reset_expiration("doc-1", "a", "2030-12-31T00:00:00Z")
        assert captured_body[0] == {"expires_at": "2030-12-31T00:00:00Z"}

    def test_reset_expiration_allows_none_to_clear(self) -> None:
        captured_body: list[object] = []

        class MockHttp:
            def put(self, url: str, **kwargs: object) -> object:
                captured_body.append(kwargs.get("json"))
                return make_response(make_envelope({"id": "a", "expires_at": None}))

        resource = AssignmentResource(MockHttp(), "acc")
        resource.reset_expiration("doc-1", "a", None)
        assert captured_body[0] == {"expires_at": None}

    @pytest.mark.parametrize("expires_at", ["", "2030-12-31", 1])
    def test_reset_expiration_rejects_invalid_value(self, expires_at: object) -> None:
        resource = AssignmentResource(object(), "acc")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="expires_at"):
            resource.reset_expiration("doc-1", "a", expires_at)  # type: ignore[arg-type]

    def test_estimate_resend_cost_posts_to_documented_endpoint(self) -> None:
        captured_url: list[str] = []

        class MockHttp:
            def post(self, url: str, **kwargs: object) -> object:
                captured_url.append(url)
                return make_response(make_envelope({"total": 0}))

        resource = AssignmentResource(MockHttp(), "acc")
        result = resource.estimate_resend_cost("doc-1", "a", "s")

        assert captured_url[0] == ("documents/doc-1/assignments/a/signers/s/estimate-resend-cost")
        assert result == {"total": 0}
