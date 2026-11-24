"""Live sandbox smoke test for the Assinafy Python SDK.

Required environment variables:
    ASSINAFY_API_KEY
    ASSINAFY_ACCOUNT_ID
    ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1

Write-mode requirement:
    ASSINAFY_TEST_EMAILS (comma-separated; one temporary signer per address)

Set ``ASSINAFY_READ_ONLY=1`` for non-mutating coverage without test emails.

Set ``ASSINAFY_SEND_TEST_NOTIFICATIONS=1`` to create an assignment for those
signers and exercise notification/resend operations. This opt-in sends email
and can consume sandbox credits.

``ASSINAFY_TEST_ACCOUNT_LIFECYCLE=1`` enables disposable account/logo CRUD.
``ASSINAFY_TEST_USER_PREFERENCES=1`` toggles one preference and restores its
original value in ``finally``.
``ASSINAFY_TEST_EXTENDED_FLOWS=1`` exercises scheduling, watchers, contracts,
envelopes and embed sessions with disposable documents. It also requires
``ASSINAFY_SEND_TEST_NOTIFICATIONS=1`` and the corresponding plan features.
The base URL may also be https://api.angry-pisco.stage.assinafy.com.br/v1.

Webhook mutation is disabled unless both ``ASSINAFY_WEBHOOK_TEST_URL`` and
``ASSINAFY_WEBHOOK_TEST_EMAIL`` are set and the existing subscription can be
restored exactly. Held endpoints and legacy HTTP URLs are left unchanged.
The script never prints API payloads or environment values.
"""

from __future__ import annotations

import os
import sys
import time
from base64 import b64decode
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from assinafy import ApiError, AssinafyClient, AssinafyError, NotificationPreferenceCode

SANDBOX_BASE_URL = "https://sandbox.assinafy.com.br/v1"
STAGING_BASE_URL = "https://api.angry-pisco.stage.assinafy.com.br/v1"


def step(label: str, fn: Callable[[], Any], failures: list[str]) -> Any:
    """Run one smoke step without logging response or exception values."""
    print(f"\n=== {label} ===")
    try:
        result = fn()
    except AssinafyError as err:
        status = f" HTTP {err.status_code}" if isinstance(err, ApiError) else ""
        print(f"  FAIL [{type(err).__name__}{status}]")
        failures.append(label)
        return None
    except Exception as err:  # noqa: BLE001
        print(f"  FAIL [{type(err).__name__}]")
        failures.append(label)
        return None
    print("  OK")
    return result


def cleanup_step(label: str, fn: Callable[[], Any], failures: list[str]) -> Any:
    """Restore/delete test resources, retrying only explicit HTTP 429 responses."""

    def run() -> Any:
        for attempt in range(4):
            try:
                return fn()
            except ApiError as error:
                if error.status_code != 429 or attempt == 3:
                    raise
                time.sleep(min(error.retry_after or 20, 60))
        return None

    return step(label, run, failures)


def optional_404_step(
    label: str,
    fn: Callable[[], Any],
    failures: list[str],
    skip_statuses: frozenset[int] = frozenset({404}),
) -> Any:
    """Run a published operation that the sandbox may not have deployed yet.

    ``skip_statuses`` is the set of answers that mean "not served here" rather
    than "broken". Missing operations may return ``404``; older sandbox
    proxies can return ``403`` for origin-root discovery documents. Only the
    discovery call opts into both statuses.
    """
    print(f"\n=== {label} ===")
    try:
        result = fn()
    except ApiError as err:
        if err.status_code in skip_statuses:
            print("  SKIP [published route not deployed in sandbox]")
            return None
        print(f"  FAIL [{type(err).__name__}]")
        failures.append(label)
        return None
    except Exception as err:  # noqa: BLE001
        print(f"  FAIL [{type(err).__name__}]")
        failures.append(label)
        return None
    print("  OK")
    return result


def _make_minimal_pdf() -> bytes:
    """Build a valid blank one-page PDF with calculated xref offsets."""
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    )
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode())
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(pdf)


