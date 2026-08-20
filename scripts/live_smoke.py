"""Live sandbox smoke test for the Assinafy Python SDK.

Required environment variables:
    ASSINAFY_API_KEY
    ASSINAFY_ACCOUNT_ID
    ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1
    ASSINAFY_TEST_EMAILS (comma-separated; one temporary signer per address)

Set ``ASSINAFY_SEND_TEST_NOTIFICATIONS=1`` to create an assignment for those
signers and exercise notification/resend operations. This opt-in sends email
and can consume sandbox credits.

``ASSINAFY_TEST_ACCOUNT_LIFECYCLE=1`` enables disposable account/logo CRUD.
``ASSINAFY_TEST_USER_PREFERENCES=1`` toggles one preference and restores its
original value in ``finally``.

Webhook mutation is disabled unless both ``ASSINAFY_WEBHOOK_TEST_URL`` and
``ASSINAFY_WEBHOOK_TEST_EMAIL`` are set and the existing subscription can be
restored exactly. The script never prints API payloads or environment values.
"""

from __future__ import annotations

import os
import sys
import time
from base64 import b64decode
from collections.abc import Callable
from typing import Any

from assinafy import ApiError, AssinafyClient, AssinafyError

SANDBOX_BASE_URL = "https://sandbox.assinafy.com.br/v1"


def step(label: str, fn: Callable[[], Any], failures: list[str]) -> Any:
    """Run one smoke step without logging response or exception values."""
    print(f"\n=== {label} ===")
    try:
        result = fn()
    except AssinafyError as err:
        print(f"  FAIL [{type(err).__name__}]")
        failures.append(label)
        return None
    except Exception as err:  # noqa: BLE001
        print(f"  FAIL [{type(err).__name__}]")
        failures.append(label)
        return None
    print("  OK")
    return result


def optional_404_step(label: str, fn: Callable[[], Any], failures: list[str]) -> Any:
    """Run a published operation that the sandbox may not have deployed yet."""
    print(f"\n=== {label} ===")
    try:
        result = fn()
    except ApiError as err:
        if err.status_code == 404:
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


def _validated_configuration() -> tuple[str, str, str, tuple[str, ...]]:
    api_key = os.environ.get("ASSINAFY_API_KEY")
    account_id = os.environ.get("ASSINAFY_ACCOUNT_ID")
    base_url = os.environ.get("ASSINAFY_BASE_URL")
    emails = tuple(
        email.strip()
        for email in os.environ.get("ASSINAFY_TEST_EMAILS", "").split(",")
        if email.strip()
    )
    if not api_key or not account_id or not emails:
        raise ValueError("missing required smoke-test environment")
    if not base_url or base_url.rstrip("/") != SANDBOX_BASE_URL:
        raise ValueError("smoke test requires the canonical HTTPS sandbox URL")
    for email in emails:
        _tagged_email(email, "validation")
    return api_key, account_id, SANDBOX_BASE_URL, emails


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
    """Return a valid transparent one-pixel PNG."""
    return b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF"
        "gAI/ScL7WQAAAABJRU5ErkJggg=="
    )


def _restorable_webhook(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    events = value.get("events")
    is_active = value.get("is_active")
    url = value.get("url")
    email = value.get("email")
    if not isinstance(events, list) or not isinstance(is_active, bool) or not url or not email:
        return None
    return {"events": list(events), "is_active": is_active, "url": url, "email": email}


def _resource_id(value: Any) -> str | None:
    resource_id = value.get("id") if isinstance(value, dict) else None
    return resource_id if isinstance(resource_id, str) and resource_id else None


def _tagged_email(email: str, tag: str) -> str:
    """Return a unique plus-address without logging or persisting the mailbox."""
    local, separator, domain = email.partition("@")
    if not separator or not local or not domain:
        raise ValueError("invalid smoke-test email")
    return f"{local}+{tag}@{domain}"


def _first_template_role_id(templates: Any) -> str | None:
    data = templates.get("data") if isinstance(templates, dict) else None
    template = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    roles = template.get("roles") if template else None
    role = roles[0] if isinstance(roles, list) and roles and isinstance(roles[0], dict) else None
    return _resource_id(role)


def _first_document_page_id(document: Any) -> str | None:
    pages = document.get("pages") if isinstance(document, dict) else None
    page = pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], dict) else None
    return _resource_id(page)


def _send_document_token(client: AssinafyClient, document_id: str, email: str) -> dict[str, Any]:
    """Try the current OpenAPI body, then the still-deployed legacy body."""
    try:
        return client.documents.send_token(document_id, email=email)
    except ApiError as err:
        if err.status_code not in {400, 422}:
            raise
        return client.documents.send_token(document_id, email, "email")


