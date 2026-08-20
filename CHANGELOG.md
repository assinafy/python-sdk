# Changelog

All notable changes to `assinafy` are documented in this file.

## [1.6.0] - 2026-08-20

### Added

- Account and authenticated-user resources, including themes, logos, KPI
  routes, and notification preferences.
- Social-login linking, channel-neutral signer-code verification, and the
  `pades` document artifact.

### Fixed

- Signer verification and terms-acceptance now send access codes in the
  documented query parameter; signer updates now forward `government_id`.
- Account deletion serializes `force` correctly and makes it keyword-only;
  explicit empty account IDs can no longer fall back to the default workspace.
- Document readiness polling preserves API/authentication errors, retries only
  transient failures, and returns the refreshed ready document.
- Path IDs, request mappings, response shapes, upload I/O, and destructive
  boolean flags now fail through the SDK's typed error hierarchy.

### Changed

- GitHub Actions use immutable action revisions, test Python 3.10 through 3.14
  plus the minimum supported `httpx`, and verify distributions before release.
- API examples use synthetic data and document current request/response shapes,
  sandbox compatibility behavior, and irreversible operation boundaries.

## [1.5.0] - 2026-08-10

Full file-by-file conformance review against the live OpenAPI spec
(`https://api.assinafy.com.br/v1/docs/openapi.json`, 66 paths as of this
release) and the Assinafy sandbox, covering every resource, the core HTTP
plumbing, the test suite, and CI/CD. Adds one confirmed-missing endpoint,
fixes several real bugs (three of them confirmed against live sandbox
responses), and closes test-coverage gaps across the board. No functionality
was removed without first confirming — live, where possible — that the
existing behavior was actually broken.

### Added

- `client.signer_documents.search(signer_id, signer_access_code, search=None)`
  — `GET /signers/{signer_id}/documents/search`. Lightweight, compact
  counterpart to `signer_documents.list()`, matching how `documents.search()`
  was added in 1.4.0.
- `client.signers.upload_signature(..., reuse=None)` — documented `reuse`
  query parameter on `POST /signature`, controlling the signer's
  `is_signature_reusable` flag.
- `client.signers.confirm_data()` now also accepts `full_name` and
  `government_id`, matching the documented request schema (kept the existing
  `whatsapp_phone_number` / `has_accepted_terms` fields rather than removing
  them, since this endpoint's full request/response has never been
  live-tested with a real signer session).
- `client.upload_and_request_signatures(..., wait_timeout=30.0, wait_poll_interval=2.0)`
  — forwarded to `documents.wait_until_ready` (previously hardcoded).

### Fixed

- `client.documents.create_from_template()` — an `options` dict containing its
  own `signers` key could silently override the already-validated `signers`
  argument with an empty list. `signers` now always wins.
- `client.documents.wait_until_ready()` no longer swallows a persistent `404`
  (document not found) into a generic timeout error; it now re-raises the
  `ApiError` immediately, since waiting can never resolve it.
- `client.assignments.create()` now requires `signers` unconditionally
  (matching its own documented schema — the sibling `estimate_cost()` keeps
  its more lenient rule where `collect` may omit signers). Previously a
  `method: "collect"` request with no `signers` was sent to the API with no
  client-side error.
- `client.assignments.create()`'s log line now counts signers from the
  normalized request body instead of the raw payload, so it no longer reports
  0 signers when the caller uses the legacy `signer_ids` alias.
- `client.fields.update()` silently dropped an explicit `{"regex": None}`,
  making it impossible to clear a field's regex — **confirmed live**: the
  regex remained set after the call. Now mirrors `tags.update()`'s handling of
  `color: None`.
- `client.webhooks.register()` treated an explicit `events=[]` the same as
  "omitted" and replaced it with the curated default — an empty list is now
  preserved as-is.
- `client.webhooks.register()` no longer silently reactivates an inactivated
  subscription or collapses a custom event list on a partial update (e.g. only
  rotating `url`): an omitted `events`/`is_active` now defaults from the
  *current* subscription instead of a hardcoded default, so a partial call
  can't clobber existing configuration. First-time registration (no existing
  subscription) is unaffected.
- `client.signer_documents.list()` now requires `signer_access_code` (previously
  optional-but-effectively-useless, since the API always 401s without it) —
  aligned with every sibling signer-facing method.
- `scripts/live_smoke.py` now saves the workspace's webhook subscription
  before its register/inactivate test and restores it exactly at the end,
  instead of relying on a human to notice and fix it out-of-band afterward.

### Changed

- **Breaking:** `client.documents.upload(source, options=None)` is now
  `upload(source, account_id=None)`, matching every sibling resource method's
  `account_id` convention. Migration: replace
  `documents.upload(source, {"account_id": "..."})` with
  `documents.upload(source, "...")`.
- `fields.create()`'s docstring no longer lists `is_read_only`/`is_visible` as
  accepted input — **confirmed live** that the API silently ignores them; they
  are server-controlled response fields only.
