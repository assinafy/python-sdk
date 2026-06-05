# Changelog

All notable changes to `assinafy` are documented in this file.

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
