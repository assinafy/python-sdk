"""OAuth 2.1 authorization-code flow with PKCE, for marketplace applications.

Use this only when your application acts on **someone else's** workspace with
that person's permission. Automating your own workspace needs none of it: keep
using an API key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx

from ..errors import ApiError, ValidationError
from ..types import Logger, OAuthScope, OAuthTokenTypeHint
from .base import BaseResource

#: Authorization server that owns the browser-facing consent page.
DEFAULT_ISSUER = "https://auth.assinafy.com.br"

#: RFC 8414 metadata path, served by the authorization server's origin.
AUTHORIZATION_SERVER_METADATA_PATH = ".well-known/oauth-authorization-server"

#: RFC 9728 metadata path, served by this API's origin (outside ``/v1``).
PROTECTED_RESOURCE_METADATA_PATH = ".well-known/oauth-protected-resource"

#: The only code-challenge method the authorization server accepts.
CODE_CHALLENGE_METHOD = "S256"

_TOKEN_TYPE_HINTS = frozenset({"access_token", "refresh_token"})

# RFC 7636 code-verifier grammar: 43-128 characters from the unreserved set.
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


class OAuthResource(BaseResource):
    """OAuth 2.1 + OpenID Connect endpoints and the client-side flow helpers.

    Obtain one from :meth:`assinafy.client.AssinafyClient.oauth`::

        oauth = client.oauth("your-client-id", "your-client-secret")

    **Two hosts, on purpose.** The consent page lives on the authorization
    server (``https://auth.assinafy.com.br``); ``/oauth/token``,
    ``/oauth/revoke`` and ``/oauth/userinfo`` live on this API under ``/v1``.
    The two discovery documents sit at the *origin* of each host, above the
    ``/v1`` prefix. Every request this resource makes outside ``/v1`` — or to
    the authorization server — is sent without the client's ``api_key`` /
    ``token``, because those credentials belong to a different trust domain.

    **Flat JSON, no envelope.** RFC 6749 §5.1/§5.2, RFC 8414 and OIDC Core
    §5.3.2 all forbid the ``{status, message, data}`` envelope the rest of this
    API uses, so these methods return the decoded body as-is.

    **Errors.** Failures raise :class:`~assinafy.errors.ApiError`. On the token
    and revocation endpoints — and on a declined callback surfaced by
    :meth:`handle_callback` — ``str(error)`` is the RFC error code
    (``invalid_grant``, ``invalid_client``, ``access_denied``, ...) and
    ``error.response_data`` carries ``error_description``, so branch on the
    message. :meth:`userinfo` is the exception: it authenticates like any other
    API route, so its ``401``/``403`` arrive in the ordinary envelope.

    **OAuth is production-only today.** The sandbox host does not serve
    ``/v1/oauth/*``; it answers ``404``.

    The SDK stores no tokens, holds no refresh locks and renews nothing
    automatically. Those are application concerns.

    Args:
        http: The shared ``httpx.Client`` from the owning client.
        client_id: The application's ``client_id`` from the Assinafy app
            (**Settings → OAuth applications**).
        client_secret: Confidential applications only. Public applications
            authenticate with PKCE alone and are never issued a secret.
        logger: Optional :class:`~assinafy.types.Logger`-shaped object.

    .. seealso:: https://api.assinafy.com.br/v1/docs (tag *OAuth Integration Guide*)
    """

    def __init__(
        self,
        http: httpx.Client,
        client_id: str,
        client_secret: str | None = None,
        logger: Logger | None = None,
    ) -> None:
        super().__init__(http, None, logger)
        if not isinstance(client_id, str) or not client_id.strip():
            raise ValidationError("OAuth client_id must be a non-empty string")
        if client_secret is not None and (
            not isinstance(client_secret, str) or not client_secret.strip()
        ):
            raise ValidationError("OAuth client_secret must be a non-empty string when supplied")
        self._client_id = client_id
        self._client_secret = client_secret

    def __repr__(self) -> str:
        """Identify the client without ever rendering its secret."""
        kind = "public" if self._client_secret is None else "confidential"
        return f"OAuthResource(client_id={self._client_id!r}, client_type={kind!r})"

    # ------------------------------------------------------------------
    # PKCE material — pure functions, no HTTP
    # ------------------------------------------------------------------

    @staticmethod
    def create_code_verifier() -> str:
        """Generate an RFC 7636 code verifier: 43 characters from the unreserved set.

        A **new** one is required for every connection attempt.
        :meth:`start_authorization` calls this for you; use it directly only
        when your framework owns the session material.
        """
        return _b64url(secrets.token_bytes(32))

    @staticmethod
    def create_state() -> str:
        """Generate the random per-attempt ``state`` that protects the callback from CSRF."""
        return _b64url(secrets.token_bytes(32))

    @staticmethod
    def code_challenge(code_verifier: str) -> str:
        """Derive the ``S256`` challenge sent to the authorization server from a verifier."""
        _assert_code_verifier(code_verifier)
        return _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())

    def start_authorization(
        self,
        redirect_uri: str,
        scopes: list[OAuthScope] | list[str],
        *,
        issuer: str | None = None,
        authorization_endpoint: str | None = None,
        state: str | None = None,
        nonce: str | None = None,
        code_verifier: str | None = None,
        resource: str | None = None,
    ) -> dict[str, Any]:
        """Begin a connection: mint PKCE material and build the authorization URL.

        Pure string construction — makes **no** HTTP request.

        Call this once per connection attempt. A fresh ``code_verifier`` and
        ``state`` are generated every time, which is the single rule that stops
        one attempt's material being replayed against another. Persist the whole
        return value in the user's authenticated server-side session, then
        redirect the browser to ``authorization_url`` with a full page
        navigation (never an AJAX call).

        Args:
            redirect_uri: One of the application's registered URIs, character
                for character. Must be ``https://`` and carry no fragment;
                ``http://localhost`` is not accepted — use an HTTPS tunnel.
            scopes: The permissions to request, within what the application is
                registered for. See :data:`assinafy.types.OAUTH_SCOPES` for the
                published set; an unlisted scope is **not** rejected locally,
                because the authorization server may publish new ones.
            issuer: Authorization server origin. Defaults to
                :data:`DEFAULT_ISSUER`; pass ``authorization_servers[0]`` from
                :meth:`protected_resource_metadata` to follow discovery.
            authorization_endpoint: Overrides ``{issuer}/oauth/authorize``, for
                callers configuring from :meth:`authorization_server_metadata`.
            state: Supply your own per-attempt state instead of a generated one.
            nonce: Supply your own OIDC nonce. Only used with the ``openid``
                scope, which is the only case that yields an ``id_token``.
            code_verifier: Supply your own RFC 7636 verifier (43-128 characters
                from ``A-Z a-z 0-9 - . _ ~``) instead of a generated one.
            resource: RFC 8707 resource indicator. Defaults to this API's
                origin, which is what the token endpoint expects.

        Returns:
            The transaction to store and feed back into :meth:`handle_callback`
            and :meth:`exchange_code`::

                {"authorization_url": "https://auth.assinafy.com.br/oauth/authorize"
                                      "?response_type=code&client_id=...",
                 "state": "<43-char random string>",
                 "code_verifier": "<43-char random string>",
                 "code_challenge": "<base64url sha256 of the verifier>",
                 "nonce": "<43-char random string, only with the openid scope>",
                 "redirect_uri": "https://myapp.example/oauth/callback",
                 "issuer": "https://auth.assinafy.com.br",
                 "resource": "https://api.assinafy.com.br"}

        Raises:
            ValidationError: On an unusable redirect URI, an empty scope list, a
                scope that is blank or contains a space (``scope`` is
                space-delimited on the wire, so an embedded space would silently
                request two permissions), or a malformed ``code_verifier``.
        """
        _assert_redirect_uri(redirect_uri)
        requested = _validate_scopes(scopes)

        verifier = self.create_code_verifier() if code_verifier is None else code_verifier
        _assert_code_verifier(verifier)
        challenge = self.code_challenge(verifier)

        resolved_issuer = _https_origin(
            DEFAULT_ISSUER if issuer is None else issuer, "OAuth issuer"
        )
        endpoint = (
            f"{resolved_issuer}/oauth/authorize"
            if authorization_endpoint is None
            else self._require_id(authorization_endpoint, "Authorization endpoint")
        )
        resolved_state = self.create_state() if state is None else self._require_id(state, "State")
        resolved_resource = (
            self._api_origin() if resource is None else self._require_id(resource, "Resource")
        )

        query: dict[str, str] = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(requested),
            "state": resolved_state,
            "code_challenge": challenge,
            "code_challenge_method": CODE_CHALLENGE_METHOD,
            "resource": resolved_resource,
        }
        transaction: dict[str, Any] = {
            "state": resolved_state,
            "code_verifier": verifier,
            "code_challenge": challenge,
            "redirect_uri": redirect_uri,
            "issuer": resolved_issuer,
            "resource": resolved_resource,
        }
        # An id_token is only issued for `openid`, and a nonce is only echoed into one.
        if "openid" in requested:
            resolved_nonce = (
                self.create_state() if nonce is None else self._require_id(nonce, "Nonce")
            )
            query["nonce"] = resolved_nonce
            transaction["nonce"] = resolved_nonce

        # RFC 3986 percent-encoding (space as %20, not +), matching the published guide
        # and what every other Assinafy SDK sends.
        transaction["authorization_url"] = f"{endpoint}?{urlencode(query, quote_via=quote)}"
        self._logger.info("Starting OAuth authorization", {"scopes": requested})
        return transaction

    def handle_callback(
        self,
        query: dict[str, Any],
        transaction: dict[str, Any],
    ) -> str:
        """Validate the browser's return to your redirect URI and return the code.

        Pure verification — makes **no** HTTP request.

        This is the security-critical step. It rejects a response whose ``state``
        does not match the stored transaction (CSRF, or another tab's attempt)
        and one whose ``iss`` is not the expected authorization server (a
        mixed-up or spoofed issuer) **before** the code is sent anywhere.
        Consume the stored transaction exactly once.

        Args:
            query: Your framework's already-parsed callback query parameters.
            transaction: The mapping :meth:`start_authorization` returned,
                loaded back from the user's session.

        An approved callback looks like::

            {"code": "<authorization-code>", "state": "<state>",
             "iss": "https://auth.assinafy.com.br"}

        A declined one looks like::

            {"error": "access_denied", "error_description": "...",
             "state": "<state>", "iss": "https://auth.assinafy.com.br"}

        Returns:
            The single-use authorization code, which expires **60 seconds**
            after approval.

        Raises:
            ValidationError: When the transaction is unusable, ``state`` does
                not match, ``iss`` is absent or wrong, or no code was returned.
            ApiError: When the authorization server reported an error.
                ``str(error)`` is the RFC code (``access_denied``,
                ``invalid_scope``, ``invalid_request``,
                ``unsupported_response_type``, ``invalid_target``).
        """
        if not isinstance(query, dict) or not isinstance(transaction, dict):
            raise ValidationError("OAuth callback query and transaction must be mappings")

        expected_state = _string_option(transaction, "state")
        if expected_state is None:
            raise ValidationError("Stored OAuth transaction is missing its state")
        received_state = _string_option(query, "state")
        if received_state is None or not hmac.compare_digest(expected_state, received_state):
            raise ValidationError("OAuth callback state does not match the stored transaction")

        # The authorization server advertises authorization_response_iss_parameter_supported,
        # so a missing `iss` is itself a reason to stop rather than something to tolerate.
        expected_issuer = (_string_option(transaction, "issuer") or DEFAULT_ISSUER).rstrip("/")
        received_issuer = _string_option(query, "iss")
        if received_issuer is None or not hmac.compare_digest(
            expected_issuer, received_issuer.rstrip("/")
        ):
            raise ValidationError(
                "OAuth callback issuer does not match the expected authorization server"
            )

        error = _string_option(query, "error")
        if error is not None:
            raise ApiError(
                error,
                400,
                {"error": error, "error_description": _string_option(query, "error_description")},
            )

        code = _string_option(query, "code")
        if code is None:
            raise ValidationError("OAuth callback did not include an authorization code")
        return code

    # ------------------------------------------------------------------
    # Token endpoints
    # ------------------------------------------------------------------

    def exchange_code(self, code: str, transaction: dict[str, Any]) -> dict[str, Any]:
        """``POST /oauth/token`` with ``grant_type=authorization_code``.

        Server-side only, and only once: the code is single-use and expires 60
        seconds after approval. ``redirect_uri`` and ``code_verifier`` must be
        byte-identical to the ones the authorization request was made with,
        which is why the whole stored transaction is passed rather than
        re-supplied by hand.

        Request body (``application/x-www-form-urlencoded``; ``client_secret``
        is omitted by public applications)::

            grant_type=authorization_code
            code=<authorization-code>
            redirect_uri=https://myapp.example/oauth/callback
            code_verifier=<code-verifier>
            client_id=<client-id>
            client_secret=<client-secret>
            resource=https://api.assinafy.com.br

        Example response (flat JSON, no ``data`` envelope)::

            {"access_token": "<access-token>", "token_type": "Bearer",
             "expires_in": 3600,
             "scope": "documents:read documents:write",
             "refresh_token": "<refresh-token>",
             "id_token": "<signed-id-token>"}

        ``refresh_token`` appears only when ``offline_access`` was requested
        *and* approved; ``id_token`` only with ``openid``. Read the returned
        ``scope`` instead of assuming every requested permission was granted —
        ``offline_access`` is a request-time signal and never appears there.

        Then call :meth:`~assinafy.resources.accounts.AccountResource.list` with
        the access token: an OAuth token returns exactly the one authorized
        workspace, whose ``id`` belongs in the connection record next to the
        tokens.

        Raises:
            ValidationError: On an empty code, or a transaction missing its
                verifier or redirect URI.
            ApiError: ``invalid_grant`` (expired, replayed or mismatched code),
                ``invalid_client``, ``invalid_target``.
        """
        self._require_id(code, "Authorization code")
        if not isinstance(transaction, dict):
            raise ValidationError("OAuth transaction must be a mapping")
        verifier = _string_option(transaction, "code_verifier")
        if verifier is None:
            raise ValidationError("Stored OAuth transaction is missing its code verifier")
        redirect_uri = _string_option(transaction, "redirect_uri")
        if redirect_uri is None:
            raise ValidationError("Stored OAuth transaction is missing its redirect URI")
        return self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "resource": _string_option(transaction, "resource") or self._api_origin(),
            }
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """``POST /oauth/token`` with ``grant_type=refresh_token`` — renew without the user.

        Access tokens last **1 hour**. A refresh token is valid for **30 days**,
        and every refresh returns a new one valid for another 30 days: a
        connection only expires after 30 days without a refresh, and then the
        user has to reconnect.

        **Every refresh retires the token it used and returns a new one.** A
        replayed refresh token cannot be told apart from a stolen one being
        replayed, so the server ends the whole connection when it sees one.
        Hold a per-connection lock, persist the returned ``refresh_token``
        before doing anything else with the response, and treat a
        :class:`~assinafy.errors.NetworkError` (a timeout or a dropped
        connection) as "maybe it worked": re-read what you stored before
        retrying, never retry with the old token. The SDK never retries this
        call.

        Request body (``application/x-www-form-urlencoded``)::

            grant_type=refresh_token
            refresh_token=<current-refresh-token>
            client_id=<client-id>
            client_secret=<client-secret>

        Example response (flat JSON, no ``data`` envelope)::

            {"access_token": "<new-access-token>", "token_type": "Bearer",
             "expires_in": 3600,
             "scope": "documents:read documents:write",
             "refresh_token": "<new-refresh-token>"}

        Raises:
            ValidationError: On an empty refresh token.
            ApiError: ``invalid_grant`` when the token was already used, has
                expired, lost ``offline_access``, or the user reconnected with
                different permissions — reconnect rather than retry.
        """
        self._require_id(refresh_token, "Refresh token")
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def revoke(
        self,
        token: str,
        token_type_hint: OAuthTokenTypeHint | None = None,
    ) -> None:
        """``POST /oauth/revoke`` — disconnect by revoking an access or refresh token.

        Call this when a user disconnects in your product, instead of only
        deleting your copy. Revoking the **refresh** token ends the whole
        connection, so pass that when you hold one.

        The endpoint answers ``200`` for every token outcome — revoked, already
        revoked, unknown, malformed — so it can never be used to probe whether a
        token exists, and success here is not evidence the token was real. Only
        failed client authentication answers ``401``.

        Request body (``application/x-www-form-urlencoded``)::

            token=<refresh-or-access-token>
            token_type_hint=refresh_token
            client_id=<client-id>
            client_secret=<client-secret>

        The documented success response is ``200`` with an empty body, which
        this method maps to ``None``.

        Args:
            token: The refresh token when one is stored, else the access token.
            token_type_hint: ``"refresh_token"`` or ``"access_token"``; omit
                when unsure.

        Raises:
            ValidationError: On an empty token or an unknown hint.
            ApiError: ``invalid_client`` on failed client authentication.
        """
        self._require_id(token, "Token")
        if token_type_hint is not None and token_type_hint not in _TOKEN_TYPE_HINTS:
            raise ValidationError(
                'token_type_hint must be "access_token" or "refresh_token"',
                {"token_type_hint": token_type_hint},
            )
        body = self._with_client_credentials({"token": token, "token_type_hint": token_type_hint})
        self._call_void(
            "Failed to revoke OAuth token",
            lambda: self._http.post("oauth/revoke", data=body),
        )

    def userinfo(self, access_token: str) -> dict[str, Any]:
        """``GET /oauth/userinfo`` — the OIDC claims of the user who authorized the token.

        Requires the ``openid`` scope; ``name`` additionally requires
        ``profile`` and ``email`` requires ``email``. Prefer this over decoding
        the ``id_token``, which needs full RS256/JWKS validation by a maintained
        OIDC library before any claim in it can be trusted.

        Request: no body. The token travels in ``Authorization: Bearer``, the
        only accepted method — an OAuth token sent as ``X-Api-Key`` or in the
        query string is refused. The owning client's own ``api_key`` is
        suppressed for this call so it cannot answer for the wrong identity.

        Example response (flat OIDC claims, no ``data`` envelope)::

            {"sub": "d6zqpbyog2v3xvxerwn8la94", "name": "Example User",
             "email": "person@example.com", "email_verified": true}

        ``sub`` is the user's stable identifier; the optional claims are ``null``
        or absent when the matching scope was not granted.

        Raises:
            ValidationError: On an empty access token.
            ApiError: ``401`` when the token expired or was revoked, ``403``
                when ``openid`` was not granted. Unlike the token and revocation
                endpoints, these arrive in the ordinary ``{status, data,
                message}`` envelope.
        """
        self._require_id(access_token, "Access token")
        return self._call_dict(
            "Failed to fetch OAuth userinfo",
            lambda: self._http.get(
                "oauth/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            ),
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def protected_resource_metadata(self) -> dict[str, Any]:
        """``GET /.well-known/oauth-protected-resource`` — at the API origin, outside ``/v1``.

        RFC 9728. Names the authorization server that issues tokens for this API
        and the scopes it accepts, and is what the ``resource_metadata="..."``
        parameter of a ``WWW-Authenticate`` challenge points at. Start an
        integration here, then read the authorization server's own document from
        ``authorization_servers[0]``.

        Sent without the client's credentials: the document sits above the
        ``/v1`` prefix and carries no workspace identity.

        Request: none.

        Example response (flat JSON, no ``data`` envelope)::

            {"resource": "https://api.assinafy.com.br",
             "authorization_servers": ["https://auth.assinafy.com.br"],
             "scopes_supported": ["documents:read", "documents:write",
                                  "templates:read", "templates:write",
                                  "account:read", "openid", "profile", "email"],
             "bearer_methods_supported": ["header"]}

        ``scopes_supported`` deliberately omits ``offline_access``: asking for a
        refresh token is a client concern, not something this resource is
        protected by.

        Raises:
            ApiError: When the deployment does not serve OAuth. The sandbox host
                answers ``403`` here, because this path sits above the ``/v1``
                prefix and is refused by its front-end proxy rather than reaching
                the API; ``/v1/oauth/*`` answers ``404`` there.
        """
        return self._metadata(self._api_origin(), PROTECTED_RESOURCE_METADATA_PATH)

    def authorization_server_metadata(self, issuer: str | None = None) -> dict[str, Any]:
        """``GET {issuer}/.well-known/oauth-authorization-server``.

        RFC 8414. Configure from this document rather than hardcoding endpoint
        URLs: pass its ``issuer`` and ``authorization_endpoint`` into
        :meth:`start_authorization`. It is served **only** by the authorization
        server, never by this API, so it is fetched without the client's
        credentials.

        Request: none.

        Example response (flat JSON, no ``data`` envelope)::

            {"issuer": "https://auth.assinafy.com.br",
             "authorization_endpoint": "https://auth.assinafy.com.br/oauth/authorize",
             "token_endpoint": "https://api.assinafy.com.br/v1/oauth/token",
             "revocation_endpoint": "https://api.assinafy.com.br/v1/oauth/revoke",
             "userinfo_endpoint": "https://api.assinafy.com.br/v1/oauth/userinfo",
             "jwks_uri": "https://auth.assinafy.com.br/.well-known/jwks.json",
             "scopes_supported": ["documents:read", "documents:write",
                                  "templates:read", "templates:write",
                                  "account:read", "openid", "profile", "email",
                                  "offline_access"],
             "response_types_supported": ["code"],
             "grant_types_supported": ["authorization_code", "refresh_token"],
             "code_challenge_methods_supported": ["S256"],
             "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
             "authorization_response_iss_parameter_supported": true,
             "client_id_metadata_document_supported": true}

        Validate the returned ``issuer`` against the one you expect before
        sending a secret to any endpoint it names.

        Args:
            issuer: The authorization server origin. Defaults to
                :data:`DEFAULT_ISSUER`; pass ``authorization_servers[0]`` from
                :meth:`protected_resource_metadata` to follow discovery.

        Raises:
            ValidationError: On a non-HTTPS issuer.
            ApiError: When the issuer does not serve the document.
        """
        origin = _https_origin(DEFAULT_ISSUER if issuer is None else issuer, "OAuth issuer")
        return self._metadata(origin, AUTHORIZATION_SERVER_METADATA_PATH)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _token(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a form-encoded token request.

        RFC 6749 §4.1.3 specifies ``application/x-www-form-urlencoded``, which
        is also what the published integration guide sends.
        """
        body = self._with_client_credentials(payload)
        self._logger.info("Requesting OAuth token", {"grant_type": payload.get("grant_type")})
        return self._call_dict(
            "Failed to exchange OAuth token",
            lambda: self._http.post("oauth/token", data=body),
        )

    def _with_client_credentials(self, payload: dict[str, Any]) -> dict[str, str]:
        """Add ``client_secret_post`` credentials and drop unset optional fields.

        Public applications authenticate with PKCE alone, so ``client_secret``
        is omitted rather than sent empty.
        """
        body = {key: value for key, value in payload.items() if value is not None}
        body["client_id"] = self._client_id
        if self._client_secret is not None:
            body["client_secret"] = self._client_secret
        return body

    def _metadata(self, origin: str, path: str) -> dict[str, Any]:
        """Fetch a discovery document from an origin's root, above the ``/v1`` prefix.

        The absolute URL takes the request outside the client's base path, which
        is exactly what makes
        :meth:`~assinafy.client.AssinafyClient._prepare_request` strip the
        workspace credentials before it leaves.
        """
        return self._call_dict(
            "Failed to fetch OAuth metadata",
            lambda: self._http.get(f"{origin}/{path}"),
        )

    def _api_origin(self) -> str:
        """This API's origin — the configured base URL without its path."""
        base = self._http.base_url
        port = "" if base.port is None else f":{base.port}"
        return f"{base.scheme}://{base.host}{port}"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _string_option(source: dict[str, Any], key: str) -> str | None:
    """Read a non-blank string from an untrusted mapping, else ``None``."""
    value = source.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _assert_code_verifier(code_verifier: Any) -> None:
    if not isinstance(code_verifier, str) or not _VERIFIER_RE.fullmatch(code_verifier):
        raise ValidationError(
            "PKCE code verifier must be 43-128 characters from A-Z a-z 0-9 - . _ ~"
        )


def _assert_redirect_uri(redirect_uri: Any) -> None:
    if not isinstance(redirect_uri, str) or not redirect_uri.strip():
        raise ValidationError("Redirect URI must be an absolute https:// URL")
    try:
        parsed = urlsplit(redirect_uri)
    except ValueError as err:
        raise ValidationError("Redirect URI must be an absolute https:// URL") from err
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValidationError(
            "Redirect URI must use https — plain http://localhost is not accepted, "
            "use an HTTPS tunnel",
            {"redirect_uri": redirect_uri},
        )
    if parsed.fragment or "#" in redirect_uri:
        raise ValidationError(
            "Redirect URI cannot contain a fragment", {"redirect_uri": redirect_uri}
        )


def _validate_scopes(scopes: Any) -> list[str]:
    if not isinstance(scopes, (list, tuple)) or not scopes:
        raise ValidationError("At least one OAuth scope is required")
    requested: list[str] = []
    for scope in scopes:
        if not isinstance(scope, str) or not scope.strip() or " " in scope:
            raise ValidationError(
                "OAuth scopes must be non-empty strings without spaces", {"scope": scope}
            )
        requested.append(scope)
    return requested


def _https_origin(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be an absolute https:// URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValidationError(f"{name} must use https", {name.lower(): value})
    return value.rstrip("/")