def main() -> int:
    try:
        api_key, account_id, base_url, test_emails = _validated_configuration()
        webhook_opt_in = _webhook_opt_in()
        send_test_notifications = _opt_in("ASSINAFY_SEND_TEST_NOTIFICATIONS")
        test_account_lifecycle = _opt_in("ASSINAFY_TEST_ACCOUNT_LIFECYCLE")
        test_user_preferences = _opt_in("ASSINAFY_TEST_USER_PREFERENCES")
    except ValueError:
        print("Unsafe or incomplete live-smoke configuration", file=sys.stderr)
        return 2

    failures: list[str] = []
    signer_ids: list[str] = []
    signer_emails: list[str] = []
    tag_id: str | None = None
    field_id: str | None = None
    document_id: str | None = None
    webhook_restore: dict[str, Any] | None = None
    webhook_mutation_attempted = False
    temporary_account_id: str | None = None
    preference_restore: dict[str, bool] | None = None
    client = AssinafyClient(api_key=api_key, account_id=account_id, base_url=base_url)

    try:
        # Read-only endpoints first.
        step("accounts.list()", lambda: client.accounts.list(), failures)
        step("accounts.get()", lambda: client.accounts.get(), failures)
        step("accounts.theme()", lambda: client.accounts.theme(), failures)
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
                step(
                    "users.update_notification_preferences()",
                    lambda: client.users.update_notification_preferences(
                        {"DocumentCompleted": not original}
                    ),
                    failures,
                )
        elif not test_user_preferences:
            print("\n=== user preference mutation ===\n  SKIP [explicit opt-in not configured]")

        step("documents.statuses()", lambda: client.documents.statuses(), failures)
        step("fields.list_types()", lambda: client.fields.list_types(), failures)
        step("webhooks.list_event_types()", lambda: client.webhooks.list_event_types(), failures)
        step(
            "documents.list(per_page=5)",
            lambda: client.documents.list({"per_page": 5}),
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
        if template_id:
            step("templates.get(real id)", lambda: client.templates.get(template_id), failures)
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

        if webhook_opt_in:
            webhook_restore = _restorable_webhook(original_webhook)
            if webhook_restore is None:
                print("\n=== webhook mutation ===\n  SKIP [original subscription not restorable]")
            else:
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
            print("\n=== webhook mutation ===\n  SKIP [explicit opt-in not configured]")

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

        # Write flow. IDs are captured immediately and cleaned only in finally.
        timestamp = int(time.time())
        if test_account_lifecycle:
            account = step(
                "accounts.create() disposable account",
                lambda: client.accounts.create(f"SDK Smoke {timestamp}"),
                failures,
            )
            temporary_account_id = _resource_id(account)
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
                lambda email=tagged_email: client.signers.create(
                    {"full_name": "SDK Smoke Test", "email": email}
                ),
                failures,
            )
            signer_id = _resource_id(signer)
            if signer_id:
                signer_ids.append(signer_id)
                signer_emails.append(tagged_email)

        primary_signer_id = signer_ids[0] if signer_ids else None
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

        tag_name = f"sdk-smoke-{timestamp}"
        tag = step(
            "tags.create()",
            lambda: client.tags.create({"name": tag_name, "color": "3366ff"}),
            failures,
        )
        tag_id = _resource_id(tag)
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
        field_id = _resource_id(field)
        if field_id:
            step("fields.get()", lambda: client.fields.get(field_id), failures)
            step(
                "fields.update() sets a regex",
                lambda: client.fields.update(field_id, {"regex": "^[0-9]+$"}),
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
                "fields.validate()",
                lambda: client.fields.validate(field_id, "123"),
                failures,
            )
            step(
                "fields.validate_multiple()",
                lambda: client.fields.validate_multiple([{"field_id": field_id, "value": "123"}]),
                failures,
            )

        document = step(
            "documents.upload()",
            lambda: client.documents.upload(
                {"buffer": _make_minimal_pdf(), "file_name": "sdk-smoke.pdf"}
            ),
            failures,
        )
        document_id = _resource_id(document)
        if document_id:
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
            ready_document = step(
                "documents.wait_until_ready()",
                lambda: client.documents.wait_until_ready(document_id, timeout=60),
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
                assignment_id = _resource_id(assignment)
                if assignment_id and primary_signer_id:
                    step(
                        "documents.send_token() sends test OTP",
                        lambda: _send_document_token(client, document_id, signer_emails[0]),
                        failures,
                    )
                    step(
                        "signer_documents.download() public artifact",
                        lambda: client.signer_documents.download(
                            primary_signer_id, document_id, artifact_name="original"
                        ),
                        failures,
                    )
                    step(
                        "assignments.reset_expiration()",
                        lambda: client.assignments.reset_expiration(
                            document_id, assignment_id, "2031-01-31T00:00:00Z"
                        ),
                        failures,
                    )
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
            role_id = _first_template_role_id(templates)
            if role_id:
                step(
                    "documents.estimate_cost_from_template()",
                    lambda: client.documents.estimate_cost_from_template(
                        template_id, [{"role_id": role_id}]
                    ),
                    failures,
                )
    except Exception as err:  # noqa: BLE001
        print(f"\n=== smoke execution ===\n  FAIL [{type(err).__name__}]")
        failures.append("smoke execution")
    finally:
        if webhook_mutation_attempted and webhook_restore is not None:
            step(
                "webhooks.register() restores original subscription",
                lambda: client.webhooks.register(webhook_restore),
                failures,
            )
        if preference_restore is not None:
            step(
                "users.update_notification_preferences() restores original",
                lambda: client.users.update_notification_preferences(preference_restore),
                failures,
            )
        if document_id:
            step(
                "documents.delete() cleanup",
                lambda: client.documents.delete(document_id),
                failures,
            )
        if field_id:
            step("fields.delete() cleanup", lambda: client.fields.delete(field_id), failures)
        if tag_id:
            step("tags.delete() cleanup", lambda: client.tags.delete(tag_id, force=True), failures)
        for signer_id in reversed(signer_ids):
            step(
                "signers.delete() cleanup",
                lambda current_id=signer_id: client.signers.delete(current_id),
                failures,
            )
        if temporary_account_id:
            step(
                "accounts.delete() disposable account cleanup",
                lambda: client.accounts.delete(temporary_account_id),
                failures,
            )
        try:
            client.close()
        except Exception as err:  # noqa: BLE001
            print(f"\n=== client.close() ===\n  FAIL [{type(err).__name__}]")
            failures.append("client.close()")

    if failures:
        print("\nLive smoke failed; see step labels above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
