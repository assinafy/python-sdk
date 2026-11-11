from __future__ import annotations

import builtins
import mimetypes
from typing import Any
from urllib.parse import urlsplit

from ..errors import ValidationError
from ..types import NOTIFICATION_POLICY_CODES
from ..utils import clean_params, load_file_source, stats_params, validate_boolean_preferences
from .base import BaseResource

_NOTIFICATION_SENDERS = frozenset({"User", "Account"})


class AccountResource(BaseResource):
    """Workspace administration endpoints under ``/accounts``.

    Account-returning methods expose this complete unwrapped shape::

        {"resource": "account", "id": "account-id", "name": "Acme Inc.",
         "primary_color": "aabbcc", "secondary_color": "112233",
         "notification_sender_type": "User", "roles": ["owner"],
         "is_delete_allowed": true, "created_at": "2026-06-03T03:54:16Z"}
    """

    def list(self) -> builtins.list[dict[str, Any]]:
        """``GET /accounts`` — list the authenticated user's workspaces.

        Example unwrapped response::

            [{"resource": "account", "id": "account-id", "name": "Acme Inc.",
              "primary_color": "aabbcc", "secondary_color": "112233",
              "notification_sender_type": "User", "roles": ["owner"],
              "is_delete_allowed": true,
              "created_at": "2026-06-03T03:54:16Z"}]

        Request body: none. OAuth returns only the connected workspace and
        needs no particular scope. Use its ID for the connection's other calls.
        """
        return self._call_plain_list("Failed to list accounts", lambda: self._http.get("accounts"))

    def create(self, name: str, notification_sender_type: str | None = None) -> dict[str, Any]:
        """``POST /accounts`` — create a workspace.

        Sends ``{"name": "Acme"}`` and, when provided,
        ``notification_sender_type`` (``"User"`` or ``"Account"``). It is
        optional; setting it later with :meth:`update` provides broad deployment
        compatibility. Returns the complete account payload
        documented on :class:`AccountResource`.

        Example response (``data`` envelope unwrapped)::

            {"resource": "account", "id": "account-id", "name": "Acme Inc.",
             "primary_color": "aabbcc", "secondary_color": "112233",
             "notification_sender_type": "User", "roles": ["owner"],
             "is_delete_allowed": true, "created_at": "2026-06-03T03:54:16Z"}
        """
        body: dict[str, Any] = {"name": self._require_id(name, "Account name")}
        if notification_sender_type is not None:
            _validate_notification_sender(notification_sender_type)
            body["notification_sender_type"] = notification_sender_type
        return self._call_dict(
            "Failed to create account", lambda: self._http.post("accounts", json=body)
        )

    def get(self, account_id: str | None = None, *, expand: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}`` — return one workspace.

        Returns the complete account payload documented on
        :class:`AccountResource`, plus ``limits`` for the current plan.
        ``limits.webhook_endpoints`` is 1 or 3; other limit keys may be added.
        This field is absent from account lists. OAuth requires ``account:read``.
        ``expand="signing_features"`` adds boolean DigitalCertificate,
        VerificationIdDocumentFaceMatchBasic, WhatsappNotification,
        VerificationBypass and Embed keys under ``signing_features``. These
        indicate plan eligibility; credits and assignment rules still apply.

        Request body: none.

        Example response (``data`` envelope unwrapped)::

            {"resource": "account", "id": "account-id", "name": "Acme Inc.",
             "primary_color": "aabbcc", "secondary_color": "112233",
             "notification_sender_type": "User", "roles": ["owner"],
             "is_delete_allowed": true, "limits": {"webhook_endpoints": 1},
             "created_at": "2026-06-03T03:54:16Z"}
        """
        if expand is not None and expand != "signing_features":
            raise ValidationError("expand must be signing_features")
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to fetch account",
            lambda: self._http.get(f"accounts/{acc_id}", params=clean_params({"expand": expand})),
        )

    def usage(self, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/usage`` — read plan and balances.

        No request body. Billing data is unavailable to third-party OAuth
        applications (403), regardless of scope. Response::

            {"plan": "Pro", "documents_renewal_date": "2026-12-01",
             "balances": {"documents": {"balance": 100, "limit": 100, "spent": 0},
                          "credits": {"balance": 10, "limit": null, "spent": 0}}}

        Plan and renewal date can be null. A null balance means unlimited;
        a null limit means no cycle limit or unlimited.
        """
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to fetch account usage", lambda: self._http.get(f"accounts/{acc_id}/usage")
        )

    def notification_policy(self, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/notification-policy`` — read workspace alerts.

        No request body. Every member can read; only owners can edit.
        Third-party OAuth applications receive 403. Response::

            {"editable": true, "owners_receive_all": false,
             "events": {"DocumentCompleted": true, "SignerDeclined": true,
              "DocumentCancelled": true, "DocumentAboutToExpire": true,
              "DocumentExpired": true, "DocumentExpirationReset": true,
              "DocumentProcessingFailed": true, "TemplateProcessingFailed": true,
              "SignerWhatsappFailed": true, "ContractRenewalNotice": true,
              "ContractExpiring": true, "ContractExpired": true, "ContractRenewed": true,
              "SignerViewed": false, "SignerSigned": true, "SignerIdentityReviewRequired": true}}

        Disabled events reach nobody on any channel, except the identity review
        email, which is always sent. ``owners_receive_all`` gives owners push
        alerts for every member's documents, subject to their own preferences.
        """
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to fetch notification policy",
            lambda: self._http.get(f"accounts/{acc_id}/notification-policy"),
        )

    def update_notification_policy(
        self, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/notification-policy`` — merge alert rules.

        Owners only; third-party OAuth applications receive 403. Send a partial
        ``events`` map and/or boolean ``owners_receive_all``. Omitted values stay
        unchanged. Example JSON::

            {"events": {"SignerViewed": true}, "owners_receive_all": true}

        Returns the full policy shown in :meth:`notification_policy`, including
        ``editable`` and all event flags. Unknown fields/codes, non-boolean values
        and an empty update are rejected before sending.
        """
        if not isinstance(payload, dict) or not payload:
            raise ValidationError("Notification policy must be a non-empty mapping")
        if payload.keys() - {"events", "owners_receive_all"}:
            raise ValidationError("Unknown notification policy fields")
        if "events" in payload:
            if not isinstance(payload["events"], dict):
                raise ValidationError("Notification policy events must be a mapping")
            if payload["events"]:
                validate_boolean_preferences(payload["events"], NOTIFICATION_POLICY_CODES)
        if "owners_receive_all" in payload and not isinstance(payload["owners_receive_all"], bool):
            raise ValidationError("owners_receive_all must be boolean")
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to update notification policy",
            lambda: self._http.put(f"accounts/{acc_id}/notification-policy", json=payload),
        )

    def list_embed_origins(self, account_id: str | None = None) -> builtins.list[dict[str, Any]]:
        """``GET /accounts/{account_id}/embed-origins`` — read allowed iframe origins.

        No request body. Requires the Embed plan feature; OAuth applications
        cannot use this endpoint. Returns oldest first::

            [{"id": "origin-id", "origin": "https://app.example.com",
              "created_at": "2026-11-04T12:05:00Z"}]
        """
        acc_id = self._account_id(account_id)
        return self._call_plain_list(
            "Failed to list embed origins",
            lambda: self._http.get(f"accounts/{acc_id}/embed-origins"),
        )

    def add_embed_origin(self, origin: str, account_id: str | None = None) -> dict[str, Any]:
        """``POST /accounts/{account_id}/embed-origins`` — allow an iframe origin.

        Sends ``{"origin": "https://app.example.com"}``. Use an exact HTTPS
        origin, without a path, query, fragment, credentials or wildcard; HTTP
        is allowed only for localhost and 127.0.0.1. A trailing slash is accepted.
        The server lowercases hosts and removes the slash and default port.
        Duplicate origins or more than ten entries return 400. Requires Embed;
        OAuth applications are refused. Response::

            {"id": "origin-id", "origin": "https://app.example.com",
             "created_at": "2026-11-04T12:05:00Z"}
        """
        _validate_embed_origin(origin)
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to add embed origin",
            lambda: self._http.post(f"accounts/{acc_id}/embed-origins", json={"origin": origin}),
        )

    def update_embed_origin(
        self, origin_id: str, origin: str, account_id: str | None = None
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}/embed-origins/{origin_id}`` — replace an origin.

        Sends ``{"origin": "https://app.example.com"}``, retaining the entry ID.
        Validation, plan and OAuth rules are the same as :meth:`add_embed_origin`.
        Returns ``{"id": "origin-id", "origin": "https://app.example.com",
        "created_at": "2026-11-04T12:05:00Z"}``; another entry with the same
        origin returns 400, and a missing ID returns 404.
        """
        _validate_embed_origin(origin)
        acc_id = self._account_id(account_id)
        oid = self._path_id(origin_id, "Origin ID")
        return self._call_dict(
            "Failed to update embed origin",
            lambda: self._http.put(
                f"accounts/{acc_id}/embed-origins/{oid}", json={"origin": origin}
            ),
        )

    def delete_embed_origin(self, origin_id: str, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/embed-origins/{origin_id}`` — remove an origin.

        No request body; ``data: []`` becomes ``None``. Requires Embed; OAuth
        applications are refused. Missing entries return 404. Removing the last
        origin disables embedding: new sessions return 409/embed_origins_missing.
        """
        acc_id = self._account_id(account_id)
        oid = self._path_id(origin_id, "Origin ID")
        self._call_void(
            "Failed to delete embed origin",
            lambda: self._http.delete(f"accounts/{acc_id}/embed-origins/{oid}"),
        )

    def update(
        self,
        body: dict[str, Any],
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``PUT /accounts/{account_id}`` — update ``name`` and/or sender type.

        Example JSON: ``{"name": "Acme 2", "notification_sender_type": "User"}``.
        Returns the complete account payload documented on
        :class:`AccountResource`.

        Example response (``data`` envelope unwrapped)::

            {"resource": "account", "id": "account-id", "name": "Acme Inc.",
             "primary_color": "aabbcc", "secondary_color": "112233",
             "notification_sender_type": "User", "roles": ["owner"],
             "is_delete_allowed": true, "created_at": "2026-06-03T03:54:16Z"}
        """
        if not isinstance(body, dict):
            raise ValidationError("Account update must be a mapping")
        if not body:
            raise ValidationError("At least one account field is required")
        unknown = body.keys() - {"name", "notification_sender_type"}
        if unknown:
            raise ValidationError(f"Unknown account fields: {', '.join(sorted(unknown))}")
        if "name" in body:
            self._require_id(body["name"], "Account name")
        if "notification_sender_type" in body:
            _validate_notification_sender(body["notification_sender_type"])
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to update account",
            lambda: self._http.put(f"accounts/{acc_id}", json=body),
        )

    def delete(self, account_id: str | None = None, *, force: bool = False) -> None:
        """``DELETE /accounts/{account_id}`` — irreversibly delete a workspace.

        When ``force=True``, sends ``{"force": true}`` to cancel an active
        paid subscription and proceed; otherwise the JSON body is omitted.
        OpenAPI returns ``data: []`` on success; the SDK maps that empty result
        to ``None``.
        """
        if not isinstance(force, bool):
            raise ValidationError("force must be boolean")
        acc_id = self._account_id(account_id)
        self._call_void(
            "Failed to delete account",
            lambda: (
                self._http.request("DELETE", f"accounts/{acc_id}", json={"force": True})
                if force
                else self._http.delete(f"accounts/{acc_id}")
            ),
        )

    def theme(self, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}/theme`` — return branding.

        Example: ``{"account_name": "Acme", "primary_color": "2072b9",
        "secondary_color": "ffffff", "logo": null}``.

        Request body: none.
        """
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to fetch account theme",
            lambda: self._http.get(f"accounts/{acc_id}/theme"),
        )

    def stats(
        self,
        granularity: str = "monthly",
        month: str | None = None,
        account_id: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """``GET /accounts/{account_id}/stats`` — return document KPI rows.

        Complete unwrapped response example::

            [{"period": "2026-06", "documents_uploaded": 42,
              "documents_sent": 37, "signature_requests": 61,
              "signature_requests_notification_email": 55,
              "signature_requests_notification_whatsapp": 18,
              "signature_requests_notification_bypass": 3,
              "signature_requests_verification_email": 48,
              "signature_requests_verification_whatsapp": 6,
              "signature_requests_verification_bypass": 3,
              "signature_requests_verification_digital_certificate": 4,
              "signature_requests_viewed": 44,
              "signature_requests_completed": 52,
              "documents_certified": 30}]

        Request body: none.

        Query: ``granularity=monthly`` (default), or
        ``granularity=daily&month=2026-06``; daily queries require ``month``.
        """
        acc_id = self._account_id(account_id)
        params = stats_params(granularity, month)
        return self._call_plain_list(
            "Failed to fetch account stats",
            lambda: self._http.get(f"accounts/{acc_id}/stats", params=params),
        )

    def download_logo(self, account_id: str | None = None) -> bytes:
        """``GET /accounts/{account_id}/logo`` — return raw image bytes.

        Request body: none.
        """
        acc_id = self._account_id(account_id)
        return self._call_binary(
            "Failed to download account logo",
            lambda: self._http.get(f"accounts/{acc_id}/logo"),
        )

    def upload_logo(
        self,
        source: dict[str, Any],
        account_id: str | None = None,
    ) -> None:
        """``POST /accounts/{account_id}/logo`` — upload multipart ``file``.

        ``source`` is ``{"file_path": "logo.png"}`` or
        ``{"buffer": image_bytes, "file_name": "logo.png"}``. The multipart
        part is named ``file``. Success is ``None``; the API envelope contains
        only ``status`` and ``message``.
        """
        buffer, file_name = load_file_source(source)
        if not buffer:
            raise ValidationError("Logo buffer is empty")
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        acc_id = self._account_id(account_id)
        self._call_void(
            "Failed to upload account logo",
            lambda: self._http.post(
                f"accounts/{acc_id}/logo",
                files={"file": (file_name, buffer, content_type)},
            ),
        )

    def delete_logo(self, account_id: str | None = None) -> None:
        """``DELETE /accounts/{account_id}/logo`` — remove the logo.

        Request body: none. Success is ``None``; the API envelope contains only
        ``status`` and ``message``.
        """
        acc_id = self._account_id(account_id)
        self._call_void(
            "Failed to delete account logo",
            lambda: self._http.delete(f"accounts/{acc_id}/logo"),
        )


def _validate_notification_sender(value: Any) -> None:
    if not isinstance(value, str) or value not in _NOTIFICATION_SENDERS:
        raise ValidationError('notification_sender_type must be "User" or "Account"')


def _validate_embed_origin(origin: Any) -> None:
    if not isinstance(origin, str) or any(c.isspace() or ord(c) < 32 for c in origin):
        raise ValidationError("Embed origin must be an exact HTTP(S) origin")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
        valid = (
            parsed.hostname
            and not any(c in origin for c in "*\\?#")
            and not parsed.username
            and not parsed.password
            and "@" not in parsed.netloc
            and not parsed.netloc.endswith(":")
            and parsed.path in {"", "/"}
            and (port is None or port > 0)
            and (
                parsed.scheme == "https"
                or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
            )
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValidationError("Embed origin must be an exact HTTPS origin or local HTTP origin")
