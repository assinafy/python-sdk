# Assinafy Python SDK

Python SDK for the [Assinafy API](https://api.assinafy.com.br/v1/docs).

The SDK is synchronous, uses `httpx`, and covers every documented API group:
authentication, documents, signers, signer documents, assignments, field
definitions, templates, tags, and webhooks. Each public method's docstring names the
exact HTTP verb and endpoint it calls, so you can cross-reference against the
official docs in one step.

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

client = AssinafyClient(
    api_key=os.environ["ASSINAFY_API_KEY"],
    account_id=os.environ["ASSINAFY_ACCOUNT_ID"],
    webhook_secret=os.environ.get("ASSINAFY_WEBHOOK_SECRET"),
)

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

## Authentication

Prefer `api_key`; it is sent as the documented `X-Api-Key` header. `token` sends `Authorization: Bearer <token>` for legacy/user-token flows.

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
client.authentication.create_api_key("password")
client.authentication.get_api_key()
client.authentication.delete_api_key()
client.authentication.change_password("user@example.com", "old", "new")
client.authentication.request_password_reset("user@example.com")
client.authentication.reset_password("user@example.com", "new", token="reset-token")
```

### Documents

```python
doc = client.documents.upload({"file_path": "./contract.pdf"})
doc = client.documents.upload({"buffer": pdf_bytes, "file_name": "contract.pdf"})

client.documents.statuses()
client.documents.list({"page": 1, "per_page": 20, "tags": "tag-id", "sort": "-updated_at"})
client.documents.get(doc["id"])
client.documents.activities(doc["id"])
client.documents.wait_until_ready(doc["id"])
client.documents.download(doc["id"], "certificated")
client.documents.thumbnail(doc["id"])
client.documents.download_page(doc["id"], page_id)
client.documents.verify(signature_hash)
client.documents.public_info(doc["id"])
client.documents.send_token(doc["id"], "signer@example.com", "email")
client.documents.list_tags(doc["id"])
client.documents.replace_tags(doc["id"], ["Contracts", "2026-Q1"])
client.documents.append_tags(doc["id"], ["Urgent"])
client.documents.detach_tag(doc["id"], tag_id)
client.documents.delete(doc["id"])
```

Uploads follow the documented multipart shape and are locally limited to PDF files up to 25 MB.

### Templates

```python
templates = client.templates.list({"search": "NDA", "tags": "tag-id", "per_page": 20})
template = client.templates.get(template_id)

client.documents.create_from_template(
    template_id,
    [{"role_id": "role-id", "id": signer_id, "verification_method": "Email"}],
    {"name": "NDA - John Doe", "message": "Please sign."},
)

client.documents.estimate_cost_from_template(
    template_id,
    [{"role_id": "role-id", "id": signer_id}],
)
```

### Tags

```python
tags = client.tags.list({"search": "contract", "per_page": 20})
tag = client.tags.create({"name": "Contracts", "color": "ff8800"})
client.tags.update(tag["id"], {"name": "Sales Contracts"})
client.tags.update(tag["id"], {"color": None})  # clears color
client.tags.delete(tag["id"])
client.tags.delete(tag["id"], force=True)
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
client.signers.delete(signer["id"])
client.signers.find_by_email("john@example.com")
```

Signer-access-code endpoints:

```python
client.signers.get_self(signer_access_code)
client.signers.accept_terms(signer_access_code)
client.signers.verify_email(signer_access_code, "123456")
client.signers.confirm_data(
    document_id,
    signer_access_code,
    {"email": "john@example.com", "has_accepted_terms": True},
)
client.signers.upload_signature(signer_access_code, png_bytes, "signature")
client.signers.download_signature(signer_access_code, "signature")
```

### Assignments

```python
client.assignments.estimate_cost(document_id, {"signers": [{"verification_method": "Email"}]})

assignment = client.assignments.create(document_id, {
    "method": "virtual",
    "signers": [{"id": signer["id"]}],
    "message": "Please review and sign",
    "expires_at": "2026-12-31T00:00:00Z",
})

client.assignments.reset_expiration(document_id, assignment["id"], "2027-01-31T00:00:00Z")
client.assignments.resend_notification(document_id, assignment["id"], signer["id"])
client.assignments.estimate_resend_cost(document_id, assignment["id"], signer["id"])
client.assignments.whatsapp_notifications(document_id, assignment["id"])
```

Signer-facing assignment endpoints:

```python
client.assignments.get_for_signer(signer_access_code)
client.assignments.sign(document_id, assignment_id, [{"itemId": "item-1"}], signer_access_code)
client.assignments.decline(document_id, assignment_id, "I do not agree.", signer_access_code)
```

### Signer Documents

```python
client.signer_documents.current(signer_id, signer_access_code)
client.signer_documents.list(signer_id, signer_access_code, {"status": "pending_signature"})
client.signer_documents.sign_multiple(["doc-1", "doc-2"], signer_access_code)
client.signer_documents.decline_multiple(["doc-1"], "Unfavorable terms.", signer_access_code)
client.signer_documents.download(signer_id, document_id, signer_access_code, "original")
```

### Field Definitions

```python
field = client.fields.create({"type": "text", "name": "CPF"})
client.fields.list({"include_standard": True})
client.fields.get(field["id"])
client.fields.update(field["id"], {"name": "CPF updated"})
client.fields.validate(field["id"], "400.676.228-36", signer_access_code=signer_access_code)
client.fields.validate_multiple(
    [{"field_id": field["id"], "value": "400.676.228-36"}],
    signer_access_code=signer_access_code,
)
client.fields.list_types()
client.fields.delete(field["id"])
```

### Webhooks

```python
client.webhooks.register({
    "url": "https://example.com/webhooks/assinafy",
    "email": "admin@example.com",
    "events": ["document_ready", "signer_signed_document"],
})

client.webhooks.get()
client.webhooks.inactivate()
client.webhooks.delete()
client.webhooks.list_event_types()
client.webhooks.list_dispatches({"delivered": False, "page": 1, "per_page": 20})
client.webhooks.retry_dispatch(dispatch_id)
```

### Webhook Verification

```python
signature = request.headers.get("X-Assinafy-Signature", "")
raw_body = request.get_data()

if not client.webhook_verifier.verify(raw_body, signature):
    return "Invalid signature", 401

event = client.webhook_verifier.extract_event(raw_body)
event_type = client.webhook_verifier.get_event_type(event)
event_data = client.webhook_verifier.get_event_data(event)
```

## Query Parameters

The SDK accepts Pythonic aliases for documented hyphenated query parameters. For example, `per_page` is sent as `per-page`, and `signer_access_code` is sent as `signer-access-code`.

## Errors

The SDK raises typed errors; every failure raises a subclass of `AssinafyError`.

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
pip install -e ".[dev]"
pytest
mypy src
ruff check src tests
```

### Live smoke test

```bash
ASSINAFY_API_KEY=... ASSINAFY_ACCOUNT_ID=... python scripts/live_smoke.py
```

Hits the live API to confirm read endpoints, signer CRUD, document upload,
document tagging, tag CRUD, ``wait_until_ready`` polling, cost estimation, and
cleanup all work end-to-end.

## License

MIT
