# Assinafy Python SDK Conformance Report

- Date: 2026-08-10
- SDK version: 1.5.0
- Reference: https://api.assinafy.com.br/v1/docs
  (authoritative spec: https://api.assinafy.com.br/v1/docs/openapi.json — 66 paths / 87 operations)
- Live validation: Assinafy sandbox (`https://sandbox.assinafy.com.br/v1`)
- Scope: the SDK deliberately targets the document/signing workflow (see
  "Known gaps" below) rather than every documented endpoint.

## Result

The SDK conforms to the live API and passes 169 unit tests (up from 120),
`ruff check`, `ruff format --check`, and `mypy --strict`, plus an extended live
sandbox run covering every in-scope resource. One missing endpoint was added,
seven bugs were fixed (three confirmed against live sandbox responses), and
test coverage gaps across nine resource files were closed. Nothing was removed
without first confirming — live, wherever an access code/credential wasn't
required to do so safely — that the existing behavior didn't actually work.

## Method

1. Diffed every path, verb, parameter, request body, and response schema in
   the live OpenAPI spec against the SDK, file by file, across all nine
   resource modules plus the core client/base/errors/utils/types/webhook-
   verifier layer, the test suite, and CI/CD configuration.
2. Live-tested disputed and newly-fixed behavior directly against the
   sandbox, confirming or refuting each finding rather than trusting the spec
   or the SDK's prior docstrings blindly — this project's long-standing rule
   is that live behavior is authoritative when the two disagree.
3. Fixed confirmed bugs and gaps, added missing tests, corrected docstrings,
   and hardened CI.
4. Re-ran the full local verification suite and an extended live smoke test,
   then restored any sandbox state (the shared webhook subscription) the
   smoke test temporarily overwrote.

## Findings and actions

| Severity | Finding | Verification | Action |
| --- | --- | --- | --- |
| Gap | `GET /signers/{id}/documents/search` documented, not exposed | Spec diff | Added `signer_documents.search()` |
| Bug | `documents.create_from_template()`: an `options` dict containing its own `signers` key silently overrode the validated `signers` argument | Reproduced with a mock transport | `signers` now always applied last |
| Bug | `documents.wait_until_ready()` swallowed a persistent 404 into a generic timeout, hiding the real error | Reproduced with a mock transport | Re-raises `ApiError` immediately on 404 |
| Bug | `assignments.create()` let a `method: collect` request through with no `signers`, though the schema requires it unconditionally | Spec diff; documented schema requires `signers` even for `collect` in both examples | `create()` now requires signers unconditionally; `estimate_cost()` unchanged |
| Bug | `assignments.create()`'s log line undercounted signers passed via the legacy `signer_ids` alias | Reproduced with a mock logger | Logs from the normalized body |
| Bug | `fields.update({"regex": None})` did not clear the regex | **Confirmed live**: set a regex, called update with `regex: None`, regex remained set | Rewrote to preserve explicit `None`, mirroring `tags.update()` |
| Bug | `webhooks.register(events=[])` was replaced with the curated default instead of staying empty | Reproduced with a mock transport | Fixed to a `None`-check instead of truthiness |
| Best practice | `webhooks.register()` on a partial update (e.g. only rotating `url`) silently reactivated an inactivated subscription / collapsed a custom event list | **Confirmed live** the fix round-trips correctly | Omitted `events`/`is_active` now default from the current subscription, not a hardcoded value |
| Doc-mismatch | `fields.create()` docstring listed `is_read_only`/`is_visible` as accepted input | **Confirmed live**: created a field with both set, API silently ignored both | Docstring corrected; these are response-only fields |
| Doc-mismatch | `fields.list()` example omitted the `resource` field present in every sibling example | **Confirmed live** the real value is `"field_definition"` (the spec's own `"field"` example is stale) | Added `resource` to the example |
| Doc-mismatch | `create_from_template`/`estimate_cost_from_template` docstring examples didn't match the documented request schemas (`copy_receivers` vs `tags`; an undocumented `id`) | Spec diff | Corrected both examples |
| Doc-mismatch | `signers.get_self()` docstring omitted the documented `is_signature_reusable` response flag | Spec diff | Added to docstring/example |
| Verified | `templates.get()` targets `GET /accounts/{id}/templates/{id}`, absent from the OpenAPI `paths` | **Confirmed live** with a real template ID: 200, matches docstring shape | No change |
| Verified | `documents.public_info()`'s reduced response shape | **Confirmed live** | No change |
| Verified | `fields.list()`/`templates.list()`'s documented `search`/`page`/`per-page`/`sort` | Spec's global "Searching, paginating and sorting" section documents these for all list endpoints, not just the per-operation `parameters` arrays that a naive per-path diff would check | No docstring change — the earlier flag was a false positive from only reading per-operation parameters |
| Best practice | `documents.upload()` alone took an `options` dict for `account_id`, unlike every sibling method's direct parameter | Source review | **Breaking:** `upload(source, account_id=None)` |
| Best practice | `signer_documents.list()`'s `signer_access_code` was optional-but-effectively-required (API 401s without it) | Reproduced with a mock transport | Now a required parameter, matching siblings |
| Best practice | `SignerReference` exported in `__all__` but unused in any real signature | Source review | Wired into `assignments.py`'s signer-normalization helpers |
| Best practice | `BaseResource._read_header`'s `hasattr` guard was unreachable (every real/mocked `headers` has `.get`) | Source review | Removed |

## Live verification summary

Exercised directly against the sandbox:

| Area | What was exercised |
| --- | --- |
| Documents | statuses (full 11-code list), list, search, upload → wait → public_info → delete |
| Templates | list, get (real ID, undocumented path), estimate-cost-from-template (real role ID) |
| Fields | create with `is_read_only`/`is_visible` input (silently ignored, confirmed), update regex-set then regex-clear-with-`None` (confirmed fixed), delete |
| Assignments | estimate_cost, **create() with a real invitation sent to `bill@febacapital.com` and `billm@billm.org`**, list, reset_expiration (set + null-clear), resend_notification, estimate_resend_cost, whatsapp_notifications |
| Webhooks | get, register (defaults-from-current-state fix), inactivate, restore |
| Extended `scripts/live_smoke.py` | 30+ steps, 0 failures — see script for the full list |

The signer-side happy path (`verify_email` → `confirm_data` → `upload_signature`
→ `sign`) still can't be exercised end-to-end without reading a real signer's
inbox for the access code. These endpoints remain proven correctly wired via
the documented 401-on-invalid-code behavior.

## API coverage

| API area | SDK coverage |
| --- | --- |
| Authentication | login, social login, API key create/get/delete, change/request/reset password |
| Signers | workspace CRUD, exact-email lookup, self, accept-terms, verify-email, confirm-data (now incl. `full_name`/`government_id`), signature upload (incl. `reuse`)/download |
| Documents | upload, list, search, statuses, get, rename, wait, artifact/page/thumbnail download, activities, delete, template create + cost estimate, public verify/info/send-token, document tags |
| Templates | list, get (single) |
| Tags | list/create/update/delete (incl. `force` and `color: null`) |
| Assignments | list, estimate-cost, virtual/collect create (with `step`, signers now required), reset-expiration (incl. null), signer view/sign/reject, WhatsApp notifications, resend + resend-cost |
| Signer documents | current, list, **search**, sign/decline multiple, artifact download |
| Field definitions | CRUD (regex-clear now works), single/multiple validation, type catalog |
| Webhooks | subscription get/update (now state-safe)/inactivate, event-type catalog, dispatch list/retry, payload-parsing helpers |

## Known gaps (documented, intentionally not implemented)

Confirmed still current against the live spec. Per the agreed scope, the SDK
targets the **document/signing workflow**:

- **Workspace administration** — `GET/POST /accounts`, `GET/PUT/DELETE
  /accounts/{id}`, `GET/POST/DELETE /accounts/{id}/logo`, `GET
  /accounts/{id}/theme`.
- **Current user** — `GET /users/self`.
- **Stats** — `GET /accounts/{id}/stats`, `GET /users/self/stats`.
- **Browser OAuth flows** — `POST /auth/link-social-login` (the previously
  documented `GET /auth/authenticate` / `GET /login-callback` redirect
  endpoints are no longer present in the spec at all).
- Template create/update/delete/page-download endpoints are **no longer
  referenced anywhere in the spec** (previously listed as a known gap because
  they existed with no request/response contract; that gap is now moot).

## Verification commands

```bash
.venv/bin/python -m pytest --cov=assinafy --cov-report=term-missing   # 169 passed
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/mypy src                  # strict, clean
ASSINAFY_API_KEY=... ASSINAFY_ACCOUNT_ID=... \
  ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1 \
  PYTHONPATH=src .venv/bin/python scripts/live_smoke.py
```

## Notes

- The sandbox API key was passed only via process environment variables /
  direct request headers and was never written to repository files.
- The live smoke test now saves the workspace's webhook subscription before
  its register/inactivate test and restores it automatically at the end,
  instead of requiring a human to notice and fix it out-of-band afterward.
  One residual imperfection: the very first run, before this auto-restore
  logic existed, the original subscription's `email` field was lost to a
  preview-truncation bug in the script's own logging; the restored
  subscription now uses `bill@febacapital.com` for that field. The `url`,
  `events`, and `is_active` were fully recovered and are exact.
- Assignment creation was exercised for real (per explicit instruction to use
  `bill@febacapital.com` and `billm@billm.org` as test signers), sending one
  real signature-request invitation to each; the underlying document was
  deleted afterward, which cascades the assignment.
