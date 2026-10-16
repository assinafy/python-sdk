# Changelog

All notable changes to `assinafy` are documented in this file.

## [1.12.0] - 2026-10-16

### Added

- `IdDocumentFaceMatchBasic` verification for assignment and template creation and cost estimates, paired with Email or Whatsapp notifications.
- `signers.identity_verification()` and `start_identity_verification()` for biometric verification state and explicitly consented hosted capture sessions.
- `assignments.identity_verification()`, `download_identity_verification_image()` and `review_identity_verification()` for workspace identity review, evidence and approval or rejection.
- `webhooks.delete_endpoint_by_url()` removes an endpoint using its exact registered URL.
- `pending_identity_review` document status, five identity-verification webhook event types and Python 3.15 support.

### Fixed

- Document readiness polling returns processed documents awaiting identity review and keeps server error text out of logs.
- Template creation and pricing omit optional signer fields set to `None`.
- Webhook signature verification rejects malformed non-ASCII signatures without an encoding error.

## [1.11.1] - 2026-10-12

### Added

- `ApiError` exposes `rate_limit_limit`, `rate_limit_remaining` and `rate_limit_reset` (the `X-Rate-Limit-Limit`, `X-Rate-Limit-Remaining` and `X-Rate-Limit-Reset` headers) and `retry_after` (the `Retry-After` seconds of a `429 Too Many Requests`), so a caller can wait the time the API asks for.
- `signer_documents.list_as_workspace()` and `search_as_workspace()` list and search a workspace signer's documents with the API key or bearer token.
- `fields.validate_as_workspace()` and `validate_multiple_as_workspace()` validate field values with the API key or bearer token.

### Changed

- `documents.send_token()` always sends the required `{"channel": "email", "recipient": "<signer email>"}` body. `channel` defaults to `"email"` and any other channel raises `ValidationError`; a missing recipient raises `ValidationError` instead of sending an empty body. `email=` remains an alias of `recipient` and now sends the same body. Migration: call `send_token(document_id, signer_email)`.
- `assignments.reset_expiration(document_id, assignment_id, None)` is documented as removing the expiration; it sends `{"expires_at": null}`.
- Docstring examples include `government_id` on signers, `endpoint_id` on webhook deliveries and `default_document_tags` on listed templates.

### Security

- A request that carries a signer access code is sent without the client's API key or bearer token, on every route. `signer_documents.list()` and `search()` use only the code; workspace access goes through the new `*_as_workspace` methods.
- `fields.validate()` and `validate_multiple()` require a non-blank signer access code and no longer fall back to the workspace credentials when it is omitted. Migration: call `validate_as_workspace()` or `validate_multiple_as_workspace()` for workspace access.
- `signer_documents.download()` rejects a blank signer access code; omitting it still downloads the public artifact.

## [1.11.0] - 2026-10-11

### Added

- `signers.create()` accepts `government_id` (CPF or CNPJ), so a signer who will use the `DigitalCertificate` verification method can be created in one call.
- `fields.validate()` rejects a missing `value` before sending the request.

### Changed

- `documents.send_token()` documents the published `{channel, recipient}` body as the primary form; the `{email}` body remains accepted as the legacy form. The example response now matches the published schema.
- `documents.append_tags()` accepts an empty list, as the published schema allows.
- `oauth.start_authorization()` validates a caller-supplied `resource` as an HTTPS origin, matching the issuer and token-exchange validation.
- `WebhookVerifier.verify_delivery()` rejects a boolean `tolerance`.
- Signer response examples include the nullable `government_id` field, and the `templates.get()` docstring notes that the route is not published in the OpenAPI document.

## [1.10.0] - 2026-10-07

### Added

- `oauth.exchange_token()` supports RFC 8693 token exchange for Assinafy internal-service applications, including explicit resource and scope selection.
- Multiple webhook endpoints (1 per account, up to 3 on paid plans): `webhooks.list_endpoints()`, `create_endpoint()`, `get_endpoint()`, `update_endpoint()` and `delete_endpoint()`.
- Webhook signing secrets: `webhooks.get_endpoint_secret()` and `rotate_endpoint_secret()`.
- `WebhookVerifier.verify_delivery()` verifies Standard Webhooks signatures (`webhook-id`, `webhook-timestamp`, `webhook-signature`) and rejects deliveries outside a replay window, 300 seconds by default.
- Two-factor authentication: `authentication.verify_mfa()` completes a login that returned an `mfa_token`, and `list_mfa_methods()`, `start_totp_enrollment()`, `confirm_totp_enrollment()`, `regenerate_recovery_codes()` and `delete_mfa_method()` manage authenticator enrollment. `verify_mfa()` is sent without client credentials.