def _validated_configuration(
    *, require_emails: bool = True
) -> tuple[str, str, str, tuple[str, ...]]:
    api_key = os.environ.get("ASSINAFY_API_KEY")
    account_id = os.environ.get("ASSINAFY_ACCOUNT_ID")
    base_url = os.environ.get("ASSINAFY_BASE_URL")
    emails = tuple(
        email.strip()
        for email in os.environ.get("ASSINAFY_TEST_EMAILS", "").split(",")
        if email.strip()
    )
    if not api_key or not account_id or (require_emails and not emails):
        raise ValueError("missing required smoke-test environment")
    if not base_url or base_url.rstrip("/") not in {SANDBOX_BASE_URL, STAGING_BASE_URL}:
        raise ValueError("smoke test requires the canonical HTTPS sandbox or staging URL")
    for email in emails:
        _tagged_email(email, "validation")
    return api_key, account_id, base_url.rstrip("/"), emails


def _webhook_opt_in() -> tuple[str, str] | None:
    url = os.environ.get("ASSINAFY_WEBHOOK_TEST_URL")
    email = os.environ.get("ASSINAFY_WEBHOOK_TEST_EMAIL")
    if not url and not email:
        return None
    if not url or not email or not url.startswith("https://"):
        raise ValueError("webhook smoke test requires HTTPS URL and email opt-ins")
    return url, email


def _opt_in(name: str) -> bool:
    value = os.environ.get(name, "0")
    if value not in {"0", "1"}:
        raise ValueError(f"{name} must be 0 or 1")
    return value == "1"


def _make_minimal_png() -> bytes:
    """Return a valid 64-by-32 PNG with a synthetic black diagonal on white."""
    return b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAEAAAAAgCAYAAACinX6EAAAAsElEQVR4nOXSSQqAQAxE"
        "0dz/0roqEaXpMUMlH3pt5aGIyPV+1ZIvQDWI59KqEL8Lq0E0L6sC0b0oO8TwJVkh"
        "pi/IBrG8PAvE9mJ2iGNLWSGOL2SDUFvGAqG+KDqE2ZKoEOYLokG4fTkKhPs/6A3h"
        "DoC8IMIAIGuIcADICiIsANKGCA+AtCBoANBpCDoAdAqCFgDtQtADoFWINABoFiIdABqF"
        "SAuAehDpAVALogwA+gLcGzGv6NJp3c4AAAAASUVORK5CYII="
    )


def _restorable_webhook(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("is_held") or value.get("held_since") is not None:
        return None
    events = value.get("events")
    is_active = value.get("is_active")
    url = value.get("url")
    email = value.get("email")
    if (
        not isinstance(events, list)
        or any(not isinstance(event, str) or not event for event in events)
        or not isinstance(is_active, bool)
        or not isinstance(url, str)
        or not url.startswith("https://")
        or not isinstance(email, str)
        or not email
    ):
        return None
    return {"events": list(events), "is_active": is_active, "url": url, "email": email}


def _resource_id(value: Any) -> str | None:
    resource_id = value.get("id") if isinstance(value, dict) else None
    return resource_id if isinstance(resource_id, str) and resource_id else None


def _required_resource_id(value: Any, operation: str) -> str:
    resource_id = _resource_id(value)
    if resource_id is None:
        raise RuntimeError(f"{operation} returned no resource ID")
    return resource_id


def _tagged_email(email: str, tag: str) -> str:
    """Return a unique plus-address without logging or persisting the mailbox."""
    local, separator, domain = email.partition("@")
    if not separator or not local or not domain:
        raise ValueError("invalid smoke-test email")
    return f"{local}+{tag}@{domain}"


def _template_role_ids(template: Any) -> list[str]:
    roles = template.get("roles") if isinstance(template, dict) else None
    if not isinstance(roles, list):
        return []
    return [role_id for role in roles if (role_id := _resource_id(role)) is not None]


def _first_document_page_id(document: Any) -> str | None:
    pages = document.get("pages") if isinstance(document, dict) else None
    page = pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], dict) else None
    return _resource_id(page)


