# Assinafy Python SDK

Python SDK for the [Assinafy API](https://api.assinafy.com.br/v1/docs) — the
Brazilian electronic-signature platform.

The SDK is synchronous, built on `httpx`, and covers all 89 operations
currently published by Assinafy: accounts, users, authentication, documents,
signers, signer documents, assignments, field definitions, templates, tags, and
webhooks. Every public method names the verb and path it calls and documents
its request body and unwrapped response; shared resource shapes are documented
once and referenced by the methods that return them.

- [Requirements](#requirements)
- [Installation](#installation)
- [Authentication](#authentication)
  - [Client configuration](#client-configuration)
- [Quick start](#quick-start)
- [The signing lifecycle](#the-signing-lifecycle)
  - [1. Prepare the signers](#1-prepare-the-signers)
  - [2. Upload the document](#2-upload-the-document)
  - [3. Estimate the cost](#3-estimate-the-cost)
  - [4. Request the signatures](#4-request-the-signatures)
  - [5. The signer's side](#5-the-signers-side)
  - [6. Track progress](#6-track-progress)
  - [7. Download the signed document](#7-download-the-signed-document)
  - [Starting from a template instead](#starting-from-a-template-instead)
- [Resource reference](#resource-reference)
  - [Authentication resource](#authentication-resource)
  - [Accounts](#accounts)
  - [Current user](#current-user)
  - [Documents](#documents)
  - [Templates](#templates)
  - [Tags](#tags)
  - [Signers](#signers)
  - [Assignments](#assignments)
  - [Signer documents](#signer-documents)
  - [Field definitions](#field-definitions)
  - [Webhooks](#webhooks)
- [Query parameters](#query-parameters)
- [Response payloads](#response-payloads)
- [Errors](#errors)
- [Development](#development)
- [License](#license)

## Requirements

- Python 3.10+
- `httpx` (installed automatically)

## Installation

```bash
pip install assinafy
```

## Authentication

Prefer `api_key`; it is sent as the documented `X-Api-Key` header. `token`
sends `Authorization: Bearer <token>` for legacy/user-token flows. If both are
provided, the API key takes precedence.

```python
client = AssinafyClient(api_key="k_xxx", account_id="acc_xxx")
client = AssinafyClient(token="jwt_xxx", account_id="acc_xxx")
```

The SDK withholds both credentials on routes whose published security is
public or signer-access-code-only, so an API key is never sent to an endpoint
that does not expect one. Every outbound production and sandbox request uses
`User-Agent: Assinafy-Python-SDK/v<package-version>`.

Unauthenticated clients are allowed, for public and signer-access-code
endpoints:

```python
public_client = AssinafyClient()
session = public_client.authentication.login("user@example.com", "password")
```

### Client configuration

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | str | None | Sent as `X-Api-Key`. |
| `token` | str | None | Sent as `Authorization: Bearer <token>`. |
| `account_id` | str | None | Default workspace/account ID for account-scoped methods. |
| `base_url` | str | `https://api.assinafy.com.br/v1` | API base URL. |
| `webhook_secret` | str | None | Secret used by `WebhookVerifier`. |
| `timeout` | float | `30.0` | Request timeout in seconds. |
| `logger` | object | no-op | Object with `debug/info/warning/error` methods. |

Use `https://sandbox.assinafy.com.br/v1` as `base_url` to work against the
sandbox. `base_url` must carry only scheme, host, port, and path — the
constructor rejects a URL that embeds credentials (`https://user:pass@host/v1`,
which would silently replace your API key or token with HTTP Basic auth) or
that carries a query string or fragment (which would glue the request path into
the wrong URL component). Plaintext `http://` is rejected while `api_key` or
`token` is set unless the host is loopback, so a mistyped or misconfigured URL
cannot put your credentials on the wire in the clear. Credential-free clients
may use plaintext `http://` anywhere, which keeps local and LAN mock servers
usable.

The client is a context manager and holds an HTTP connection pool; use `with`
or call `close()` when you are finished.

## Quick start

`upload_and_request_signatures` runs the common case end to end:

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

It chains three calls — upload, create each signer, create the assignment — and
is **not transactional**: a failure partway through does not roll back what
already succeeded. It also accepts `wait_timeout` / `wait_poll_interval` to
override the default document-readiness poll. Phone-only signers use WhatsApp
verification and notification, which requires account availability and consumes
credits; use `assignments.estimate_cost()` when the cost must be known before
sending.

When you need explicit IDs, cost control, or cleanup, drive the same lifecycle
through the individual resources instead — that is what the next section walks
through.

## The signing lifecycle

A document goes from upload to a certified PDF in seven stages. Each stage
below is a real call you can run in order.

```python
import os
from assinafy import AssinafyClient

client = AssinafyClient(
    api_key=os.environ["ASSINAFY_API_KEY"],
    account_id=os.environ["ASSINAFY_ACCOUNT_ID"],
)
```

### 1. Prepare the signers

Signers are workspace-level records, reused across documents. Look one up
before creating a duplicate:

```python
signer = client.signers.find_by_email("signer@example.com")
if signer is None:
    signer = client.signers.create({
        "full_name": "Example Signer",
        "email": "signer@example.com",
    })
```

A signer needs `full_name` plus at least one contact channel: `email`, or
`whatsapp_phone_number` in E.164 form (`+5548999990000`). The channel you give
determines how that signer can be verified and notified in stage 4.

### 2. Upload the document

Uploads use the documented multipart shape and are limited locally to PDF files
up to 25 MB (the API additionally caps documents at 2000 pages):

```python
document = client.documents.upload({"file_path": "./contract.pdf"})
# or, from memory: client.documents.upload({"buffer": pdf_bytes, "file_name": "contract.pdf"})
```

The document lands in `uploaded` status while Assinafy renders page images and
extracts metadata. Wait for that to finish before placing fields or requesting
signatures:

```python
document = client.documents.wait_until_ready(document["id"])
```

`wait_until_ready` polls `documents.get` until the status reaches
`metadata_ready`, `pending_signature`, or `certificated`; it raises on a
terminal failure status and does not retry a `404`, which waiting can never
resolve. Rename the document here if you need to — the API locks the name once
an assignment exists:

```python
document = client.documents.rename(document["id"], "Service agreement.pdf")
```

### 3. Estimate the cost

Creating an assignment sends real notifications and consumes credits. Price it
first when the cost matters:

```python
estimate = client.assignments.estimate_cost(document["id"], {
    "method": "virtual",
    "signers": [{
        "verification_method": "Email",
        "notification_methods": ["Email"],
    }],
})

if not estimate["has_sufficient_resources"]:
    raise SystemExit(estimate["blocking_reason"])
```

The estimate body takes only pricing descriptors — the SDK strips signer IDs
from the wire, since they are not part of the estimate contract.

### 4. Request the signatures

A `virtual` assignment asks each signer for a signature with no field
placement. `step` controls signing order: signers sharing a step sign in
parallel, and the next step is notified once the previous one completes.

```python
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
```

A `collect` assignment additionally places reusable fields on specific pages,
using `entries`:

```python
page = document["pages"][0]
field = client.fields.list()["data"][0]

assignment = client.assignments.create(document["id"], {
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
})
```

`left`, `top`, `width`, `height`, and `fontSize` are required 150-DPI
page-image pixel values measured from the upper-left corner; width, height, and
font size must be positive and coordinates non-negative. The API does not clamp
out-of-bounds rectangles, so keep the placement inside the page's reported
`width`/`height`. `fontFamily` and `backgroundColor` are optional presentation
metadata.

`DigitalCertificate` is also accepted as a `verification_method`. It requires
the Digital Certificate feature, requires the signer to have a CPF or CNPJ in
`government_id`, must be alone in its signing step, and is charged 2 credits
per signer. The certificate start/complete calls are not part of the published
API contract, so the SDK leaves that security-sensitive step to the
Assinafy-hosted signing flow.

Once the assignment exists you can adjust or re-drive its notifications:

```python
client.assignments.reset_expiration(document["id"], assignment["id"], "2031-01-31T00:00:00Z")
client.assignments.reset_expiration(document["id"], assignment["id"], None)  # clear expiration
client.assignments.estimate_resend_cost(document["id"], assignment["id"], signer["id"])
client.assignments.resend_notification(document["id"], assignment["id"], signer["id"])
client.assignments.whatsapp_notifications(document["id"], assignment["id"])
```

`resend_notification()` sends a real message and charges the notification
channel again; call `estimate_resend_cost()` first when the cost must be known.

### 5. The signer's side

Signers act with a one-time **signer access code**, not with your API key. The
SDK sends it as the documented `signer-access-code` query parameter and never
attaches your workspace credentials to these routes.

```python
# The signer opens their link and verifies the emailed/WhatsApp code.
client.signers.verify_code(signer_access_code, "123456")
client.signers.accept_terms(signer_access_code)

# Read what this signer is allowed to see.
view = client.assignments.get_for_signer(signer_access_code)
me = client.signers.get_self(signer_access_code)

# Confirm identity data, then submit.
client.signers.confirm_data(
    document["id"],
    signer_access_code,
    {"full_name": "Example Signer", "email": "signer@example.com",
     "government_id": "00000000000"},
)
```

A virtual assignment submits an empty item list; a collect assignment submits
one entry per completed field:

```python
client.assignments.sign(document["id"], assignment["id"], [], signer_access_code)

client.assignments.sign(
    document["id"],
    assignment["id"],
    [{"itemId": "item-1", "fieldId": "field-1", "pageId": "page-1", "value": "John Doe"}],
    signer_access_code,
)
```

Declining is the mutually exclusive alternative to signing:

```python
client.assignments.decline(
    document["id"], assignment["id"], "I do not agree with the terms.", signer_access_code
)
```

A signer with several pending documents can act on all of them at once — see
[Signer documents](#signer-documents).

### 6. Track progress

Webhooks are the reliable channel. Register the workspace's single
subscription, then parse deliveries:

```python
client.webhooks.register({
    "url": "https://example.com/webhooks/assinafy",
    "email": "ops@example.com",
    "events": ["document_ready", "signer_signed_document", "signer_rejected_document"],
    "is_active": True,
})
```

```python
raw_body = request.get_data()

event = client.webhook_verifier.extract_event(raw_body)
event_type = client.webhook_verifier.get_event_type(event)   # e.g. "document_ready"
target = client.webhook_verifier.get_event_object(event)     # the document acted on

if event_type == "document_ready":
    signed_pdf = client.documents.download(target["id"], "certificated")
```

Polling and the activity log work too:

```python
document = client.documents.get(document["id"])
print(document["status"])
client.documents.activities(document["id"])
```

### 7. Download the signed document

Once every signer has completed, the document reaches `certificated` and its
artifacts become downloadable:

```python
document = client.documents.get(document["id"])
if document["status"] == "certificated":
    signed_pdf = client.documents.download(document["id"], "certificated")
    certificate_page = client.documents.download(document["id"], "certificate-page")
    everything = client.documents.download(document["id"], "bundle")
```

Valid artifacts are `original`, `certificated`, `certificate-page`, `pades`,
and `bundle`. `pades` exists only for documents signed with an ICP-Brasil
certificate. Anyone holding the signature hash can verify a document with no
credentials at all:

```python
AssinafyClient().documents.verify(signature_hash)
```

Keep the returned document, signer, and assignment IDs. Delete only disposable
resources you created, and do so in reverse dependency order.

### Starting from a template instead

When the document layout is fixed, create it from a template and skip stages 2
and 4 — field placement and roles already live on the template:

```python
templates = client.templates.list({"search": "NDA"})
template = client.templates.get(templates["data"][0]["id"])
role_id = template["roles"][0]["id"]

client.documents.estimate_cost_from_template(
    template["id"],
    [{"role_id": role_id, "verification_method": "Email"}],
)

document = client.documents.create_from_template(
    template["id"],
    [{"role_id": role_id, "id": signer["id"], "verification_method": "Email"}],
    {"name": "NDA - John Doe", "message": "Please sign."},
)
```

Template signers take one entry per template role, allow at most one
notification method each, and follow the same contiguous-`step` rules as
assignments (copy-receiver roles ignore `step`). `options` may also carry
`expires_at`, `editor_fields` (`{"field_id": ..., "value": ...}` pairs baked
into the generated document), and `tags` — tag names that do not exist are
auto-created and merged with the template's default document tags.

## Resource reference

Every method below is covered above in context; this section is the flat index.

### Authentication resource

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

### Current user

```python
user = client.users.me()
stats = client.users.stats("monthly")
preferences = client.users.notification_preferences()
preferences = client.users.update_notification_preferences({
    "DocumentCompleted": True,
    "SignerDeclined": True,
})
```

`update_notification_preferences` merges a partial map; omitted keys keep their
values, and the response is always the complete nine-key map.

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

`list()` filters on `status`, `method`, `search`, `tags` (comma-separated IDs,
matching documents that carry all of them), and `sort` (`name` or
`updated_at`). `search()` is the compact counterpart, returning documents
without the expanded `assignment`/`pages` fields. Deletion is only permitted
while the document is in a deletable status.

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

The published OpenAPI exposes `list` only. `get` is retained because the route
is deployed and answers on the live API, and the published schema text
describes a single-template response that adds `default_document_tags`.

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

`update()` cannot change a channel that has already been verified for an
in-flight document; the API enforces that server-side.

### Assignments

```python
client.assignments.list({"page": 1, "per_page": 20})
client.assignments.estimate_cost(document_id, {"signers": [{"verification_method": "Email"}]})
client.assignments.create(document_id, {"method": "virtual", "signers": [...]})
client.assignments.reset_expiration(document_id, assignment_id, "2031-01-31T00:00:00Z")
client.assignments.estimate_resend_cost(document_id, assignment_id, signer_id)
client.assignments.resend_notification(document_id, assignment_id, signer_id)
client.assignments.whatsapp_notifications(document_id, assignment_id)

# Signer-facing:
client.assignments.get_for_signer(signer_access_code)
client.assignments.sign(document_id, assignment_id, [], signer_access_code)
client.assignments.decline(document_id, assignment_id, "I do not agree.", signer_access_code)
```

`list()` is scoped by the API to the authenticated credential's current
account. The SDK forwards an `accountId` context parameter, but passing a
different `account_id` does not re-scope this endpoint — use a credential
belonging to that workspace instead.

### Signer documents

```python
client.signer_documents.current(signer_id, signer_access_code)
client.signer_documents.list(signer_id, signer_access_code, {"page": 1, "per_page": 20})
client.signer_documents.search(signer_id, signer_access_code, "contract")  # lightweight
client.signer_documents.sign_multiple(["doc-1", "doc-2"], signer_access_code)
# Mutually exclusive alternative:
# client.signer_documents.decline_multiple(["doc-1"], "Unfavorable terms.", signer_access_code)
client.signer_documents.download(signer_id, document_id, artifact_name="original")
```

The download route is public. Its optional `signer_access_code` argument is
available for deployments that require it.

### Field definitions

```python
field = client.fields.create({"type": "text", "name": "CPF"})
client.fields.list({"include_standard": True})
client.fields.get(field["id"])
client.fields.update(field["id"], {"name": "CPF updated"})
client.fields.update(field["id"], {"regex": None})  # clears the regex
client.fields.validate(field["id"], "000.000.000-00", signer_access_code=signer_access_code)
client.fields.validate_multiple(
    [{"field_id": field["id"], "value": "000.000.000-00"}],  # synthetic CPF placeholder
    signer_access_code=signer_access_code,
)
client.fields.list_types()
client.fields.delete(field["id"])
```

`create()` takes `type` (one of the values from `list_types()`) and `name`,
optionally `regex` and `is_required`. `is_read_only` / `is_visible` are
server-controlled response fields, not create input.

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
URL/events) and `register()` again to re-enable. Because the subscription is
singular, `register()` fills an omitted `events` or `is_active` from the
*current* subscription, so a partial call (rotating only `url`, say) cannot
silently reactivate an inactivated subscription or collapse a custom event
list. Pass an explicit `events=[]` to genuinely clear all events.

**Parsing payloads.** Every webhook body shares the documented envelope: `id`,
`event`, `message`, `payload` (event-specific params), `origin`, `created_at`,
`subject` (the entity that acted), `object` (the entity acted on), and
`account_id`.

```python
raw_body = request.get_data()

event = client.webhook_verifier.extract_event(raw_body)
event_type = client.webhook_verifier.get_event_type(event)      # e.g. "document_ready"
params = client.webhook_verifier.get_event_payload(event)       # event-specific params
subject = client.webhook_verifier.get_event_subject(event)      # actor (+ "type")
target = client.webhook_verifier.get_event_object(event)        # target (+ "type")
# get_event_data(event) is a backward-compatible alias of get_event_object(event)
```

**Signature verification.** The documented Delivery Contract specifies the HTTP
method, `Content-Type`, retry, and circuit-breaker behavior, but **does not
define any signature header or shared-secret scheme**. `verify()` is provided
only for accounts that have separately arranged an HMAC-SHA256 scheme with
Assinafy:

```python
signature = request.headers.get("X-Assinafy-Signature", "")
if not client.webhook_verifier.verify(raw_body, signature):
    return "Invalid signature", 401
```

## Query parameters

The SDK accepts Pythonic aliases for documented hyphenated query parameters.
For example, `per_page` is sent as `per-page`, and `signer_access_code` is sent
as `signer-access-code`. `None` values are dropped rather than sent as empty
parameters.

## Response payloads

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
of `AssinafyError`, so a single `except AssinafyError` catches every documented
failure mode.

```python
from assinafy import ApiError, AssinafyError, NetworkError, ValidationError

try:
    client.documents.upload({"file_path": "./contract.pdf"})
except ValidationError as err:      # rejected before the request was sent
    print("Validation failed:", err.errors)
except ApiError as err:             # the API returned a non-2xx response
    print(f"API error {err.status_code}:", err.response_data)
except NetworkError as err:         # the request never reached the API
    print("Network error:", err)
except AssinafyError as err:        # unexpected response shape, etc.
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
endpoints, signer/tag/field CRUD (including clearing a field's regex), template
lookup and cost estimation, document upload, document tagging,
`wait_until_ready` polling, cost estimation, and cleanup end-to-end. Every
successfully returned resource ID is captured and its cleanup is attempted in a
`finally` block. Webhook mutation is skipped unless an explicit test endpoint is
supplied; when enabled, the prior single-workspace subscription is restored.
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