### Fixed

- Signer verification and notification methods are validated consistently for assignments, estimates and template documents.
- Collect assignments reject malformed field placement and non-finite dimensions before sending requests; decline reasons are limited to 2000 characters.
- OAuth URL, callback, PKCE and scope validation handles malformed and non-ASCII input safely.
- Transport failures omit raw exception text and chained exceptions that could contain credentials.
- Template smoke requests include every template role and document operations wait for metadata readiness; disposable cleanup retries explicit HTTP 429 responses.
- Invalid Unicode webhook signatures return `False`; hex colors reject trailing newlines and timeouts reject non-finite values.

### Changed

- `webhooks.get()`, `register()` and `inactivate()` act on the account's oldest webhook endpoint.
- `WebhookVerifier.verify()` is documented as the legacy hex HMAC check; signed endpoints use `verify_delivery()`.
- Digital-certificate signatures are documented at 0.5 credits per signer, plus the notification.
- Shared signer, statistics and polling validation uses common helpers.
- Both READMEs describe sandbox OAuth availability, application registration, internal-service token exchange and the complete signing flow.

## [1.9.2] - 2026-09-25

### Changed

- OAuth docs now describe the current refresh-token lifetime: every refresh returns a new refresh token valid for a fresh 30 days, and a connection only expires after 30 days without a refresh.
- `NetworkError` is documented as "no response arrived" (including TLS handshake failures): the request may still have been processed, so a failed `refresh()` or `exchange_code()` must never be resent with the old token. Token requests are never automatically retried.
- The `documents.verify()` docstring lists `agreement_code`, which is nullable.
- The README disconnect example revokes the most recently saved refresh token.

## [1.9.1] - 2026-09-25

### Changed

- The SDK's own HTTPS client now requires TLS 1.2 or newer; TLS 1.0 and 1.1 connections are refused. Caller-supplied clients are unchanged.

## [1.9.0] - 2026-09-23

### Added

- The OAuth scope catalog includes `webhooks:write` for configuring and deactivating a workspace webhook subscription.

## [1.8.0] - 2026-09-21

### Fixed

- `assignments.estimate_cost()` now requires at least one signer. The published contract marks
  `signers` as required only for `virtual`, but the API prices per signer in both modes and answers
  a signer-less estimate with `400 "Pelo menos um signatários precisa ser informado."` The builder
  dropped the `signers` key entirely when the list was empty, so such a call could never succeed —
  it now raises `ValidationError` locally instead of failing upstream.

## [1.7.0] - 2026-09-20

### Added

- `client.oauth(client_id, client_secret=None)` returns an `OAuthResource`
  covering the marketplace OAuth 2.1 + OpenID Connect surface, for applications
  that act on **another** workspace with that person's permission. It provides:
  - `start_authorization()` mints a fresh PKCE verifier, `state` and (with the
    `openid` scope) a `nonce`, and returns the authorization URL together with
    the transaction to keep in the user's session. Pure string construction; no
    request is made.
  - `handle_callback()` validates the callback's `state` and `iss` in constant
    time before the code is sent anywhere, and raises the RFC error code
    (`access_denied`, `invalid_scope`, ...) when the user declined.
  - `exchange_code()` and `refresh()` call `POST /oauth/token` with the
    form-encoded body RFC 6749 §4.1.3 specifies.
  - `revoke()` calls `POST /oauth/revoke`.
  - `userinfo()` calls `GET /oauth/userinfo`.
  - `protected_resource_metadata()` and `authorization_server_metadata()` read
    the RFC 9728 and RFC 8414 discovery documents, which live at each host's
    origin above the `/v1` prefix.
  - `create_code_verifier()`, `create_state()` and `code_challenge()` are
    exposed as static methods for frameworks that own the session material.