def _extended_flows(client: AssinafyClient, signer_id: str, failures: list[str]) -> None:
    """Exercise disposable scheduled, envelope, contract and embed lifecycles."""
    documents: list[str] = []
    pending_sends: list[str] = []
    envelope_id: str | None = None
    origin_id: str | None = None
    origin = f"https://sdk-smoke-{time.time_ns()}.example.com"
    send_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    try:
        for index in range(4):
            doc = client.documents.upload(
                {"buffer": _make_minimal_pdf(), "file_name": f"sdk-flow-{index}.pdf"}
            )
            documents.append(_required_resource_id(doc, "upload"))
            client.documents.wait_until_ready(documents[-1], timeout=60)
        document_id = documents[0]

        print("  Watchers, capacities and notification history before sending")
        watchers = client.documents.set_watchers(document_id, [signer_id, signer_id])
        assert [item["id"] for item in watchers] == [signer_id]
        assert client.documents.watchers(document_id)[0]["id"] == signer_id
        assert client.documents.set_watchers(document_id, []) == []
        assert client.documents.signer_capacities(document_id) == []
        assert client.documents.notification_history(document_id) == []

        print("  Contract update, read, related, renew and terminate")
        terms = client.contracts.update(
            document_id,
            {
                "status": "active",
                "start_date": "2026-01-01",
                "end_date": "2030-12-31",
                "value": 125.50,
                "currency": "BRL",
                "metadata": {"purpose": "sdk-test"},
                "external_references": [{"system": "sdk-test", "id": "example"}],
            },
        )
        assert terms["status"] == "active"
        assert client.contracts.get(document_id)["value"] is not None
        client.contracts.related(document_id, expand="document")
        client.contracts.renew(document_id, {"term": 1, "updated_at": terms["updated_at"]})
        assert (
            client.contracts.terminate(document_id, {"reason": "Disposable SDK test"})["status"]
            == "terminated"
        )

        print("  Scheduled assignment cancel, send-now and signer capacity")
        body = {
            "send_at": send_at,
            "signers": [{"id": signer_id, "embedded": True, "sign_as": "Witness"}],
        }
        scheduled = client.scheduled_sends.create_assignment(document_id, body)
        scheduled_id = _required_resource_id(scheduled, "schedule assignment")
        pending_sends.append(scheduled_id)
        assert scheduled["status"] == "pending"
        assert client.scheduled_sends.cancel(scheduled_id)["status"] == "cancelled"
        pending_sends.remove(scheduled_id)
        origin_id = _required_resource_id(client.accounts.add_embed_origin(origin), "embed origin")
        scheduled = client.scheduled_sends.create_assignment(document_id, body)
        scheduled_id = _required_resource_id(scheduled, "schedule assignment")
        pending_sends.append(scheduled_id)
        sent = client.scheduled_sends.send(scheduled_id)
        pending_sends.remove(scheduled_id)
        assert sent["status"] == "sent" and sent["assignment_id"]
        assert client.documents.signer_capacities(document_id) == [
            {"signer_id": signer_id, "sign_as": "Witness"}
        ]
        assert client.documents.notification_history(document_id)[0]["signer_id"] == signer_id
        assert client.scheduled_sends.list({"document_id": document_id})["data"]

        print("  Embed origin update, mint, exchange and one-time-token refusal")
        client.accounts.update_embed_origin(origin_id, origin)
        assert any(item["id"] == origin_id for item in client.accounts.list_embed_origins())
        session = client.assignments.create_embed_session(
            document_id, sent["assignment_id"], signer_id
        )
        token = session["url"].rstrip("/").rsplit("/", 1)[-1]
        exchanged = client.embed.exchange(token, origin)
        assert exchanged["document_id"] == document_id
        assert exchanged["signer_id"] == signer_id and exchanged["signer_access_code"]
        try:
            client.embed.exchange(token, origin)
        except ApiError as error:
            assert error.status_code == 410
        else:
            raise AssertionError("Embed token was accepted twice")

        print("  Envelope scheduling, estimates, idempotency, edits and cancellation")
        body = {
            "name": "SDK disposable envelope",
            "signers": [{"id": signer_id}],
            "documents": [{"id": doc_id, "signer_ids": [signer_id]} for doc_id in documents[1:3]],
        }
        scheduled = client.scheduled_sends.create_envelope({**body, "send_at": send_at})
        scheduled_id = _required_resource_id(scheduled, "schedule envelope")
        pending_sends.append(scheduled_id)
        assert client.scheduled_sends.cancel(scheduled_id)["status"] == "cancelled"
        pending_sends.remove(scheduled_id)
        assert client.envelopes.estimate_cost(body)["has_sufficient_resources"]
        key = f"sdk-smoke-{time.time_ns()}"
        envelope_id = _required_resource_id(
            client.envelopes.create(body, idempotency_key=key), "create envelope"
        )
        assert client.envelopes.create(body, idempotency_key=key)["id"] == envelope_id
        assert client.envelopes.get(envelope_id)["id"] == envelope_id
        client.envelopes.update(
            envelope_id,
            {
                "name": "SDK disposable envelope renamed",
                "message": None,
                "document_ids": list(reversed(documents[1:3])),
            },
        )
        assert client.envelopes.estimate_resend_cost(envelope_id, signer_id)["total"] >= 0
        client.envelopes.activities(envelope_id, {"per_page": 2})
        assert client.envelopes.download(envelope_id, "original").startswith(b"PK")
        client.envelopes.add_document(
            envelope_id,
            {
                "id": documents[3],
                "signer_ids": [signer_id],
            },
        )
        client.envelopes.remove_document(envelope_id, documents[3])
        assert client.envelopes.cancel(envelope_id)
        client.envelopes.delete(envelope_id)
        envelope_id = None
    finally:
        for scheduled_id in reversed(pending_sends):
            cleanup_step(
                "cancel pending test send",
                lambda: client.scheduled_sends.cancel(scheduled_id),
                failures,
            )
        if envelope_id:
            cleanup_step(
                "cancel test envelope", lambda: client.envelopes.cancel(envelope_id), failures
            )
            cleanup_step(
                "delete test envelope", lambda: client.envelopes.delete(envelope_id), failures
            )
        if origin_id:
            cleanup_step(
                "delete test embed origin",
                lambda: client.accounts.delete_embed_origin(origin_id),
                failures,
            )
        for document_id in reversed(documents):
            cleanup_step(
                "delete extended-flow document",
                lambda: client.documents.delete(document_id),
                failures,
            )


