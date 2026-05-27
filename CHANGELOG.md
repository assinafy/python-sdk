# Changelog

All notable changes to `assinafy` are documented in this file.

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
