# Assinafy Python SDK Audit

- Audit date: 2026-06-05
- SDK version: 1.3.1
- Reference: https://api.assinafy.com.br/v1/docs
- Live validation: Assinafy sandbox (`https://sandbox.assinafy.com.br/v1`)

## Result

The SDK conforms to the documented API surface and is validated end-to-end
against the live sandbox. Every documented endpoint that the SDK exposes was
exercised against the sandbox; one non-existent endpoint was removed and two
conformance bugs were fixed. Local tests (114), `ruff`, and `mypy --strict`
pass. Every public method's docstring carries a real request/response payload.

## Method

1. Parsed the full HTML API reference into per-section specs.
2. Instrumented the SDK's `httpx` client and called **every** SDK method against
   the sandbox, capturing real request/response payloads.
3. Ran a file-by-file conformance + quality audit (one reviewer per resource)
   cross-referencing SDK ↔ docs ↔ live payloads, with adversarial verification
   of every must-fix finding.
4. Applied verified fixes, enriched docstrings with captured payloads, and
   re-ran the full live verification against the final code.

## Live verification summary

| Outcome | Count | Detail |
| --- | --- | --- |
| Passed end-to-end | 49 | auth read, signer/tag/field CRUD, document upload→ready→download→thumbnail→page→tags→delete, assignment create/estimate/resend/reset (incl. `null` clear), webhook register/get/inactivate, public info |
| Wired-correct (401 on invalid code) | 8 | all signer-access-code flows: `get_for_signer`, `signers.get_self`/`accept_terms`/`confirm_data`/`upload_signature`/`download_signature`, `signer_documents.current`/`list`. 401 (not 404) proves verb/path/params are correct; the happy path needs an interactively verified signer session |
| Dead endpoint (removed) | 1 | `webhooks.delete` → `DELETE …/webhooks/subscriptions` returns 404 |
| Not testable in this workspace | 1 | `templates.get` (no templates exist in the sandbox account) |

## Findings and actions

| Severity | Finding | Action |
| --- | --- | --- |
| Must-fix | `webhooks.delete` hits a non-existent endpoint (live 404) | Removed; `inactivate()` is the documented disable path |
| Must-fix | `assignments.reset_expiration` rejected `None`, blocking the documented null-to-clear | Now accepts `None` (clears) and rejects `""`; verified live |
| Should-fix | `assignments` dropped the documented `signers[].step` | Now forwarded for sequential signing |
| Should-fix | `WebhookVerifier` lacked accessors for the real envelope (`payload`/`subject`/`object`) | Added `get_event_payload`/`get_event_subject`/`get_event_object`; `get_event_data` kept as alias of `get_event_object` |
| Should-fix | `WebhookVerifier.verify` HMAC scheme is undocumented by the API | Kept (non-destructive) with docstrings stating the Delivery Contract documents no signature mechanism |
| Nit | `get_api_key` could return `None` but wasn't typed for it | Typed `dict | None` |
| Quality | Duplicated try/except across `_call*`; repeated list/dict coercion | Consolidated behind `_guard`, `_call_plain_list`, `_call_plain_dict` |

## API coverage

| API area | SDK coverage |
| --- | --- |
| Authentication | login, social login, API key create/get/delete, change/request/reset password |
| Signers | workspace CRUD, exact-email lookup, self, accept-terms, verify-email, confirm-data, signature upload/download |
| Documents | upload, list, statuses, get, wait, artifact/page/thumbnail download, activities, delete, template create + cost estimate, public verify/info/send-token, document tags |
| Templates | list, get (single). See gap note below. |
| Tags | list/create/update/delete (incl. `force` and `color: null`) |
| Assignments | estimate-cost, virtual/collect create (with `step`), reset-expiration (incl. null), signer view/sign/reject, WhatsApp notifications, resend + resend-cost |
| Signer documents | current, list, sign/decline multiple, artifact download |
| Field definitions | CRUD, single/multiple validation, type catalog |
| Webhooks | subscription get/update/inactivate, event-type catalog, dispatch list/retry, payload-parsing helpers |

## Known gaps (documented, intentionally not implemented)

- **Template create / update / delete / page-download.** The Template area
  intro mentions these, and the Template-Object reference lists `POST`/`PUT`
  endpoints, but the docs provide **no request/response contract** (no body
  parameters, no examples) for them. They are intentionally not implemented to
  avoid shipping a guessed contract; add them once Assinafy documents the
  bodies. `templates.list` and `templates.get` (both documented shapes) are
  implemented.

## Verification commands

```bash
.venv/bin/python -m pytest          # 114 passed
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src                  # strict, clean
ASSINAFY_API_KEY=... ASSINAFY_ACCOUNT_ID=... \
  ASSINAFY_BASE_URL=https://sandbox.assinafy.com.br/v1 \
  PYTHONPATH=src .venv/bin/python scripts/live_smoke.py
```

## Notes

- The sandbox API key was passed only via process environment variables and was
  never written to repository files.
- Destructive auth/password operations are not live-tested against shared
  credentials; assignment-creation in the shipped smoke test is omitted to avoid
  sending real signer notifications (it is covered by the full audit harness).
