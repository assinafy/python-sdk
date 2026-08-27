from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from assinafy import ApiError


def _load_live_smoke() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "live_smoke.py"
    spec = importlib.util.spec_from_file_location("assinafy_live_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live_smoke = _load_live_smoke()


class FakeResource:
    def __init__(self, client: FakeClient, name: str) -> None:
        self.client = client
        self.name = name

    def __getattr__(self, method: str) -> Any:
        return lambda *args, **kwargs: self.client.invoke(self.name, method, args, kwargs)


class FakeClient:
    def __init__(
        self,
        *,
        templates: dict[str, Any] | None = None,
        webhook: dict[str, Any] | None = None,
        fail_methods: set[str] | None = None,
    ) -> None:
        self.templates_result = templates or {"data": []}
        self.webhook = webhook
        self.fail_methods = fail_methods or set()
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.init_kwargs: list[dict[str, Any]] = []
        self.closed = False
        self.signer_count = 0
        for name in (
            "accounts",
            "assignments",
            "authentication",
            "documents",
            "fields",
            "signer_documents",
            "signers",
            "tags",
            "templates",
            "users",
            "webhooks",
        ):
            setattr(self, name, FakeResource(self, name))

    def invoke(
        self,
        resource: str,
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        name = f"{resource}.{method}"
        self.calls.append((name, args, kwargs))
        if name in self.fail_methods:
            raise RuntimeError("PRIVATE_EXCEPTION_VALUE")
        if name == "templates.list":
            return self.templates_result
        if name == "templates.get":
            data = self.templates_result.get("data")
            return data[0] if isinstance(data, list) and data else {}
        if name == "webhooks.get":
            return self.webhook
        if name == "signers.create":
            self.signer_count += 1
            return {"id": f"PRIVATE_SIGNER_ID_{self.signer_count}", **args[0]}
        if name == "tags.create":
            return {"id": "PRIVATE_TAG_ID"}
        if name == "fields.create":
            return {"id": "PRIVATE_FIELD_ID"}
        if name == "fields.update":
            return {"regex": args[1].get("regex")}
        if name == "documents.upload":
            return {"id": "PRIVATE_DOCUMENT_ID"}
        if name == "documents.create_from_template":
            return {"id": "PRIVATE_TEMPLATE_DOCUMENT_ID"}
        if name == "documents.wait_until_ready":
            return {"id": "PRIVATE_DOCUMENT_ID", "pages": [{"id": "PRIVATE_PAGE_ID"}]}
        if name == "assignments.create":
            return {"id": "PRIVATE_ASSIGNMENT_ID"}
        if name == "accounts.create":
            return {"id": "PRIVATE_ACCOUNT_ID"}
        if name == "users.notification_preferences":
            return {"DocumentCompleted": True}
        if method in {"list", "list_dispatches", "search"}:
            return {"data": []}
        if method in {"activities", "list_event_types", "list_tags", "list_types", "statuses"}:
            return []
        return {}

    def close(self) -> None:
        self.closed = True


def _set_safe_env(monkeypatch: pytest.MonkeyPatch, emails: str = "user@example.test") -> None:
    monkeypatch.setenv("ASSINAFY_API_KEY", "API_KEY_SENTINEL")
    monkeypatch.setenv("ASSINAFY_ACCOUNT_ID", "ACCOUNT_ID_SENTINEL")
    monkeypatch.setenv("ASSINAFY_BASE_URL", live_smoke.SANDBOX_BASE_URL)
    monkeypatch.setenv("ASSINAFY_TEST_EMAILS", emails)
    for name in (
        "ASSINAFY_ACCESS_TOKEN",
        "ASSINAFY_SEND_TEST_NOTIFICATIONS",
        "ASSINAFY_TEST_ACCOUNT_LIFECYCLE",
        "ASSINAFY_TEST_USER_PREFERENCES",
        "ASSINAFY_READ_ONLY",
        "ASSINAFY_WEBHOOK_TEST_EMAIL",
        "ASSINAFY_WEBHOOK_TEST_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _install_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    def factory(**kwargs: Any) -> FakeClient:
        client.init_kwargs.append(kwargs)
        return client

    monkeypatch.setattr(live_smoke, "AssinafyClient", factory)


@pytest.mark.parametrize(
    "base_url",
    [
        None,
        "http://sandbox.assinafy.com.br/v1",
        "https://api.assinafy.com.br/v1",
        "https://sandbox.assinafy.com.br.invalid/v1",
        "https://sandbox.assinafy.com.br/v2",
    ],
)
def test_main_refuses_missing_or_non_sandbox_base_url(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str | None,
) -> None:
    _set_safe_env(monkeypatch)
    if base_url is None:
        monkeypatch.delenv("ASSINAFY_BASE_URL")
    else:
        monkeypatch.setenv("ASSINAFY_BASE_URL", base_url)
    constructed = False

    def forbidden_client(**kwargs: Any) -> None:
        nonlocal constructed
        constructed = True

    monkeypatch.setattr(live_smoke, "AssinafyClient", forbidden_client)

    assert live_smoke.main() == 2
    assert constructed is False


def test_partial_webhook_opt_in_is_rejected_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_env(monkeypatch)
    monkeypatch.setenv("ASSINAFY_WEBHOOK_TEST_URL", "https://webhook.invalid/smoke")
    constructed = False

    def forbidden_client(**kwargs: Any) -> None:
        nonlocal constructed
        constructed = True

    monkeypatch.setattr(live_smoke, "AssinafyClient", forbidden_client)

    assert live_smoke.main() == 2
    assert constructed is False


def test_invalid_notification_opt_in_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_safe_env(monkeypatch)
    monkeypatch.setenv("ASSINAFY_SEND_TEST_NOTIFICATIONS", "yes")
    monkeypatch.setattr(live_smoke, "AssinafyClient", lambda **kwargs: pytest.fail("unsafe"))
    assert live_smoke.main() == 2


def test_step_never_prints_response_or_exception_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_values = ("PRIVATE_EMAIL_VALUE", "PRIVATE_RESPONSE_VALUE", "PRIVATE_ERROR_VALUE")
    failures: list[str] = []

    assert live_smoke.step(
        "safe success label",
        lambda: {"email": private_values[0], "value": private_values[1]},
        failures,
    )

    def fail() -> None:
        raise ApiError(private_values[2], 400, {"email": private_values[0]})

    assert live_smoke.step("safe failure label", fail, failures) is None
    output = capsys.readouterr().out
    assert all(value not in output for value in private_values)
    assert failures == ["safe failure label"]


def test_optional_404_step_skips_only_not_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failures: list[str] = []

    def not_found() -> None:
        raise ApiError("private", 404)

    def server_error() -> None:
        raise ApiError("private", 500)

    assert live_smoke.optional_404_step("not deployed", not_found, failures) is None
    assert failures == []
    assert live_smoke.optional_404_step("broken", server_error, failures) is None
    assert failures == ["broken"]
    assert "private" not in capsys.readouterr().out


def test_read_preflight_failure_aborts_all_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_safe_env(monkeypatch)
    client = FakeClient(fail_methods={"accounts.get"})
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 1
    names = [name for name, _, _ in client.calls]
    assert "signers.create" not in names
    assert "tags.create" not in names
    assert "fields.create" not in names
    assert "documents.upload" not in names
    assert client.closed is True


def test_read_only_mode_needs_no_emails_and_never_mutates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_env(monkeypatch)
    monkeypatch.delenv("ASSINAFY_TEST_EMAILS")
    monkeypatch.setenv("ASSINAFY_READ_ONLY", "1")
    monkeypatch.setenv("ASSINAFY_TEST_USER_PREFERENCES", "1")
    client = FakeClient()
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 0
    names = [name for name, _, _ in client.calls]
    assert "accounts.create" not in names
    assert "signers.create" not in names
    assert "tags.create" not in names
    assert "fields.create" not in names
    assert "documents.upload" not in names
    assert "users.update_notification_preferences" not in names
    assert client.closed is True


def test_missing_created_id_aborts_dependent_writes_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingTagIdClient(FakeClient):
        def invoke(
            self,
            resource: str,
            method: str,
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
        ) -> Any:
            if (resource, method) == ("tags", "create"):
                self.calls.append(("tags.create", args, kwargs))
                return {}
            return super().invoke(resource, method, args, kwargs)

    _set_safe_env(monkeypatch)
    client = MissingTagIdClient()
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 1
    names = [name for name, _, _ in client.calls]
    assert "fields.create" not in names
    assert "documents.upload" not in names
    assert "signers.delete" in names
    assert client.closed is True


def test_minimal_pdf_has_computed_xref_offsets() -> None:
    pdf = live_smoke._make_minimal_pdf()
    startxref = int(pdf.rsplit(b"startxref\n", 1)[1].splitlines()[0])
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf[startxref:].startswith(b"xref\n0 5\n")
    assert pdf.endswith(b"%%EOF\n")

    xref_lines = pdf[startxref:].splitlines()
    for number, entry in enumerate(xref_lines[3:7], 1):
        offset = int(entry[:10])
        assert pdf[offset:].startswith(f"{number} 0 obj\n".encode())


def test_minimal_png_has_png_signature() -> None:
    assert live_smoke._make_minimal_png().startswith(b"\x89PNG\r\n\x1a\n")


def test_tagged_email_creates_runtime_only_plus_alias() -> None:
    assert live_smoke._tagged_email("user@example.test", "smoke-1") == ("user+smoke-1@example.test")
    with pytest.raises(ValueError):
        live_smoke._tagged_email("invalid", "smoke-1")


def test_main_uses_env_emails_cleans_every_resource_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(live_smoke.time, "time", lambda: 123)
    _set_safe_env(monkeypatch, "first@example.test,second@example.test")
    client = FakeClient()
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 0
    assert client.closed is True
    assert client.init_kwargs == [
        {
            "api_key": "API_KEY_SENTINEL",
            "account_id": "ACCOUNT_ID_SENTINEL",
            "base_url": live_smoke.SANDBOX_BASE_URL,
        }
    ]

    created_emails = [
        args[0]["email"] for name, args, _ in client.calls if name == "signers.create"
    ]
    assert created_emails == [
        "first+assinafy-sdk-123-1@example.test",
        "second+assinafy-sdk-123-2@example.test",
    ]
    call_names = [name for name, _, _ in client.calls]
    assert "webhooks.register" not in call_names
    assert "webhooks.inactivate" not in call_names
    assert "documents.wait_until_ready" in call_names
    assert "documents.rename" in call_names
    assert call_names[-5:] == [
        "documents.delete",
        "fields.delete",
        "tags.delete",
        "signers.delete",
        "signers.delete",
    ]

    output = capsys.readouterr().out
    for private_value in (
        "first+assinafy-sdk-123-1@example.test",
        "second+assinafy-sdk-123-2@example.test",
        "PRIVATE_DOCUMENT_ID",
        "PRIVATE_FIELD_ID",
        "PRIVATE_SIGNER_ID",
        "PRIVATE_TAG_ID",
    ):
        assert private_value not in output


def test_notification_opt_in_exercises_assignment_and_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_env(monkeypatch, "first@example.test,second@example.test")
    monkeypatch.setenv("ASSINAFY_SEND_TEST_NOTIFICATIONS", "1")
    client = FakeClient()
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 0
    names = [name for name, _, _ in client.calls]
    assert "assignments.create" in names
    assert "assignments.reset_expiration" in names
    assert "assignments.estimate_resend_cost" in names
    assert "assignments.resend_notification" in names
    assert "assignments.whatsapp_notifications" in names
    assert "documents.send_token" in names
    token_call = next(call for call in client.calls if call[0] == "documents.send_token")
    created_email = next(
        args[0]["email"] for name, args, _ in client.calls if name == "signers.create"
    )
    assert token_call[1] == ("PRIVATE_DOCUMENT_ID",)
    assert token_call[2] == {"email": created_email}
    assert "signer_documents.download" in names
    assert names.index("assignments.create") < names.index("documents.delete")


def test_notification_opt_in_exercises_template_document_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_env(monkeypatch)
    monkeypatch.setenv("ASSINAFY_SEND_TEST_NOTIFICATIONS", "1")
    client = FakeClient(
        templates={
            "data": [
                {
                    "id": "PRIVATE_TEMPLATE_ID",
                    "roles": [{"id": "PRIVATE_ROLE_ID"}],
                }
            ]
        }
    )
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 0
    names = [name for name, _, _ in client.calls]
    assert "documents.create_from_template" in names
    assert "documents.wait_until_ready" in names
    delete_ids = [args[0] for name, args, _ in client.calls if name == "documents.delete"]
    assert delete_ids == ["PRIVATE_TEMPLATE_DOCUMENT_ID", "PRIVATE_DOCUMENT_ID"]


def test_send_document_token_falls_back_only_for_contract_rejection() -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class Documents:
        def send_token(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append((args, kwargs))
            if kwargs:
                raise ApiError("current body not deployed", 400)
            return {"status": 200}

    client = type("Client", (), {"documents": Documents()})()

    assert live_smoke._send_document_token(client, "doc-1", "user@example.test") == {"status": 200}
    assert calls == [
        (("doc-1",), {"email": "user@example.test"}),
        (("doc-1", "user@example.test", "email"), {}),
    ]


def test_account_and_preference_opt_ins_restore_and_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_env(monkeypatch)
    monkeypatch.setenv("ASSINAFY_TEST_ACCOUNT_LIFECYCLE", "1")
    monkeypatch.setenv("ASSINAFY_TEST_USER_PREFERENCES", "1")
    client = FakeClient()
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 0
    names = [name for name, _, _ in client.calls]
    assert "accounts.create" in names
    assert "accounts.upload_logo" in names
    assert "accounts.download_logo" in names
    assert "accounts.delete_logo" in names
    assert names[-1] == "accounts.delete"
    updates = [
        args[0] for name, args, _ in client.calls if name == "users.update_notification_preferences"
    ]
    assert updates == [{"DocumentCompleted": False}, {"DocumentCompleted": True}]


def test_webhook_opt_in_restores_exact_original_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_safe_env(monkeypatch)
    monkeypatch.setenv("ASSINAFY_WEBHOOK_TEST_URL", "https://webhook.invalid/smoke")
    monkeypatch.setenv("ASSINAFY_WEBHOOK_TEST_EMAIL", "WEBHOOK_EMAIL_SENTINEL")
    original = {
        "events": ["event-one", "event-two"],
        "is_active": False,
        "url": "https://original.invalid/hook",
        "email": "ORIGINAL_EMAIL_SENTINEL",
        "updated_at": "PRIVATE_TIMESTAMP",
    }
    client = FakeClient(webhook=original, fail_methods={"webhooks.inactivate"})
    _install_client(monkeypatch, client)

    assert live_smoke.main() == 1
    registrations = [args[0] for name, args, _ in client.calls if name == "webhooks.register"]
    assert registrations == [
        {
            "url": "https://webhook.invalid/smoke",
            "email": "WEBHOOK_EMAIL_SENTINEL",
            "events": ["event-one", "event-two"],
            "is_active": True,
        },
        {
            "events": ["event-one", "event-two"],
            "is_active": False,
            "url": "https://original.invalid/hook",
            "email": "ORIGINAL_EMAIL_SENTINEL",
        },
    ]
    assert client.closed is True
    output = capsys.readouterr().out
    for private_value in (
        "WEBHOOK_EMAIL_SENTINEL",
        "ORIGINAL_EMAIL_SENTINEL",
        "PRIVATE_EXCEPTION_VALUE",
        "PRIVATE_TIMESTAMP",
    ):
        assert private_value not in output


def test_unexpected_failure_still_runs_all_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_safe_env(monkeypatch)
    client = FakeClient(
        templates={"data": [{"id": "PRIVATE_TEMPLATE_ID", "roles": [{"id": "role"}]}]}
    )
    _install_client(monkeypatch, client)

    def fail_after_creates(templates: Any) -> None:
        raise RuntimeError("PRIVATE_LATE_FAILURE")

    monkeypatch.setattr(live_smoke, "_first_template_role_id", fail_after_creates)

    assert live_smoke.main() == 1
    assert client.closed is True
    call_names = [name for name, _, _ in client.calls]
    assert call_names[-4:] == [
        "documents.delete",
        "fields.delete",
        "tags.delete",
        "signers.delete",
    ]
    assert "PRIVATE_LATE_FAILURE" not in capsys.readouterr().out
