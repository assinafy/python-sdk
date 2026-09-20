# Assinafy Python SDK

*[Leia em português](README.md) · English*

Python SDK for the [Assinafy API](https://api.assinafy.com.br/v1/docs) — the
Brazilian electronic-signature platform.

The SDK is synchronous, built on `httpx`, and covers all 93 operations
currently published by Assinafy: accounts, users, authentication, OAuth,
documents, signers, signer documents, assignments, field definitions,
templates, tags, and webhooks. Every public method names the verb and path it
calls and documents its request body and unwrapped response; shared resource
shapes are documented once and referenced by the methods that return them.

- [Requirements](#requirements)
- [Installation](#installation)
- [Authentication](#authentication)
  - [Client configuration](#client-configuration)
- [Quick start](#quick-start)
- [Signer verification methods](#signer-verification-methods)
  - [ICP-Brasil digital certificate (A1/A3)](#icp-brasil-digital-certificate-a1a3)
- [The signing lifecycle](#the-signing-lifecycle)
  - [1. Prepare the signers](#1-prepare-the-signers)
  - [2. Upload the document](#2-upload-the-document)
  - [3. Estimate the cost](#3-estimate-the-cost)
  - [4. Request the signatures](#4-request-the-signatures)
  - [5. The signer's side](#5-the-signers-side)
  - [6. Track progress](#6-track-progress)
  - [7. Download the signed document](#7-download-the-signed-document)
  - [Starting from a template instead](#starting-from-a-template-instead)
- [OAuth for marketplace applications](#oauth-for-marketplace-applications)
  - [1. Register the application](#1-register-the-application)
  - [2. Send the user to Assinafy](#2-send-the-user-to-assinafy)
  - [3. Handle the callback and exchange the code](#3-handle-the-callback-and-exchange-the-code)
  - [4. Call the API](#4-call-the-api)
  - [5. Refresh and disconnect](#5-refresh-and-disconnect)
  - [Discovery and OpenID Connect](#discovery-and-openid-connect)
  - [OAuth checklist](#oauth-checklist)
- [Resource reference](#resource-reference)
  - [Authentication resource](#authentication-resource)
  - [Accounts](#accounts)
  - [Current user](#current-user)
  - [Documents](#documents)
  - [Templates](#templates)
  - [Tags](#tags)
  - [Signers](#signers)
  - [Assignments](#assignments)
  - [OAuth](#oauth)
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

There are four ways to authenticate, and which one you want depends on whose
workspace you are acting on:

| Mode | Sent as | Use it when |
| --- | --- | --- |
| API key | `X-Api-Key` | you automate **your own** workspace — recommended for back ends |
| Access token | `Authorization: Bearer` | you hold a user session from `authentication.login()` |
| Signer access code | `signer-access-code` query parameter | you drive the signer-facing endpoints |
| OAuth 2.1 + PKCE | `Authorization: Bearer` | you build an app that **other people** connect to their own workspace — see [OAuth for marketplace applications](#oauth-for-marketplace-applications) |

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
the wrong URL component). Plaintext `http://` is rejected for every non-loopback
host — `login`, `social_login`, `change_password`, `reset_password` and
`create_api_key` send secrets in the request body even when the client carries
no `api_key` or `token`, so the loopback interface is the only place plaintext
is safe. Point local and mock servers at `localhost`/`127.0.0.1`.

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

## Signer verification methods

Set per signer through `verification_method` when you create the assignment.
Verification and notification are **coupled**: send one, both, or neither — the
missing side is inferred, and sending neither defaults both to `Email`.

| Method | How it works | Cost per signer |
| --- | --- | --- |
| `Email` *(default)* | A one-time code (OTP) by email, required before signing | Free |
| `Whatsapp` | A one-time code (OTP) over WhatsApp | Verification free; the notification it requires costs 0.45 credits, on paid plans only |
| `DigitalCertificate` | The signer signs with their **own ICP-Brasil certificate (A1/A3)** through the Web PKI browser extension, producing a qualified **PAdES** signature | 2 credits, plus its notification |

Allowed pairings: `Email` → notify by `Email`; `Whatsapp` → notify by
`Whatsapp`; `DigitalCertificate` → notify by `Email` **or** `Whatsapp`. Only one
notification method per signer, and an invalid pairing is a `400`.

### ICP-Brasil digital certificate (A1/A3)

Requires the **Digital Certificate** feature on the account (Standard and Pro
plans), a CPF or CNPJ in the signer's `government_id`, and exactly **one
certificate signer per signing step**. A CPF requires that person's own
certificate (an e-CPF, or an e-CNPJ naming them as legal representative); a CNPJ
requires the company's e-CNPJ.

```python
signer = client.signers.update(signer["id"], {"government_id": "39053344705"})

estimate = client.assignments.estimate_cost(document["id"], {
    "method": "virtual",
    "signers": [{"verification_method": "DigitalCertificate",
                 "notification_methods": ["Email"]}],
})

client.assignments.create(document["id"], {
    "method": "virtual",
    "signers": [{
        "id": signer["id"],
        "step": 1,
        "verification_method": "DigitalCertificate",
        "notification_methods": ["Email"],
    }],
})
```

Before the signer can open the assignment they must confirm their identity data
**and** accept the terms — `confirm_data(..., {"has_accepted_terms": True})`
covers both in one call, and `accept_terms()` is never gated. Sending
`has_accepted_terms` to `get_for_signer()` is too late to open that gate.

The ordinary signing endpoint **rejects** certificate signers: their signature
is produced by a two-step handshake with the Web PKI browser extension.

```
POST /v1/signers/certificate/start     -> data.token       (Web PKI operation token)
        v  the browser signs that token with the signer's certificate
POST /v1/signers/certificate/complete  -> data.signerName
```

Both routes are deployed on production and sandbox, but they are **not**
published as operations in the OpenAPI document, so their request and response
contract is unspecified and this SDK does not call them — drive that step
through the Assinafy-hosted signing flow. Everything around it is covered:
creating the assignment, `confirm_data`, cost estimation, and downloading the
resulting `pades` artifact once the flow completes.

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

`DigitalCertificate` is also accepted as a `verification_method`; see
[ICP-Brasil digital certificate (A1/A3)](#icp-brasil-digital-certificate-a1a3)
for its requirements, its cost, and why the SDK stops short of the signature
handshake itself.

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

## OAuth for marketplace applications

Everything above assumes you automate **your own** workspace with an API key. If
you are building a product that **other people connect to their own Assinafy
workspace**, do not ask them for their API key: run the OAuth 2.1
authorization-code flow with PKCE and receive a token limited to what they
approved, for the one workspace they picked, that they can switch off at any
time.

| | API key | OAuth |
| --- | --- | --- |
| Acts on | **your own** workspace | **someone else's** workspace, with their permission |
| Can do | everything your account can do | only what the user approved |
| The user can switch it off | no | yes, at any time |

> OAuth is served in **production only** today. `https://sandbox.assinafy.com.br/v1/oauth/*`
> answers `404`.

The resource is a factory rather than an attribute, because an OAuth application
has credentials of its own:

```python
from assinafy import AssinafyClient

# A credential-free client is enough for the whole flow up to the exchange.
oauth = AssinafyClient().oauth(
    os.environ["ASSINAFY_OAUTH_CLIENT_ID"],
    os.environ.get("ASSINAFY_OAUTH_CLIENT_SECRET"),  # confidential apps only
)
```

The SDK stores no tokens, holds no refresh locks, and renews nothing on its own.
Those are your application's decisions, and the sections below say exactly where
they land.

### 1. Register the application

In the Assinafy app (<https://app.assinafy.com.br>) open **Settings → OAuth
applications → New application**. You must own the workspace that will own the
application, and its plan must include OAuth applications.

| Field | What to put |
| --- | --- |
| Name, Description, Logo URL | what users read on the approval screen |
| Redirect URIs | where users return, e.g. `https://myapp.example/oauth/callback`. Must be `https://`, carry no `#`, and is matched **exactly** — `…/callback` and `…/callback/` are different. Register one per environment; for local development use an HTTPS tunnel, because `http://localhost` is not accepted |
| Permissions | the **most** your app will ever request; you can ask for less at connect time, never more |
| Type | **Confidential** if your code runs on a server you control, **Public** if it runs on the user's device. This cannot be changed later |

You receive a `client_id` and, for confidential applications, a `client_secret`
shown once. Store the secret in your server's secret storage; never ship it in
browser code, a mobile app, or a repository.

The scopes:

| Scope | Lets your app |
| --- | --- |
| `documents:read` | read documents, their signers, assignments and activity |
| `documents:write` | create documents and send them for signature |
| `templates:read` / `templates:write` | read / change templates |
| `account:read` | read the workspace's profile, theme and logo |
| `openid`, `profile`, `email` | identify the user, and read their name and email |
| `offline_access` | receive a refresh token, to keep working while the user is away |

Request the minimum: every permission is another line the user reads before
deciding, and they approve everything or nothing. Billing, workspace membership,
credential management and administration are **never** reachable with an OAuth
token, whatever its scopes.

### 2. Send the user to Assinafy

`start_authorization()` mints a fresh PKCE verifier and `state` (and a `nonce`
when you request `openid`), and returns the URL plus the transaction those later
steps need. It makes no HTTP request.

```python
start = oauth.start_authorization(
    "https://myapp.example/oauth/callback",
    ["documents:read", "documents:write", "offline_access"],
)

session["assinafy_oauth"] = start        # the user's server-side session
return redirect(start["authorization_url"])   # a full page navigation, not AJAX
```

```python
{
  "authorization_url": "https://auth.assinafy.com.br/oauth/authorize?response_type=code&...",
  "state": "<random per attempt>",
  "code_verifier": "<random per attempt>",
  "code_challenge": "<base64url sha256 of the verifier>",
  "redirect_uri": "https://myapp.example/oauth/callback",
  "issuer": "https://auth.assinafy.com.br",
  "resource": "https://api.assinafy.com.br",
}
```

Call it **once per connection attempt**: a fresh verifier and `state` every time
is the whole protection against one attempt's material being replayed against
another. Keep the return value in the user's authenticated session, not in a
cookie or a URL.

If the `client_id` or `redirect_uri` is wrong the user is not sent back to you at
all — the authorization server shows an error on its own page, because
redirecting to an unverified address would be unsafe. Users stuck on an Assinafy
error page usually means one of those two values is wrong.

### 3. Handle the callback and exchange the code

`handle_callback()` is the security-critical step. It compares `state` and `iss`
in constant time **before** the code is used anywhere, and raises the RFC error
code when the user declined.

```python
from assinafy import ApiError, ValidationError

transaction = session.pop("assinafy_oauth")

try:
    code = oauth.handle_callback(request.args, transaction)
except ValidationError:
    return "This response is not ours", 400     # state or iss mismatch
except ApiError as err:
    if str(err) == "access_denied":
        return "You declined the connection", 200
    raise

tokens = oauth.exchange_code(code, transaction)
```

```python
{
  "access_token": "<access-token>",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "documents:read documents:write",
  "refresh_token": "<refresh-token>",   # only with offline_access
  "id_token": "<signed-id-token>",      # only with openid
}
```

The code is single-use and expires **60 seconds** after approval, so exchange it
server-side and immediately. Read the returned `scope` instead of assuming every
requested permission was granted; `offline_access` is a request-time signal and
never appears there.

OAuth responses are flat JSON — they are the only calls in this API that are not
wrapped in the `{status, message, data}` envelope. On failure, `str(err)` is the
RFC error code (`invalid_grant`, `invalid_client`, `invalid_target`,
`unsupported_grant_type`) and `err.response_data` carries `error_description`, so
branch on the message.

### 4. Call the API

A token belongs to the **one** workspace the user picked. With an OAuth token the
workspace list returns exactly that workspace, so store its ID next to the
tokens:

```python
api = AssinafyClient(token=tokens["access_token"])
workspace_id = api.accounts.list()[0]["id"]

documents = api.documents.list({"per_page": 20}, account_id=workspace_id)
```

Always send the token in `Authorization: Bearer`; as `X-Api-Key` or in the query
string it is refused. Calling any other workspace returns `403`, even one the
same user belongs to — this is the integration mistake we see most often. If your
customer uses several workspaces, connect each one separately and keep tokens per
workspace.

A missing permission answers `403` with a challenge naming it:

```
WWW-Authenticate: Bearer error="insufficient_scope", scope="documents:write", ...
```

Treat that as a prompt to reconnect with that scope added, not as something to
retry. A `403` without that header has another cause: a different workspace, the
user's own role, or an area OAuth tokens can never reach.

### 5. Refresh and disconnect

Access tokens last **1 hour**. With `offline_access` you renew them without the
user; the connection itself lasts **30 days from the approval** and refreshing
does not extend it, so plan for users to reconnect monthly.

```python
tokens = oauth.refresh(stored_refresh_token)
save(tokens["refresh_token"])    # before doing anything else with the response
```

> **Every refresh retires the token it used.** A replayed refresh token cannot be
> told apart from a stolen one, so the server ends the whole connection when it
> sees one: every token stops working and the user must connect again. Persist the
> new refresh token before you use the access token, hold one refresh at a time
> per connection, and treat a timeout as "maybe it worked" — re-read what you
> stored instead of retrying with the old token.

When a user disconnects in your product, revoke instead of only deleting your
copy. Revoking the refresh token ends the whole connection:

```python
oauth.revoke(stored_refresh_token, "refresh_token")
```

The endpoint answers `200` for every token outcome — revoked, already revoked,
unknown, malformed — so it can never be used to probe whether a token exists, and
success is not evidence the token was real. Only failed client authentication
answers `401`. Users can also revoke your app themselves under **Connected apps**;
handle the resulting `401` by asking them to connect again.

### Discovery and OpenID Connect

Rather than hardcoding endpoints, read them. `protected_resource_metadata()`
(RFC 9728) describes this API and names its authorization server;
`authorization_server_metadata()` (RFC 8414) describes that server. Both live at
their host's origin root, above `/v1`, and are fetched without your workspace
credentials.

```python
resource = oauth.protected_resource_metadata()
server = oauth.authorization_server_metadata(resource["authorization_servers"][0])

start = oauth.start_authorization(
    "https://myapp.example/oauth/callback",
    ["documents:read", "openid", "email"],
    issuer=server["issuer"],
    authorization_endpoint=server["authorization_endpoint"],
)
```

Request `openid` (plus `profile` and/or `email`) to sign users in. Validate the
`id_token` with a maintained OpenID Connect library — RS256, keys at the
server's `jwks_uri`, `iss` equal to the issuer, `aud` equal to your `client_id`,
`exp` in the future, and `nonce` matching the one in your transaction. For the
user's name and email, read the claims rather than the token:

```python
claims = oauth.userinfo(tokens["access_token"])
# {"sub": "...", "name": "Example User", "email": "person@example.com",
#  "email_verified": True}
```

`sub` is the user's stable identifier. `userinfo()` authenticates like any other
API route, so unlike the token endpoints its `401`/`403` arrive in the ordinary
envelope; the SDK drops the client's `X-Api-Key` for this call so a workspace key
can never answer for the wrong identity.

If your framework owns the session material, the PKCE primitives are available
directly:

```python
verifier = OAuthResource.create_code_verifier()   # 43 chars, RFC 7636 grammar
challenge = OAuthResource.code_challenge(verifier)
state = OAuthResource.create_state()
```

### OAuth checklist

- A new PKCE verifier and `state` for every connection attempt
- `state` and `iss` checked on your redirect URI — `handle_callback()` does both
- `client_secret` on your server only, never in browser code, a mobile app, or a repository
- The new refresh token saved before use, and one refresh at a time per connection
- `401` handled: refresh, and if that fails, ask the user to reconnect
- The workspace ID stored per connection, and the returned `scope` read
- Every production redirect URI registered, `https://`, and exact
- Only the permissions you need
- Tokens revoked when a user disconnects

New applications are unverified: the approval screen says Assinafy has not
reviewed the app, and it can connect to at most **25 workspaces**. The authorize
and token endpoints accept **50 requests per minute per IP** — hitting that
normally means a refresh loop.

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
client.documents.list({"page": 1, "per_page": 20, "tags": "tag-id", "sort": "updated_at"})
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

`create()` takes `full_name`, `email` and `whatsapp_phone_number`.
`government_id` — the CPF or CNPJ the digital certificate requires — exists only
on `update()`, so create the signer and then complete their record.

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

### OAuth

```python
oauth = client.oauth("client-id", "client-secret")

start = oauth.start_authorization(
    "https://myapp.example/oauth/callback",
    ["documents:read", "documents:write", "offline_access"],
)
code = oauth.handle_callback(callback_query, start)
tokens = oauth.exchange_code(code, start)
tokens = oauth.refresh(tokens["refresh_token"])
claims = oauth.userinfo(tokens["access_token"])
oauth.revoke(tokens["refresh_token"], "refresh_token")

oauth.protected_resource_metadata()
oauth.authorization_server_metadata()

# Static PKCE primitives, for frameworks that own the session material.
OAuthResource.create_code_verifier()
OAuthResource.create_state()
OAuthResource.code_challenge(verifier)
```

`start_authorization()` and `handle_callback()` make no HTTP request. See
[OAuth for marketplace applications](#oauth-for-marketplace-applications) for
the whole flow.

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
the SDK returns `data`. The five OAuth calls are the documented exception: RFC
6749, RFC 8414 and OpenID Connect all mandate a flat body, so `exchange_code`,
`refresh`, `userinfo` and the two discovery methods return top-level JSON, and
`revoke` returns `None`. No-data operations return `None` or preserve their
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