- `signers.confirm_data()` now raises `ValidationError` on an empty body
  instead of silently sending `{}`, matching `signers.update()`.
- Corrected several docstring examples to match the live/resolved-spec
  contract: `create_from_template` (dropped undocumented `copy_receivers`,
  added `tags`), `estimate_cost_from_template` (dropped an undocumented `id`
  field from the example), `signers.get_self` (added the documented
  `is_signature_reusable` flag), `documents.statuses()` (full 11-status list),
  `fields.list()` (added the missing `resource` field).
- CI: added `permissions: contents: read` to both workflows, a concurrency
  group to `release.yml`, `ruff format --check`, and `pytest --cov` reporting.
  Verified `actions/checkout@v7`, `actions/setup-python@v7`,
  `actions/upload-artifact@v7`, `actions/download-artifact@v8`, and
  `pypa/gh-action-pypi-publish@release/v1` are all still current; verified the
  Python 3.10–3.14 CI matrix covers every currently-supported CPython release
  (3.15 is prerelease-only as of this writing).
- `assinafy.types.SignerReference` is now actually used in
  `assignments.py`'s signer-normalization signatures instead of sitting
  unused in `__all__`.
- Simplified `BaseResource._read_header`'s dead `hasattr` guard (every real
  and test-mocked `headers` object has `.get`).

### Verified (no change)

- `templates.get()` targeting `GET /accounts/{id}/templates/{id}` (absent from
  the OpenAPI `paths`) still returns 200 live.
- `documents.public_info()`'s reduced response shape matches its docstring.
- `fields.list()`/`templates.list()`'s documented `search`/`page`/`per-page`/
  `sort` params are backed by the spec's global "Searching, paginating and
  sorting" contract (not per-operation `parameters`, which only enumerate a
  subset) — no docstring change needed for the resources that only claimed
  these four.
- 169 unit tests pass (up from 120); `ruff check`, `ruff format --check`, and
  `mypy --strict` are all clean.
- Live sandbox run: read paths, signer/tag/field CRUD (incl. the regex-clear
  fix), template lookup + cost estimate, document upload → ready → rename →
  delete, a real assignment invitation sent to two real test inboxes
  (estimate-cost, reset-expiration incl. null-clear, resend-notification,
  estimate-resend-cost, whatsapp-notifications), and the webhook
  register/inactivate/restore cycle all pass end-to-end.

## [1.4.0] - 2026-07-20

Coverage audit against the authoritative OpenAPI spec
(`https://api.assinafy.com.br/v1/docs/openapi.json`, 68 paths), re-validated
end-to-end against the Assinafy sandbox. Adds the documented signing-workflow
endpoints that the SDK did not yet expose. No breaking changes.

### Added

- `client.documents.rename(document_id, name)` — `PATCH /documents/{id}`. Renames
  a document while it is still in `uploaded` / `metadata_ready` status (the API
  locks the name once signing starts). Name is capped at 255 characters.
- `client.documents.search(params, account_id)` — `GET /accounts/{id}/documents/search`.
  Lightweight, compact document search (no expanded `assignment` / `pages`),
  ideal for autocomplete. Accepts `search`, `status`, and pagination params.
- `client.assignments.list(params, account_id)` — `GET /assignments`. Lists the
  account's assignments (account context is supplied automatically as the
  `accountId` query parameter). Returns the standard `{"data": [...], "meta": {...}}`.

### Verified (no change)

- `client.documents.send_token()` sends the documented `{"recipient", "channel"}`
  body — confirmed correct against the live sandbox (the OpenAPI spec's
  `{"email"}` shape returns `400 "channel is required"`; live behavior is
  authoritative).
- `client.templates.get()` targets a real endpoint
  (`GET /accounts/{id}/templates/{id}` returns 200 live) even though it is absent
  from the OpenAPI `paths`.

### Changed

- CI/release workflows: bumped `actions/checkout` and `actions/setup-python`
  from v6 to v7 (latest majors).

## [1.3.2] - 2026-06-05

### Fixed

- Corrected the response payload examples in the docstrings for
  `assignments.whatsapp_notifications`, `webhooks.list_dispatches`, and
  `webhooks.retry_dispatch` to match the documented object shapes (these
  endpoints returned empty arrays during live testing, so the 1.3.1 examples had
  invented fields such as `response_status` and the wrong types for `id`/
  `sent_at`/`created_at`). Also aligned the `fields.validate` example
  request/response so the value matches the echoed field type. Docstrings only —
  no code or behavior changes.

## [1.3.1] - 2026-06-05

Full conformance audit against `https://api.assinafy.com.br/v1/docs`, validated
with live testing against the Assinafy sandbox. Every public method's docstring
now includes a real request/response payload example captured from the API.

### Removed

- `client.webhooks.delete()` — `DELETE /accounts/{account_id}/webhooks/subscriptions`
  is **not a real endpoint** (the live API returns `404 Não encontrada`), so the
  method could never succeed. The documented way to stop delivery is
  `client.webhooks.inactivate()`, which preserves the configured URL/events.
  Migration: replace any `webhooks.delete()` call with `webhooks.inactivate()`.

