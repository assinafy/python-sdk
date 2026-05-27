# Assinafy Python SDK Audit

Audit date: 2026-05-27
Reference: https://api.assinafy.com.br/v1/docs

## Result

The SDK is aligned with the current documented API surface after adding the
current Tags endpoints and document tag attachment helpers for release 1.3.0.
Local tests, linting, typing, and an API-key-safe live smoke test pass.

## API Coverage

| API area | SDK coverage |
| --- | --- |
| Authentication | Login, social login, API key create/get/delete, password change/reset request/reset. Live password/API-key mutation is intentionally not run against production credentials. |
| Signers | Workspace CRUD, exact-email convenience lookup, self lookup, accept terms, email verification, confirm data, signature upload/download. |
| Documents | Upload, list, statuses, get, wait, artifact/page/thumbnail download, activities, delete, template document creation/cost estimate, public verify/info/token, document tags. |
| Templates | List and get. Document creation from templates lives under `client.documents`, matching the documented endpoint group. |
| Tags | Workspace tag list/create/update/delete, including forced delete and `color: None` clearing. |
| Assignments | Cost estimate, virtual/collect create, reset expiration, signer view/sign/reject, WhatsApp notifications, resend, resend-cost estimate. |
| Signer documents | Current document, list, sign/decline multiple, artifact download. |
| Field definitions | CRUD, single/multiple validation, field type catalog. |
| Webhooks | Subscription get/update/delete/inactivate, event type catalog, dispatch list/retry, HMAC verifier helper. |

## File-by-File Review

| File | Audit notes |
| --- | --- |
| `src/assinafy/client.py` | Initializes every resource from one shared `httpx.Client`; now exposes `client.tags`. Auth header selection remains KISS and documented. |
| `src/assinafy/resources/base.py` | Centralized response unwrapping, pagination parsing, and error normalization are DRY and reusable. |
| `src/assinafy/resources/documents.py` | Matches document routes and now includes all documented document tag endpoints. Upload validation remains local and conservative. |
| `src/assinafy/resources/tags.py` | New workspace tag resource follows documented paths and preserves `color: None` for server-side color clearing. |
| `src/assinafy/resources/signers.py` | Uses documented workspace signer endpoints and signer-access-code flows with hyphenated request aliases. |
| `src/assinafy/resources/assignments.py` | Normalizes legacy convenience inputs to the documented `signers` shape without removing compatibility. |
| `src/assinafy/resources/signer_documents.py` | Signer-facing document routes match signer-access-code query requirements. |
| `src/assinafy/resources/fields.py` | Field CRUD/validation/type catalog match the documented field definition group. |
| `src/assinafy/resources/templates.py` | Keeps template discovery scoped; template document creation stays on `DocumentResource` where the documented route is defined. |
| `src/assinafy/resources/webhooks.py` | Covers subscription, event types, dispatches, retry, and inactivation; default event list is explicit. |
| `src/assinafy/resources/authentication.py` | Request shapes match docs. Production smoke skips destructive/account-sensitive auth mutations without a bearer token. |
| `src/assinafy/support/webhook_verifier.py` | HMAC helper is isolated and documented as the common scheme, with subclassing guidance for account-specific schemes. |
| `src/assinafy/types.py` | Public type aliases remain lightweight; no runtime coupling to generated schemas. |
| `src/assinafy/utils.py` | Shared response/error/query helpers keep parameter aliasing DRY. |
| `tests/` | Unit coverage now includes tag resource routes and document tag routes, plus additional document endpoint assertions. |
| `scripts/live_smoke.py` | Now exits non-zero on required live failures, skips API-key-management checks unless `ASSINAFY_ACCESS_TOKEN` is set, and exercises tag/document-tag flows. |
| `README.md` | Resource coverage and examples updated for tags/document tags; logger contract corrected to `warning`. |
| `CHANGELOG.md` | Unreleased audit changes documented. |

## Verification

Commands run:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src
ASSINAFY_API_KEY=... ASSINAFY_ACCOUNT_ID=... PYTHONPATH=src .venv/bin/python scripts/live_smoke.py
```

Results:

- `104 passed`
- `ruff`: all checks passed
- `mypy`: no issues in `src`
- Live smoke: passed for API-key-safe production flows; `authentication.get_api_key()` was skipped because it requires a bearer access token.

## Notes

- The provided API key was used only via process environment variables and was
  not written to repository files.
- Destructive authentication/password operations should not be live-tested
  against production credentials without a dedicated disposable user and token.