- `assinafy.types` publishes `VerificationMethod`, `NotificationMethod`,
  `OAuthScope`, `OAuthGrantType` and `OAuthTokenTypeHint`, alongside the
  `VERIFICATION_METHODS`, `NOTIFICATION_METHODS` and `OAUTH_SCOPES` frozensets
  the resources validate against.

### Changed

- OAuth responses are returned flat, as RFC 6749 §5.1/§5.2, RFC 8414 and OIDC
  Core §5.3.2 require; they are the only calls in the API that are not wrapped
  in the `{status, data, message}` envelope. On the token and revocation
  endpoints `str(error)` is the RFC error code and `error.response_data` carries
  `error_description`, so callers branch on the message.
- `POST /oauth/token`, `POST /oauth/revoke` and the two discovery documents are
  sent without the client's `api_key` / `token`; `GET /oauth/userinfo` drops
  `X-Api-Key` but keeps the access token the caller passes, so a workspace key
  can never answer for the wrong identity.
- `AssignmentResource` documents that `DigitalCertificate` signers sign through
  the deployed-but-unpublished `POST /signers/certificate/start` + `/complete`
  handshake with the Web PKI browser extension, and that everything around that
  signature — assignment creation, `confirm_data`, cost estimation and the
  `pades` artifact — is covered by the SDK.
- `assignments.get_for_signer()` records that the `has_accepted_terms` query
  parameter is too late to open the digital-certificate gate: a certificate
  signer must be sent through `signers.confirm_data(..., has_accepted_terms=True)`
  or `signers.accept_terms()` first.
- Signer-facing endpoints now build their `signer-access-code` query string
  through one shared helper instead of repeating the alias mapping in twelve
  methods, and the `verification_method` / `notification_methods` enumerations
  live in `assinafy.types` instead of being duplicated in two resources.
- The `multipart/form-data` upload loader moved to `assinafy.utils` as
  `load_file_source()`, so the account-logo upload no longer reaches into the
  documents module for a private helper.

## [1.6.3] - 2026-08-27

### Fixed

- `AssinafyClient` now rejects a plaintext `http://` `base_url` for every
  non-loopback host, not only when `api_key` or `token` is set. The previous
  exemption for credential-free clients was unsound: `authentication.login()`,
  `social_login()`, `change_password()`, `reset_password()` and
  `create_api_key()` put passwords and provider tokens in the *request body*,
  and those are exactly the calls a client makes before it has any credential
  to configure. A credential-free client pointed at `http://host/v1` sent them
  in the clear. Loopback hosts still accept `http://`, so local and mock
  servers keep working at `localhost` / `127.0.0.1`.
- `upload_and_request_signatures()` now attaches `document_id` and the
  `signer_ids` created so far to the `context` of any `AssinafyError` raised
  after the upload succeeds. The docstring already told callers to inspect the
  error context for cleanup, but nothing populated it, so a failure during
  signer or assignment creation left orphaned records whose IDs the caller
  could not recover.

## [1.6.2] - 2026-08-27

### Fixed

- `AssinafyClient` now rejects a `base_url` that embeds credentials
  (`https://user:pass@host/v1`). Such a URL made HTTPX derive an
  `Authorization: Basic` header that replaced the configured `api_key` or
  `token` on every request, and put those URL credentials into any proxy or
  access log along the way.
- `AssinafyClient` now rejects a `base_url` carrying a query string or
  fragment. Previously the request path was appended to the wrong URL
  component — `https://host/v1?x=1` sent every call to
  `https://host/v1?x=1/accounts/...` while still attaching the API key.
- `AssinafyClient` now rejects a plaintext `http://` `base_url` pointing at a
  non-loopback host while `api_key` or `token` is set, so a mistyped or
  misconfigured URL can no longer send credentials in the clear. Loopback
  hosts and credential-free clients still accept `http://`, keeping local and
  mock servers usable.

### Changed

- `assignments.list()` documents that the API scopes results to the
  authenticated credential's current account, so passing a different
  `account_id` does not re-scope the endpoint.
- `webhooks.list_dispatches()` documents the wire values the `delivered`
  filter accepts.
- `templates.get()` records that the route is deployed and answers on the live
  API even though the published schema lists only `templates.list()`.
- The README is reorganised as a single end-to-end flow — install,
  authenticate, configure, then the seven signing stages from upload to
  certified download — with a table of contents ahead of the flat resource
  reference.

