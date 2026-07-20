# Assinafy Python SDK Audit

- Audit date: 2026-07-20
- SDK version: 1.4.0
- Reference: https://api.assinafy.com.br/v1/docs
  (authoritative spec: https://api.assinafy.com.br/v1/docs/openapi.json — 68 paths)
- Live validation: Assinafy sandbox (`https://sandbox.assinafy.com.br/v1`)

## Result

The SDK conforms to the live API and is validated end-to-end against the
sandbox. This audit fetched the machine-readable OpenAPI spec (not just the HTML
reference), diffed it path-by-path against the SDK, and live-tested the gaps.
Three documented signing-workflow endpoints were missing and have been added;
two prior "unverifiable" items were confirmed correct against the live API. The
full local suite (120 tests), `ruff`, and `mypy --strict` pass, and a 31-step
live smoke test against the sandbox passes with zero failures.

## Method

1. Downloaded the OpenAPI 3.0 spec and enumerated all 68 documented paths.
2. Extracted every HTTP call the SDK makes and diffed it against the spec.
3. Probed each divergence directly against the live sandbox (real requests) to
   determine ground truth — the spec is imperfect, so **live behavior is
   authoritative**.
4. Implemented the missing signing-workflow endpoints with docstrings carrying
   real captured payloads, added unit tests, and re-ran the full verification
   (local suite + live smoke).

## Live verification summary

| Outcome | Detail |
| --- | --- |
| Live smoke passed | 31 steps: reads, signer/tag/field CRUD, document upload→ready→**rename**→delete, **documents.search**, **assignments.list**, cost estimate, document tagging, webhook register/get/inactivate |
| New endpoints live-tested through the SDK | `documents.rename` (upload→wait→rename→delete), `documents.search` (compact results, pagination meta), `assignments.list` (13 assignments, 7 pages of pagination) |
| Signer bootstrap verified | `send-token` accepts the SDK's `{recipient, channel}` body (200); spec's `{email}` returns 400. Signer-access-code endpoints return 401 on an invalid code (verb/path/params correct; auth is checked before the body) |

## Findings and actions

| Severity | Finding | Action |
| --- | --- | --- |
| Coverage | `PATCH /documents/{id}` (rename) was documented + live but not exposed | Added `documents.rename()` |
| Coverage | `GET /accounts/{id}/documents/search` (lightweight search) not exposed | Added `documents.search()` |
| Coverage | `GET /assignments` (list assignments) not exposed | Added `assignments.list()` (account context via the `accountId` query param, discovered by live probing) |
| Verified | Spec claims `send-token` body is `{email}` | Live-confirmed the SDK's `{recipient, channel}` is correct; spec is wrong. No change |
| Verified | `templates.get` targets a path absent from the OpenAPI `paths` | Live-confirmed `GET /accounts/{id}/templates/{id}` returns 200. No change |
| Best practice | CI/release pinned `actions/checkout@v6`, `actions/setup-python@v6` | Bumped both to v7 (latest majors) |

## API coverage

| API area | SDK coverage |
| --- | --- |
| Authentication | login, social login, API key create/get/delete, change/request/reset password |
| Signers | workspace CRUD, exact-email lookup, self, accept-terms, verify-email, confirm-data, signature upload/download |
| Documents | upload, list, **search**, statuses, get, **rename**, wait, artifact/page/thumbnail download, activities, delete, template create + cost estimate, public verify/info/send-token, document tags |
| Templates | list, get (single) |
| Tags | list/create/update/delete (incl. `force` and `color: null`) |
| Assignments | **list**, estimate-cost, virtual/collect create (with `step`), reset-expiration (incl. null), signer view/sign/reject, WhatsApp notifications, resend + resend-cost |
| Signer documents | current, list, sign/decline multiple, artifact download |
| Field definitions | CRUD, single/multiple validation, type catalog |
| Webhooks | subscription get/update/inactivate, event-type catalog, dispatch list/retry, payload-parsing helpers |

## Known gaps (documented, intentionally not implemented)

Per the agreed scope, the SDK targets the **document/signing workflow**. The
following documented endpoints are deliberately excluded and can be added if the
scope expands:

- **Workspace administration** — `GET/POST /accounts`, `GET/PUT/DELETE
  /accounts/{id}` (incl. workspace deletion), `GET/POST/DELETE
  /accounts/{id}/logo`, `GET /accounts/{id}/theme`. Admin/branding concerns
  outside the signing flow.
- **Current user** — `GET /users/self`. Returns the authenticated user profile;
  not needed for signing.
- **Stats** — `GET /accounts/{id}/stats`, `GET /users/self/stats`. Documented but
  return `404` on the sandbox (not deployed); omitted until they are live.
- **Browser OAuth flows** — `GET /auth/authenticate`, `GET /login-callback`,
  `POST /auth/link-social-login`. Redirect-based flows for interactive browsers,
  not a server-side SDK.
- **Template create / update / delete / page-download.** The spec references
  these but provides no request/response body contract; not implemented to avoid
  shipping a guessed shape.

## Signer happy-path (email-gated)

The signer-side signing flow (`get_for_signer` → `verify_email` → `confirm_data`
→ `upload_signature` → `sign`) authenticates with a per-signer access code that
Assinafy delivers only by email/WhatsApp to the signer. These endpoints are
proven wired-correct (401 on an invalid code — the API validates auth before the
body). Fully exercising the happy path requires reading the signer's inbox to
extract the access code; see the audit conversation for the live invitation sent
to the test address.

## Verification commands

```bash
.venv/bin/python -m pytest          # 120 passed
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src                  # strict, clean
ASSINAFY_API_KEY=... ASSINAFY_ACCOUNT_ID=... \
  ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1 \
  PYTHONPATH=src .venv/bin/python scripts/live_smoke.py   # 31 steps, 0 failures
```

## Notes

- The sandbox API key was passed only via process environment variables / direct
  request headers and was never written to repository files.
- The live smoke test registers and inactivates a webhook subscription; because
  the sandbox has a single shared subscription, the audit restored the original
  `webhook.site` subscription afterward.
- Assignment creation in the shipped smoke test remains omitted to avoid sending
  real signer notifications; the full audit exercised it separately.
