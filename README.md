# Assinafy Python SDK

Python SDK for the [Assinafy API](https://api.assinafy.com.br/v1/docs).

The SDK is synchronous, uses `httpx`, and covers all 89 operations currently
published by Assinafy: accounts, users, authentication, documents, signers,
signer documents, assignments, field definitions, templates, tags, and
webhooks. Endpoint docstrings identify the published verb/path and request /
unwrapped-response shape; shared resource shapes are documented once and
referenced by methods that return them.

## Requirements

- Python 3.10+
- `httpx` (installed automatically)

## Installation

```bash
pip install assinafy
```

## Quick Start

```python
import os
from assinafy import AssinafyClient

with AssinafyClient(
    api_key=os.environ["ASSINAFY_API_KEY"],
    account_id=os.environ["ASSINAFY_ACCOUNT_ID"],
    webhook_secret=os.environ.get("ASSINAFY_WEBHOOK_SECRET"),
) as client:
    result = client.upload_and_request_signatures(
        source={"file_path": "./contract.pdf"},
        signers=[
            {"full_name": "John Doe", "email": "john@example.com"},
            {"full_name": "Jane Smith", "email": "jane@example.com"},
        ],
        message="Please sign this contract",
    )

    print(result["document"]["id"])
```

`upload_and_request_signatures` chains three calls (upload, create each signer,
create the assignment) and is not transactional — a failure partway through
does not roll back what already succeeded. It also accepts `wait_timeout` /
`wait_poll_interval` to override the default document-readiness poll.
Phone-only signers use WhatsApp verification and notification, which requires
account availability and consumes credits; use `assignments.estimate_cost()`
when the current cost must be known before sending.

## Document signing flow

Use the individual resources when you need explicit IDs, cost estimation, or
cleanup control:

```python
import os
from assinafy import AssinafyClient

with AssinafyClient(
    api_key=os.environ["ASSINAFY_API_KEY"],
    account_id=os.environ["ASSINAFY_ACCOUNT_ID"],
) as client:
    # 1. Create or reuse the people who will sign.
    signer = client.signers.find_by_email("signer@example.com")
    if signer is None:
        signer = client.signers.create({
            "full_name": "Example Signer",
            "email": "signer@example.com",
        })

    # 2. Upload and wait until field/signature metadata is ready.
    document = client.documents.upload({"file_path": "./contract.pdf"})
    document = client.documents.wait_until_ready(document["id"])

    # 3. Estimate before creating the notification-producing assignment.
    estimate = client.assignments.estimate_cost(document["id"], {
        "method": "virtual",
        "signers": [{
            "verification_method": "Email",
            "notification_methods": ["Email"],
        }],
    })

    # 4. Request the signature. This can send a real notification.
    assignment = client.assignments.create(document["id"], {
        "method": "virtual",
        "signers": [{
            "id": signer["id"],
            "verification_method": "Email",
            "notification_methods": ["Email"],
            "step": 1,
        }],
        "message": "Please review and sign.",
        "expires_at": "2030-12-31T23:59:59Z",
    })

    # 5. Read progress and download the completed artifact when certificated.
    document = client.documents.get(document["id"])
    if document["status"] == "certificated":
        signed_pdf = client.documents.download(document["id"], "certificated")
```

Keep the returned document, signer, and assignment IDs. Delete only disposable
resources you created, and do so in reverse dependency order.

## Authentication

Prefer `api_key`; it is sent as the documented `X-Api-Key` header. `token` sends
`Authorization: Bearer <token>` for legacy/user-token flows. If both are
provided, the API key takes precedence.
The SDK omits both credentials on routes whose OpenAPI security is public or
signer-access-code-only.
Every outbound production and sandbox request uses
`User-Agent: Assinafy-Python-SDK/v<package-version>`.

```python
client = AssinafyClient(api_key="k_xxx", account_id="acc_xxx")
client = AssinafyClient(token="jwt_xxx", account_id="acc_xxx")
```

Unauthenticated clients are allowed for public and signer-access-code endpoints:

```python
public_client = AssinafyClient()
session = public_client.authentication.login("user@example.com", "password")
```

### Configuration

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | str | None | Sent as `X-Api-Key`. |
| `token` | str | None | Sent as `Authorization: Bearer <token>`. |
| `account_id` | str | None | Default workspace/account ID for account-scoped methods. |
| `base_url` | str | `https://api.assinafy.com.br/v1` | API base URL. |
| `webhook_secret` | str | None | Secret used by `WebhookVerifier`. |
| `timeout` | float | `30.0` | Request timeout in seconds. |
| `logger` | object | no-op | Object with `debug/info/warning/error` methods. |

## Resources

### Authentication

```python
client.authentication.login("user@example.com", "password")
client.authentication.social_login("google", "provider-token", True)
client.authentication.link_social_login("google", "provider-token")
client.authentication.create_api_key("password")
client.authentication.get_api_key()
client.authentication.delete_api_key()
client.authentication.change_password("user@example.com", "old", "new")
client.authentication.request_password_reset("user@example.com")
client.authentication.reset_password("user@example.com", "new", token="reset-token")
```

### Accounts

```python
accounts = client.accounts.list()
created_account = client.accounts.create("SDK Example Workspace")
created_id = created_account["id"]
created_account = client.accounts.update(
    {"notification_sender_type": "Account"}, created_id
)
created_account = client.accounts.get(created_id)
created_account = client.accounts.update({"name": "SDK Example Updated"}, created_id)
theme = client.accounts.theme(created_id)
stats = client.accounts.stats("monthly", account_id=created_id)
daily_stats = client.accounts.stats("daily", "2026-08", account_id=created_id)
client.accounts.upload_logo({"file_path": "./logo.png"}, created_id)
logo_bytes = client.accounts.download_logo(created_id)
client.accounts.delete_logo(created_id)

# Delete only the disposable workspace created above.
client.accounts.delete(created_id)
```

`delete()` targets the supplied account ID (or the client's default) and makes
`force` keyword-only so a positional ID can never be mistaken for the force
flag. Use `force=True` only when you intentionally want to cancel that
account's active paid subscription as part of deletion. Creating the account
first and setting `notification_sender_type` with `update()` is supported
across deployed API versions.

### Current User

```python
user = client.users.me()
stats = client.users.stats("monthly")
preferences = client.users.notification_preferences()
preferences = client.users.update_notification_preferences({
    "DocumentCompleted": True,
    "SignerDeclined": True,
})
```

The live smoke script reports routes unavailable in the configured sandbox as
explicit skips.

### Documents

```python
doc = client.documents.upload({"file_path": "./contract.pdf"})
doc = client.documents.upload({"buffer": pdf_bytes, "file_name": "contract.pdf"})

client.documents.statuses()
client.documents.list({"page": 1, "per_page": 20, "tags": "tag-id", "sort": "-updated_at"})
client.documents.search({"search": "nda", "status": "metadata_ready"})  # lightweight, compact
client.documents.get(doc["id"])
client.documents.rename(doc["id"], "Service agreement.pdf")  # before signing starts
client.documents.activities(doc["id"])
client.documents.wait_until_ready(doc["id"])
client.documents.download(doc["id"], "certificated")
client.documents.download(doc["id"], "pades")  # ICP-Brasil certificate artifact
client.documents.thumbnail(doc["id"])
client.documents.download_page(doc["id"], page_id)
client.documents.verify(signature_hash)
client.documents.public_info(doc["id"])
# Choose one form; each call sends a real token.
client.documents.send_token(doc["id"], email="signer@example.com")
# Legacy body alternative: client.documents.send_token(doc["id"], "signer@example.com", "email")
client.documents.list_tags(doc["id"])
client.documents.replace_tags(doc["id"], [tag_id_a, tag_id_b])
client.documents.append_tags(doc["id"], [tag_id_c])
client.documents.detach_tag(doc["id"], tag_id)
client.documents.delete(doc["id"])
```

Uploads follow the documented multipart shape and are locally limited to PDF files up to 25 MB.

### Templates

```python
templates = client.templates.list({"search": "NDA", "per_page": 20})
template = client.templates.get(template_id)

client.documents.create_from_template(
    template_id,
    [{"role_id": "role-id", "id": signer_id, "verification_method": "Email"}],
    {"name": "NDA - John Doe", "message": "Please sign."},
)

client.documents.estimate_cost_from_template(
    template_id,
    [{"role_id": "role-id", "verification_method": "Email"}],
)
```

### Tags

```python
tags = client.tags.list({"search": "contract"})
tag = client.tags.create({"name": "Contracts", "color": "ff8800"})
client.tags.update(tag["id"], {"name": "Sales Contracts"})
client.tags.update(tag["id"], {"color": None})  # clears color
client.tags.delete(tag["id"])
# If the tag is attached, use this instead of the prior line:
# client.tags.delete(tag["id"], force=True)
```

### Signers

```python
signer = client.signers.create({
    "full_name": "John Doe",
    "email": "john@example.com",
})

client.signers.create({
    "full_name": "Jane Doe",
    "whatsapp_phone_number": "+5548999990000",
})

client.signers.get(signer["id"])
client.signers.list({"search": "john", "per_page": 50})
client.signers.update(signer["id"], {"full_name": "Johnny Doe"})
client.signers.find_by_email("john@example.com")
client.signers.delete(signer["id"])
```

Signer-access-code endpoints:

```python
client.signers.get_self(signer_access_code)
client.signers.accept_terms(signer_access_code)
client.signers.verify_code(signer_access_code, "123456")
# verify_email(...) remains as a backward-compatible alias.
client.signers.confirm_data(
    document_id,
    signer_access_code,
    {"full_name": "John Doe", "email": "john@example.com", "government_id": "00000000000"},
)
client.signers.upload_signature(signer_access_code, png_bytes, "signature")
# Alternative: client.signers.upload_signature(signer_access_code, png_bytes, reuse=True)
client.signers.download_signature(signer_access_code, "signature")
```

### Assignments

```python
client.assignments.list({"page": 1, "per_page": 20})  # assignments for the account
client.assignments.estimate_cost(document_id, {"signers": [{"verification_method": "Email"}]})

assignment = client.assignments.create(document_id, {
    "method": "virtual",
    "signers": [
        # `step` controls sequential signing order (signers sharing a step sign
        # in parallel; the next step is notified once the previous one finishes).
        {"id": signer_a["id"], "verification_method": "Email", "step": 1},
        {"id": signer_b["id"], "verification_method": "Email", "step": 2},
    ],
    "message": "Please review and sign",
    "expires_at": "2026-12-31T00:00:00Z",
})

client.assignments.reset_expiration(document_id, assignment["id"], "2027-01-31T00:00:00Z")
client.assignments.estimate_resend_cost(document_id, assignment["id"], signer["id"])
client.assignments.resend_notification(document_id, assignment["id"], signer["id"])
# Alternative: client.assignments.reset_expiration(document_id, assignment["id"], None)
client.assignments.whatsapp_notifications(document_id, assignment["id"])
```

For a `collect` assignment, `entries` places reusable fields on a page:

```python
collect_payload = {
    "method": "collect",
    "signers": [{
        "id": signer["id"],
        "verification_method": "Email",
        "notification_methods": ["Email"],
        "step": 1,
    }],
    "entries": [{
        "page_id": page["id"],
        "fields": [{
            "signer_id": signer["id"],
            "field_id": field["id"],
            "display_settings": {
                "left": 69,
                "top": 282,
                "width": 421,
                "height": 45.86,
                "fontSize": 18,
                "fontFamily": "Arial",
                "backgroundColor": "#D5EBFF",
            },
        }],
    }],
}
```

The five numeric display fields are required 150-DPI page-image pixel values;
the rectangle must remain within the selected page. `fontFamily` and
`backgroundColor` are optional.

`resend_notification()` sends a real message and charges the notification
channel again; call `estimate_resend_cost()` first when cost must be known.

Signer-facing assignment endpoints:

```python
client.assignments.get_for_signer(signer_access_code)
# Virtual assignment: confirm signer data, then submit the empty item list.
client.signers.confirm_data(document_id, signer_access_code, {"full_name": "Example Signer"})
client.assignments.sign(document_id, assignment_id, [], signer_access_code)
# Collect assignment: submit each completed item.
client.assignments.sign(
    document_id,
    assignment_id,
    [{"itemId": "item-1", "fieldId": "field-1", "pageId": "page-1", "value": "John Doe"}],
    signer_access_code,
)
# Mutually exclusive alternative:
# client.assignments.decline(document_id, assignment_id, "I do not agree.", signer_access_code)
```

`DigitalCertificate` is accepted as an assignment `verification_method`, and
the `pades` artifact is downloadable. Certificate start/complete calls are not
part of the published API contract, so the SDK leaves that security-sensitive
step to the Assinafy-hosted signing flow.

### Signer Documents

```python
client.signer_documents.current(signer_id, signer_access_code)
client.signer_documents.list(signer_id, signer_access_code, {"page": 1, "per_page": 20})
client.signer_documents.search(signer_id, signer_access_code, "contract")  # lightweight, compact
client.signer_documents.sign_multiple(["doc-1", "doc-2"], signer_access_code)
# Mutually exclusive alternative:
# client.signer_documents.decline_multiple(["doc-1"], "Unfavorable terms.", signer_access_code)
client.signer_documents.download(signer_id, document_id, artifact_name="original")
```

The download route is public. Its optional `signer_access_code` argument is
available for deployments that require it.

### Field Definitions

```python
field = client.fields.create({"type": "text", "name": "CPF"})
client.fields.list({"include_standard": True})
client.fields.get(field["id"])
client.fields.update(field["id"], {"name": "CPF updated"})
client.fields.validate(field["id"], "000.000.000-00", signer_access_code=signer_access_code)
client.fields.validate_multiple(
    [{"field_id": field["id"], "value": "000.000.000-00"}],  # synthetic CPF placeholder
    signer_access_code=signer_access_code,
)
client.fields.list_types()
client.fields.delete(field["id"])
```

### Webhooks

```python
client.webhooks.get()
client.webhooks.list_event_types()
client.webhooks.list_dispatches({"delivered": False, "page": 1, "per_page": 20})

# Mutating calls affect the workspace's single subscription or redeliver an
# existing event. Snapshot and restore the subscription around test changes.
# client.webhooks.register({
#     "url": "https://example.com/webhooks/assinafy",
#     "email": "admin@example.com",
#     "events": ["document_ready", "signer_signed_document"],
#     "is_active": True,
# })
# client.webhooks.inactivate()
# client.webhooks.retry_dispatch(dispatch_id)
```

A workspace has a single webhook subscription. There is no documented `DELETE`
endpoint — call `inactivate()` to stop delivery (it preserves the configured
URL/events) and `register()` again to re-enable.

### Webhooks: Parsing Payloads

Every webhook body shares the documented envelope: `id`, `event`, `message`,
`payload` (event-specific params), `origin`, `created_at`, `subject` (the entity
that acted), `object` (the entity acted on), and `account_id`.

```python
raw_body = request.get_data()

event = client.webhook_verifier.extract_event(raw_body)
event_type = client.webhook_verifier.get_event_type(event)      # e.g. "document_ready"
params = client.webhook_verifier.get_event_payload(event)       # event-specific params
subject = client.webhook_verifier.get_event_subject(event)      # actor (+ "type")
target = client.webhook_verifier.get_event_object(event)        # target (+ "type")
# get_event_data(event) is a backward-compatible alias of get_event_object(event)
```

#### Signature verification

The documented Delivery Contract specifies the HTTP method, `Content-Type`,
retry, and circuit-breaker behavior, but **does not define any signature header
or shared-secret scheme**. `verify()` is provided only for accounts that have
separately arranged an HMAC-SHA256 scheme with Assinafy:

```python
signature = request.headers.get("X-Assinafy-Signature", "")
if not client.webhook_verifier.verify(raw_body, signature):
    return "Invalid signature", 401
```

## Query Parameters

The SDK accepts Pythonic aliases for documented hyphenated query parameters. For example, `per_page` is sent as `per-page`, and `signer_access_code` is sent as `signer-access-code`.

## Response Payloads

JSON endpoints normally return `{"status": 200, "message": "", "data": ...}`;
the SDK returns `data`. No-data operations return `None` or preserve their
small `{"status", "message"}` envelope for backward compatibility, as stated
in each method's docstring. Binary methods return `bytes`; paginated methods
return `{"data": [...], "meta": {"current_page", "per_page", "total",
"last_page"}}` using the API's pagination headers.

The complete stable top-level resource payloads are:

```json
{
  "Account": {
    "resource": "account", "id": "account-id", "name": "Acme Inc.",
    "primary_color": "aabbcc", "secondary_color": "112233",
    "notification_sender_type": "User", "roles": ["owner"],
    "is_delete_allowed": true, "created_at": "2026-06-03T03:54:16Z"
  },
  "User": {
    "id": "user-id", "name": "Example User", "email": "user@example.com",
    "telephone": null, "government_id": null, "is_email_verified": true,
    "has_accepted_terms": true, "created_at": "2026-06-03T03:54:16Z",
    "to_be_deleted_at": null
  },
  "Signer": {
    "resource": "signer", "id": "signer-id", "full_name": "Example Signer",
    "email": "signer@example.com", "whatsapp_phone_number": null,
    "has_accepted_terms": false
  },
  "Document": {
    "resource": "document", "id": "document-id", "account_id": "account-id",
    "template_id": null, "name": "contract.pdf", "status": "metadata_ready",
    "artifacts": {"original": "https://api.example/document/original"},
    "is_closed": false, "signing_url": "https://app.example/sign/document-id",
    "decline_reason": null, "declined_by": null, "tags": [],
    "assignment": null, "pages": [], "created_at": "2026-06-03T03:54:16Z",
    "updated_at": "2026-06-03T03:54:17Z"
  },
  "Assignment": {
    "resource": "assignment", "id": "assignment-id",
    "sender_email": "sender@example.com", "method": "virtual",
    "expires_at": null, "message": null,
    "signers": [{
      "resource": "signer", "id": "signer-id", "full_name": "Example Signer",
      "email": "signer@example.com", "whatsapp_phone_number": null,
      "has_accepted_terms": false, "verification_method": "Email",
      "notification_methods": ["Email"], "step": 1, "notified": true,
      "completed": false, "notification_history": [{
        "event": "signature_request", "status": "sent", "error_code": null,
        "error_message": null, "sent_at": "2026-08-26T12:00:00Z",
        "failed_at": null
      }]
    }],
    "copy_receivers": [],
    "items": [{
      "id": "item-id",
      "page": {"id": "page-id", "number": 1, "height": 2100,
               "width": 1275, "download_url": "https://api.example/page"},
      "signer": {"id": "signer-id", "full_name": "Example Signer",
                 "email": "signer@example.com"},
      "field": {"id": "field-id", "name": "Signature", "type": "signature"},
      "display_settings": {"left": 69, "top": 282, "width": 421,
                           "height": 45.86, "fontFamily": "Arial",
                           "fontSize": 18, "backgroundColor": "#D5EBFF"},
      "value": null, "completed": false
    }],
    "summary": {"signer_count": 1, "completed_count": 0,
                "signers": [{"id": "signer-id", "full_name": "Example Signer",
                             "email": "signer@example.com", "completed": false}]},
    "signing_urls": [{"signer_id": "signer-id",
                      "url": "https://api.example/sign/document-id"}]
  },
  "CostEstimate": {
    "documents": 1, "credits": 0.45, "needs_extra_document": false,
    "extra_document_cost": 0, "total_credits": 0.45,
    "breakdown": [{"code": "NotificationWhatsapp",
                   "name": "Whatsapp Notification", "cost": 0.45,
                   "quantity": 1, "unit_cost": 0.45}],
    "document_balance": 10, "credit_balance": 0,
    "has_sufficient_resources": true, "blocking_reason": null, "message": null
  },
  "Field": {
    "resource": "field", "id": "field-id", "name": "CPF", "type": "text",
    "regex": null, "is_pre_defined": false, "is_active": true,
    "is_required": true, "is_standard": false, "is_read_only": false,
    "is_visible": true
  },
  "Tag": {
    "resource": "tag", "id": "tag-id", "name": "Contracts", "color": null,
    "created_at": "2026-06-03T03:54:16Z",
    "updated_at": "2026-06-03T03:54:17Z"
  },
  "WebhookSubscription": {
    "events": ["document_ready"], "is_active": true,
    "url": "https://example.com/webhooks/assinafy", "email": "ops@example.com",
    "updated_at": "2026-06-03T03:54:17Z"
  }
}
```

Field resource values are returned verbatim. The documented value is `"field"`;
`"field_definition"` is also supported.

Template, notification-preference, KPI, verification, webhook-dispatch, and
operation-specific contracts are documented beside their public methods;
methods returning shared resources reference the canonical shapes above.
The SDK preserves extra server fields so additive API changes remain usable.

## Errors

SDK validation, transport, HTTP, and response-shape failures raise a subclass
of `AssinafyError`.

```python
from assinafy import ApiError, AssinafyError, NetworkError, ValidationError

try:
    client.documents.upload({"file_path": "./contract.pdf"})
except ValidationError as err:
    print("Validation failed:", err.errors)
except ApiError as err:
    print(f"API error {err.status_code}:", err.response_data)
except NetworkError as err:
    print("Network error:", err)
except AssinafyError as err:
    print("SDK error:", err, err.context)
```

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest --cov=assinafy --cov-branch --cov-fail-under=90 --cov-report=term-missing
python -m mypy src scripts/live_smoke.py
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

### Live smoke test

For CI-safe, non-mutating coverage (no test email required):

```bash
ASSINAFY_API_KEY=... \
ASSINAFY_ACCOUNT_ID=... \
ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1 \
ASSINAFY_READ_ONLY=1 \
python scripts/live_smoke.py
```

For the disposable write flow:

```bash
ASSINAFY_API_KEY=... \
ASSINAFY_ACCOUNT_ID=... \
ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1 \
ASSINAFY_TEST_EMAILS=first@example.com,second@example.com \
ASSINAFY_SEND_TEST_NOTIFICATIONS=1 \
ASSINAFY_TEST_ACCOUNT_LIFECYCLE=1 \
ASSINAFY_TEST_USER_PREFERENCES=1 \
python scripts/live_smoke.py
```

The script refuses production and missing base URLs. It confirms read
endpoints, signer/tag/field CRUD (including
clearing a field's regex), template lookup and cost estimation, document
upload, document tagging, ``wait_until_ready`` polling, cost estimation, and
cleanup end-to-end. Every successfully returned resource ID is captured and
its cleanup is attempted in a `finally` block. Webhook mutation is skipped
unless an explicit test endpoint is supplied; when enabled, the prior
single-workspace subscription is restored.
The notification opt-in sends real sandbox emails and may consume sandbox
credits; omit it for CRUD-only smoke coverage. Account and user-preference
mutations are separate opt-ins and are cleaned/restored in `finally`.

### Release checklist

1. Bump `src/assinafy/_version.py` and add user-facing release notes to
   `CHANGELOG.md`.
2. Run the development gates above, install release tooling with
   `python -m pip install build twine`, then run `python -m build` and
   `python -m twine check dist/*`.
3. Push the GitLab source and verify that the branch and CI result reached the
   GitHub mirror.
4. Create and push an annotated `v<version>` tag matching `__version__`.
5. Approve the protected `pypi` environment and verify Trusted Publishing
   provenance after release.

## License

MIT