def main() -> int:
    try:
        read_only = _opt_in("ASSINAFY_READ_ONLY")
        api_key, account_id, base_url, test_emails = _validated_configuration(
            require_emails=not read_only
        )
        webhook_opt_in = _webhook_opt_in()
        send_test_notifications = _opt_in("ASSINAFY_SEND_TEST_NOTIFICATIONS")
        test_account_lifecycle = _opt_in("ASSINAFY_TEST_ACCOUNT_LIFECYCLE")
        test_user_preferences = _opt_in("ASSINAFY_TEST_USER_PREFERENCES")
        test_extended_flows = _opt_in("ASSINAFY_TEST_EXTENDED_FLOWS")
        if test_extended_flows and not read_only and not send_test_notifications:
            raise ValueError("Extended flows require the notification opt-in")
    except ValueError:
        print("Unsafe or incomplete live-smoke configuration", file=sys.stderr)
        return 2

    failures: list[str] = []
    signer_ids: list[str] = []
    signer_emails: list[str] = []
    tag_id: str | None = None
    field_id: str | None = None
    document_id: str | None = None
    template_document_id: str | None = None
    webhook_restore: dict[str, Any] | None = None
    webhook_mutation_attempted = False
    temporary_account_id: str | None = None
    preference_restore: dict[NotificationPreferenceCode, bool] | None = None
    preference_mutation_attempted = False
    close_attempted = False
    client = AssinafyClient(api_key=api_key, account_id=account_id, base_url=base_url)

    try:
        # Read-only endpoints first.
        step("accounts.list()", lambda: client.accounts.list(), failures)
        step("accounts.get()", lambda: client.accounts.get(), failures)
        step("accounts.theme()", lambda: client.accounts.theme(), failures)
        optional_404_step("accounts.usage()", lambda: client.accounts.usage(), failures)
        optional_404_step(
            "accounts.notification_policy()",
            lambda: client.accounts.notification_policy(),
            failures,
        )
        optional_404_step("accounts.stats()", lambda: client.accounts.stats(), failures)
        step("users.me()", lambda: client.users.me(), failures)
        optional_404_step("users.stats()", lambda: client.users.stats(), failures)
        preferences = optional_404_step(
            "users.notification_preferences()",
            lambda: client.users.notification_preferences(),
            failures,
        )
        if test_user_preferences and isinstance(preferences, dict):
            original = preferences.get("DocumentCompleted")
            if isinstance(original, bool):
                preference_restore = {"DocumentCompleted": original}

        optional_404_step(
            "users.push_preferences()", lambda: client.users.push_preferences(), failures
        )
        optional_404_step(
            "envelopes.list(per_page=5)", lambda: client.envelopes.list({"per_page": 5}), failures
        )
        step("documents.statuses()", lambda: client.documents.statuses(), failures)
        step("fields.list_types()", lambda: client.fields.list_types(), failures)
        step("webhooks.list_event_types()", lambda: client.webhooks.list_event_types(), failures)

        # Discovery is credential-free and available on both environments.
        # Older sandbox deployments may still refuse root metadata paths.
        oauth = client.oauth("live-smoke-discovery-only")
        optional_404_step(
            "oauth.protected_resource_metadata()",
            lambda: oauth.protected_resource_metadata(),
            failures,
            # The sandbox host serves this path through nginx, which answers 403
            # rather than letting the API answer 404.
            skip_statuses=frozenset({403, 404}),
        )
        optional_404_step(
            "oauth.authorization_server_metadata()",
            lambda: oauth.authorization_server_metadata(),
            failures,
        )
        step(
            "oauth.start_authorization() [no request]",
            lambda: oauth.start_authorization(
                "https://example.com/oauth/callback", ["documents:read"]
            ),
            failures,
        )
        step(
            "documents.list(per_page=5)",
            lambda: client.documents.list({"per_page": 5}),
            failures,
        )
        contracts = optional_404_step(
            "contracts.list(per_page=5)",
            lambda: client.contracts.list({"per_page": 5}),
            failures,
        )
        contract_rows = contracts.get("data") if isinstance(contracts, dict) else None
        first_contract = (
            contract_rows[0] if isinstance(contract_rows, list) and contract_rows else None
        )
        contract_document_id = (
            first_contract.get("document_id") if isinstance(first_contract, dict) else None
        )
        if isinstance(contract_document_id, str) and contract_document_id:
            step(
                "contracts.get()",
                lambda: client.contracts.get(contract_document_id),
                failures,
            )
            step(
                "contracts.related()",
                lambda: client.contracts.related(contract_document_id),
                failures,
            )
        step(
            "signers.list(per_page=5)",
            lambda: client.signers.list({"per_page": 5}),
            failures,
        )
        templates = step(
            "templates.list(per_page=5)",
            lambda: client.templates.list({"per_page": 5}),
            failures,
        )
        template_data = templates.get("data") if isinstance(templates, dict) else None
        template_id = (
            _resource_id(template_data[0])
            if isinstance(template_data, list) and template_data
            else None
        )
        template = None
        if template_id:
            template = step(
                "templates.get(real id)", lambda: client.templates.get(template_id), failures
            )
        step(
            "documents.search(search=sdk)",
            lambda: client.documents.search({"search": "sdk", "per_page": 5}),
            failures,
        )
        step(
            "assignments.list(per_page=5)",
            lambda: client.assignments.list({"per_page": 5}),
            failures,
        )
        step("fields.list()", lambda: client.fields.list(), failures)
        step(
            "documents.verify(invalid hash)",
            lambda: client.documents.verify("0" * 40),
            failures,
        )
        step(
            "tags.list(search=sdk-smoke)",
            lambda: client.tags.list({"search": "sdk-smoke"}),
            failures,
        )
        original_webhook = step("webhooks.get()", lambda: client.webhooks.get(), failures)
        step(
            "webhooks.list_dispatches(per_page=5)",
            lambda: client.webhooks.list_dispatches({"per_page": 5}),
            failures,
        )
        optional_404_step(
            "webhooks.list_endpoints()", lambda: client.webhooks.list_endpoints(), failures
        )
        optional_404_step(
            "authentication.list_mfa_methods()",
            lambda: client.authentication.list_mfa_methods(),
            failures,
        )

        if webhook_opt_in:
            webhook_restore = _restorable_webhook(original_webhook)

        access_token = os.environ.get("ASSINAFY_ACCESS_TOKEN")
        if access_token:
            token_client = AssinafyClient(token=access_token, base_url=base_url)
            try:
                step(
                    "authentication.get_api_key()",
                    lambda: token_client.authentication.get_api_key(),
                    failures,
                )
            finally:
                token_client.close()
        else:
            print("\n=== authentication.get_api_key() ===\n  SKIP [access token not configured]")

        if read_only:
            step("client.close()", client.close, failures)
            close_attempted = True
            return 1 if failures else 0

        if failures:
            print("\n=== mutation flow ===\n  SKIP [read preflight failed]")
            return 1

        if test_user_preferences and preference_restore is not None:
            preference_mutation_attempted = True
            step(
                "users.update_notification_preferences()",
                lambda: client.users.update_notification_preferences(
                    {"DocumentCompleted": not preference_restore["DocumentCompleted"]}
                ),
                failures,
            )
        else:
            reason = (
                "endpoint unavailable"
                if test_user_preferences
                else "explicit opt-in not configured"
            )
            print(f"\n=== user preference mutation ===\n  SKIP [{reason}]")

        if webhook_opt_in and webhook_restore is not None:
            webhook_url, webhook_email = webhook_opt_in
            webhook_mutation_attempted = True
            step(
                "webhooks.register()",
                lambda: client.webhooks.register(
                    {
                        "url": webhook_url,
                        "email": webhook_email,
                        "events": list(webhook_restore["events"]),
                        "is_active": True,
                    }
                ),
                failures,
            )
            step("webhooks.inactivate()", lambda: client.webhooks.inactivate(), failures)
        else:
            reason = (
                "subscription not restorable"
                if webhook_opt_in
                else "explicit opt-in not configured"
            )
            print(f"\n=== webhook mutation ===\n  SKIP [{reason}]")

        if failures:
            print("\n=== resource mutation flow ===\n  SKIP [mutation preflight failed]")
            return 1

        # Write flow. IDs are captured immediately and cleaned only in finally.
        timestamp = int(time.time())
        if test_account_lifecycle:
            account = step(
                "accounts.create() disposable account",
                lambda: client.accounts.create(f"SDK Smoke {timestamp}"),
                failures,
            )
            temporary_account_id = _required_resource_id(account, "accounts.create()")
            if temporary_account_id:
                step(
                    "accounts.get() disposable account",
                    lambda: client.accounts.get(temporary_account_id),
                    failures,
                )
                step(
                    "accounts.update() disposable account",
                    lambda: client.accounts.update(
                        {"name": f"SDK Smoke Updated {timestamp}"}, temporary_account_id
                    ),
                    failures,
                )
                step(
                    "accounts.theme() disposable account",
                    lambda: client.accounts.theme(temporary_account_id),
                    failures,
                )
                optional_404_step(
                    "accounts.stats() disposable account",
                    lambda: client.accounts.stats(account_id=temporary_account_id),
                    failures,
                )
                step(
                    "accounts.upload_logo() disposable account",
                    lambda: client.accounts.upload_logo(
                        {"buffer": _make_minimal_png(), "file_name": "sdk-smoke.png"},
                        temporary_account_id,
                    ),
                    failures,
                )
                step(
                    "accounts.download_logo() disposable account",
                    lambda: client.accounts.download_logo(temporary_account_id),
                    failures,
                )
                step(
                    "accounts.delete_logo() disposable account",
                    lambda: client.accounts.delete_logo(temporary_account_id),
                    failures,
                )
        else:
            print("\n=== account lifecycle ===\n  SKIP [explicit opt-in not configured]")

        for index, signer_email in enumerate(test_emails, 1):
            tagged_email = _tagged_email(signer_email, f"assinafy-sdk-{timestamp}-{index}")
            signer = step(
                f"signers.create() #{index}",
                lambda: client.signers.create(
                    {"full_name": "SDK Smoke Test", "email": tagged_email}
                ),
                failures,
            )
            signer_id = _required_resource_id(signer, "signers.create()")
            signer_ids.append(signer_id)
            signer_emails.append(tagged_email)

        primary_signer_id = signer_ids[0] if signer_ids else None
        if primary_signer_id and test_extended_flows:
            step(
                "extended workflows",
                lambda: _extended_flows(client, primary_signer_id, failures),
                failures,
            )
        if primary_signer_id:
            step("signers.get()", lambda: client.signers.get(primary_signer_id), failures)
            step(
                "signers.update()",
                lambda: client.signers.update(primary_signer_id, {"full_name": "SDK Smoke Test 2"}),
                failures,
            )
            step(
                "signers.find_by_email()",
                lambda: client.signers.find_by_email(signer_emails[0]),
                failures,
            )
            step(
                "signer_documents.list_as_workspace()",
                lambda: client.signer_documents.list_as_workspace(primary_signer_id),
                failures,
            )
            step(
                "signer_documents.search_as_workspace()",
                lambda: client.signer_documents.search_as_workspace(primary_signer_id, "sdk"),
                failures,
            )

        tag_name = f"sdk-smoke-{timestamp}"
        tag = step(
            "tags.create()",
            lambda: client.tags.create({"name": tag_name, "color": "3366ff"}),
            failures,
        )
        tag_id = _required_resource_id(tag, "tags.create()")
        if tag_id:
            step(
                "tags.update()",
                lambda: client.tags.update(tag_id, {"color": None}),
                failures,
            )

        field = step(
            "fields.create()",
            lambda: client.fields.create({"type": "text", "name": f"sdk-smoke-field-{timestamp}"}),
            failures,
        )
        field_id = _required_resource_id(field, "fields.create()")
        if field_id:
            step("fields.get()", lambda: client.fields.get(field_id), failures)
            step(
                "fields.update() sets a regex",
                lambda: client.fields.update(field_id, {"regex": "/^[0-9]+$/"}),
                failures,
            )
            cleared = step(
                "fields.update() clears the regex with None",
                lambda: client.fields.update(field_id, {"regex": None}),
                failures,
            )
            if isinstance(cleared, dict) and cleared.get("regex") is not None:
                print("  FAIL [regex was not cleared]")
                failures.append("fields.update() regex-clear did not take effect")
            step(
                "fields.validate_as_workspace()",
                lambda: client.fields.validate_as_workspace(field_id, "123"),
                failures,
            )
            step(
                "fields.validate_multiple_as_workspace()",
                lambda: client.fields.validate_multiple_as_workspace(
                    [{"field_id": field_id, "value": "123"}]
                ),
                failures,
            )

        document = step(
            "documents.upload()",
            lambda: client.documents.upload(
                {"buffer": _make_minimal_pdf(), "file_name": "sdk-smoke.pdf"}
            ),
            failures,
        )
        document_id = _required_resource_id(document, "documents.upload()")
        if document_id:
            ready_document = step(
                "documents.wait_until_ready()",
                lambda: client.documents.wait_until_ready(document_id, timeout=60),
                failures,
            )
            step("documents.get()", lambda: client.documents.get(document_id), failures)
            step(
                "documents.activities()",
                lambda: client.documents.activities(document_id),
                failures,
            )
            if tag_id:
                step(
                    "documents.append_tags()",
                    lambda: client.documents.append_tags(document_id, [tag_id]),
                    failures,
                )
                step(
                    "documents.list_tags()",
                    lambda: client.documents.list_tags(document_id),
                    failures,
                )
                step(
                    "documents.replace_tags()",
                    lambda: client.documents.replace_tags(document_id, [tag_id]),
                    failures,
                )
                step(
                    "documents.detach_tag()",
                    lambda: client.documents.detach_tag(document_id, tag_id),
                    failures,
                )
                step(
                    "documents.append_tags() after detach",
                    lambda: client.documents.append_tags(document_id, [tag_id]),
                    failures,
                )
            if primary_signer_id:
                step(
                    "assignments.estimate_cost()",
                    lambda: client.assignments.estimate_cost(
                        document_id,
                        {"method": "virtual", "signers": [{"verification_method": "Email"}]},
                    ),
                    failures,
                )
            step(
                "documents.public_info()",
                lambda: client.documents.public_info(document_id),
                failures,
            )
            step(
                "documents.download(original)",
                lambda: client.documents.download(document_id, "original"),
                failures,
            )
            step("documents.thumbnail()", lambda: client.documents.thumbnail(document_id), failures)
            page_id = _first_document_page_id(ready_document)
            if page_id:
                step(
                    "documents.download_page()",
                    lambda: client.documents.download_page(document_id, page_id),
                    failures,
                )
            step(
                "documents.rename()",
                lambda: client.documents.rename(document_id, "sdk-smoke-renamed.pdf"),
                failures,
            )
            if signer_ids and send_test_notifications:
                assignment = step(
                    "assignments.create() sends test notifications",
                    lambda: client.assignments.create(
                        document_id,
                        {
                            "method": "virtual",
                            "signers": [
                                {
                                    "id": signer_id,
                                    "verification_method": "Email",
                                    "notification_methods": ["Email"],
                                }
                                for signer_id in signer_ids
                            ],
                            "expires_at": "2030-12-31T00:00:00Z",
                        },
                    ),
                    failures,
                )
                assignment_id = _required_resource_id(assignment, "assignments.create()")
                if assignment_id and primary_signer_id:
                    step(
                        "documents.send_token() sends test OTP",
                        lambda: client.documents.send_token(document_id, signer_emails[0]),
                        failures,
                    )
                    step(
                        "documents.download() workspace artifact",
                        lambda: client.documents.download(document_id, "original"),
                        failures,
                    )
                    step(
                        "assignments.reset_expiration()",
                        lambda: client.assignments.reset_expiration(
                            document_id, assignment_id, "2031-01-31T00:00:00Z"
                        ),
                        failures,
                    )
                    cleared_expiration = step(
                        "assignments.reset_expiration(None) clears the expiration",
                        lambda: client.assignments.reset_expiration(
                            document_id, assignment_id, None
                        ),
                        failures,
                    )
                    if (
                        isinstance(cleared_expiration, dict)
                        and cleared_expiration.get("expires_at") is not None
                    ):
                        print("  FAIL [expiration was not cleared]")
                        failures.append("assignments.reset_expiration(None) did not clear")
                    step(
                        "assignments.estimate_resend_cost()",
                        lambda: client.assignments.estimate_resend_cost(
                            document_id, assignment_id, primary_signer_id
                        ),
                        failures,
                    )
                    step(
                        "assignments.resend_notification() sends test email",
                        lambda: client.assignments.resend_notification(
                            document_id, assignment_id, primary_signer_id
                        ),
                        failures,
                    )
                    step(
                        "assignments.whatsapp_notifications()",
                        lambda: client.assignments.whatsapp_notifications(
                            document_id, assignment_id
                        ),
                        failures,
                    )
            else:
                print("\n=== assignment notifications ===\n  SKIP [explicit opt-in not configured]")

        if template_id:
            role_ids = _template_role_ids(template)
            if role_ids:
                step(
                    "documents.estimate_cost_from_template()",
                    lambda: client.documents.estimate_cost_from_template(
                        template_id, [{"role_id": role_id} for role_id in role_ids]
                    ),
                    failures,
                )
            # The API refuses the same signer in two roles: one signer per role.
            if role_ids and len(signer_ids) >= len(role_ids) and send_test_notifications:
                template_document = step(
                    "documents.create_from_template() sends test notifications",
                    lambda: client.documents.create_from_template(
                        template_id,
                        [
                            {
                                "role_id": template_role_id,
                                "id": signer_id,
                                "verification_method": "Email",
                                "notification_methods": ["Email"],
                            }
                            for template_role_id, signer_id in zip(role_ids, signer_ids)
                        ],
                        {"name": f"sdk-template-smoke-{timestamp}.pdf"},
                    ),
                    failures,
                )
                template_document_id = _required_resource_id(
                    template_document, "documents.create_from_template()"
                )
                step(
                    "documents.wait_until_ready() template document",
                    lambda: client.documents.wait_until_ready(template_document_id, timeout=60),
                    failures,
                )
            else:
                print(
                    "\n=== template document creation ===\n"
                    "  SKIP [too few test signers for the template roles, or no opt-in]"
                )
    except Exception as err:  # noqa: BLE001
        print(f"\n=== smoke execution ===\n  FAIL [{type(err).__name__}]")
        failures.append("smoke execution")
    finally:
        if webhook_mutation_attempted and webhook_restore is not None:
            cleanup_step(
                "webhooks.register() restores original subscription",
                lambda: client.webhooks.register(webhook_restore),
                failures,
            )
        if preference_mutation_attempted and preference_restore is not None:
            cleanup_step(
                "users.update_notification_preferences() restores original",
                lambda: client.users.update_notification_preferences(preference_restore),
                failures,
            )
        if template_document_id:
            cleanup_step(
                "documents.delete() template cleanup",
                lambda: client.documents.delete(template_document_id),
                failures,
            )
        if document_id:
            cleanup_step(
                "documents.delete() cleanup",
                lambda: client.documents.delete(document_id),
                failures,
            )
        if field_id:
            cleanup_step(
                "fields.delete() cleanup", lambda: client.fields.delete(field_id), failures
            )
        if tag_id:
            cleanup_step(
                "tags.delete() cleanup", lambda: client.tags.delete(tag_id, force=True), failures
            )
        for signer_id in reversed(signer_ids):
            cleanup_step(
                "signers.delete() cleanup",
                lambda: client.signers.delete(signer_id),
                failures,
            )
        if temporary_account_id:
            cleanup_step(
                "accounts.delete() disposable account cleanup",
                lambda: client.accounts.delete(temporary_account_id),
                failures,
            )
        if not close_attempted:
            step("client.close()", client.close, failures)

    if failures:
        print("\nLive smoke failed; see step labels above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