## [1.6.1] - 2026-08-26

### Added

- A complete document-signing flow, request/response references, live-smoke
  modes, and a release checklist in the README and public method docstrings.
- A main-branch, read-only sandbox workflow using environment secrets, plus
  weekly updates for pinned GitHub Actions.

### Fixed

- Every production and sandbox request now uses
  `User-Agent: Assinafy-Python-SDK/v<package-version>`, even when callers
  override the underlying HTTP headers.
- Client credentials are withheld from public, signer-code-only, cross-origin,
  and out-of-base-path requests while remaining attached to protected routes.
- Composite document workflows validate all signer, assignment, expiration,
  and wait options before the first write and preserve Email and WhatsApp
  channel behavior.
- Template, signer, webhook, tag, upload-source, query-alias, and RFC 3339
  validation now fails before malformed requests are sent.
- Signer lookup paginates exact email matches, response-shape failures use the
  SDK error hierarchy, and binary endpoints accept their documented media
  types.
- Virtual assignment signing accepts the required empty item list; template
  creation omits unset options and leaves role-aware step checks to the API.
- Read-only live smoke runs cannot execute preference restoration writes, and
  missing created-resource IDs fail immediately while cleanup still runs.

### Changed

- Supported HTTPX releases are constrained to `>=0.27.0,<1`.
- Mirrored branch pushes run the full Python 3.10–3.14, Ruff, strict mypy,
  minimum-HTTPX, test, and distribution gates.

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
- API examples use synthetic data and document request/response shapes and
  irreversible operation boundaries.

## [1.5.0] - 2026-08-10

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
  `whatsapp_phone_number` / `has_accepted_terms` compatibility fields).
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
  making it impossible to clear a field's regex. It now mirrors
  `tags.update()`'s handling of `color: None`.
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
  optional), aligned with every sibling signer-facing method.
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
  accepted input; they are server-controlled response fields only.
- `signers.confirm_data()` now raises `ValidationError` on an empty body
  instead of silently sending `{}`, matching `signers.update()`.
- Corrected several docstring examples to match the published
  contract: `create_from_template` (dropped undocumented `copy_receivers`,
  added `tags`), `estimate_cost_from_template` (dropped an undocumented `id`
  field from the example), `signers.get_self` (added the documented
  `is_signature_reusable` flag), `documents.statuses()` (full 11-status list),
  `fields.list()` (added the missing `resource` field).
- CI: added `permissions: contents: read` to both workflows, a concurrency
  group to `release.yml`, `ruff format --check`, and `pytest --cov` reporting.
- `assinafy.types.SignerReference` is now actually used in
  `assignments.py`'s signer-normalization signatures instead of sitting
  unused in `__all__`.
- Simplified `BaseResource._read_header`'s dead `hasattr` guard (every real
  and test-mocked `headers` object has `.get`).

## [1.4.0] - 2026-07-20

Adds documented signing-workflow endpoints. No breaking changes.

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

### Changed

- CI/release workflows: bumped `actions/checkout` and `actions/setup-python`
  from v6 to v7 (latest majors).

## [1.3.2] - 2026-06-05

### Fixed

- Corrected the response payload examples in the docstrings for
  `assignments.whatsapp_notifications`, `webhooks.list_dispatches`, and
  `webhooks.retry_dispatch` to match the documented object shapes. Also aligned
  the `fields.validate` example request/response so the value matches the echoed
  field type. Docstrings only — no code or behavior changes.

## [1.3.1] - 2026-06-05

### Removed

- `client.webhooks.delete()` — `DELETE /accounts/{account_id}/webhooks/subscriptions`
  is not a documented endpoint. The supported way to stop delivery is
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

## [1.3.0] - 2026-05-27

### Added

- `client.tags` resource covering `GET/POST/PUT/DELETE /accounts/{account_id}/tags`.
- Document tag helpers covering list, replace, append, and detach endpoints under
  `/accounts/{account_id}/documents/{document_id}/tags`.

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

- `User-Agent` header now includes the SDK version.
- `documents.create_from_template` and `documents.estimate_cost_from_template`
  now validate that `signers` is non-empty before sending the request.
- `WebhookVerifier` class docstring documents the assumed HMAC-SHA256 scheme
  and how to subclass for accounts using a different scheme.

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