### Fixed

- `assignments.reset_expiration()` now accepts `expires_at=None` to **clear** an
  assignment's expiration, matching the documented behavior ("a null value means
  no expiration"). Previously the SDK rejected `None`, making this documented
  operation impossible. An empty string is still rejected as malformed.
- `assignments.create()` / `estimate_cost()` now forward each signer's optional
  `step` field, enabling sequential (multi-step) signing order as documented.
  Previously `step` was silently dropped.
- `authentication.get_api_key()` is now typed `dict | None` and returns `None`
  when no API key has been generated yet (the API returns a null `data`).

### Added

- `WebhookVerifier.get_event_payload()`, `get_event_subject()`, and
  `get_event_object()` accessors matching the documented webhook envelope
  (`payload` for event params; `subject`/`object` for the polymorphic entities).
  `get_event_data()` is retained as a backward-compatible alias of
  `get_event_object()`.
- Python 3.14 added to the CI test matrix and the package classifiers.

### Changed

- `WebhookVerifier` docstrings now state plainly that the public Delivery
  Contract documents no signature header/HMAC scheme; `verify()` is for accounts
  that have separately negotiated one.
- `webhooks.register()` documents that an omitted `events` list falls back to a
  curated subset; pass explicit events (see `list_event_types()`) for full
  control.
- Internal: `BaseResource` error handling consolidated behind a single `_guard`
  boundary, and bare-array/object unwrapping centralized in `_call_plain_list` /
  `_call_plain_dict` (removes ~10 duplicated coercion sites). No behavior change.

### Verified

- 114 unit tests pass; `ruff` and `mypy --strict` are clean.
- Live sandbox run: 49 SDK calls succeed end-to-end (read paths, signer/tag/field
  CRUD, document upload → ready → download → tagging → delete, assignment
  create/estimate/resend/reset incl. null-clear, webhook register/inactivate).
  The 8 signer-access-code endpoints return `401` with an invalid code,
  confirming they are correctly wired; their happy path requires an
  interactively verified signer session.

## [1.3.0] - 2026-05-27

### Added

- `client.tags` resource covering `GET/POST/PUT/DELETE /accounts/{account_id}/tags`.
- Document tag helpers covering list, replace, append, and detach endpoints under
  `/accounts/{account_id}/documents/{document_id}/tags`.
- Unit and live-smoke coverage for tag CRUD and document tag attachment flows.

## [1.2.0] - 2026-05-11

### Added

- `__version__` constant exposed at the package root.
- Comprehensive docstrings on every public method covering the HTTP verb,
  endpoint path, accepted parameters, and notable server-side rules
  (e.g. `documents.delete` deletable statuses, `signers.update` verification
  integrity rules).
- `scripts/live_smoke.py` — runnable live-API smoke test covering read paths,
  signer CRUD, document upload, and cost estimation.

### Changed

- `User-Agent` header now includes the SDK version (`assinafy-python-sdk/1.2.0`).
- `documents.create_from_template` and `documents.estimate_cost_from_template`
  now validate that `signers` is non-empty before sending the request.
- `WebhookVerifier` class docstring documents the assumed HMAC-SHA256 scheme
  and how to subclass for accounts using a different scheme.

### Verified

- 100% endpoint coverage versus https://api.assinafy.com.br/v1/docs — all
  documented routes for authentication, documents, signers, signer-documents,
  templates, assignments, fields, and webhooks are implemented with matching
  verbs, paths, body shapes, and hyphenated query-parameter aliases.
- 95 unit tests pass; `ruff` and `mypy --strict` are clean.
- Live API smoke test passes against `https://api.assinafy.com.br/v1`.

## [1.1.1] - 2026-05-09

### Changed

- Distribution renamed from `assinafy-sdk` to `assinafy` on PyPI. Install with `pip install assinafy`. Import path is unchanged.

## [1.1.0] - 2026-05-07

### Changed

- `signers.create` now follows the documented API exactly: it `POST`s the payload directly without an implicit "find by email then short-circuit" lookup or a 409-recovery refetch.
- `signers.update` now requires at least one documented field (`full_name`, `email`, or `whatsapp_phone_number`).
- `upload_and_request_signatures` now expects `full_name` (matching the API) instead of `name`.
- `BaseResource` is now typed against `httpx.Client` and `Logger`; the no-op logger is exposed via the `Logger` Protocol.

### Added

- `py.typed` marker (PEP 561) so consumers get inline type hints.

### Removed

- `documents.is_fully_signed` and `documents.get_signing_progress` — derive from `documents.get(id)` instead.
- `AssignmentVerificationMethod` and `AssignmentNotificationMethod` aliases (they were just `str`).

## [1.0.0] - 2026-04-10

### Added

- Initial synchronous Python SDK release with `httpx`.
- Core resources for documents, signers, assignments, webhooks, and workspaces.
- `WebhookVerifier` with HMAC-SHA256 verification.
- Pytest test suite.
