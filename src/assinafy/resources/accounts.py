from __future__ import annotations

import builtins
import mimetypes
import re
from typing import Any

from ..errors import ValidationError
from .base import BaseResource
from .documents import _load_source

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
        """
        return self._call_plain_list("Failed to list accounts", lambda: self._http.get("accounts"))

    def create(self, name: str, notification_sender_type: str | None = None) -> dict[str, Any]:
        """``POST /accounts`` — create a workspace.

        Sends ``{"name": "Acme"}`` and, when provided,
        ``notification_sender_type`` (``"User"`` or ``"Account"``). It is
        optional because the current sandbox rejects both
        explicit values while accepting an omitted field; the published
        contract documents the enum. Returns the complete account payload
        documented on :class:`AccountResource`.
        """
        body: dict[str, Any] = {"name": self._require_id(name, "Account name")}
        if notification_sender_type is not None:
            _validate_notification_sender(notification_sender_type)
            body["notification_sender_type"] = notification_sender_type
        return self._call_dict(
            "Failed to create account", lambda: self._http.post("accounts", json=body)
        )

    def get(self, account_id: str | None = None) -> dict[str, Any]:
        """``GET /accounts/{account_id}`` — return one workspace.

        Returns the complete account payload documented on
        :class:`AccountResource`.
        """
        acc_id = self._account_id(account_id)
        return self._call_dict(
            "Failed to fetch account", lambda: self._http.get(f"accounts/{acc_id}")
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
        Success returns ``None``; the API response has no ``data`` payload.
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

        This follows the current published contract. The sandbox returned 404
        for this published route on 2026-08-20; no client-side fallback can
        synthesize authoritative KPI data.

        Complete unwrapped response example::

            [{"period": "2026-06", "documents_uploaded": 42,
              "documents_sent": 37, "signature_requests": 61,
              "signature_requests_email": 55,
              "signature_requests_whatsapp": 18,
              "signature_requests_viewed": 44,
              "signature_requests_completed": 52,
              "documents_certified": 30}]
        """
        acc_id = self._account_id(account_id)
        params = _stats_params(granularity, month)
        return self._call_plain_list(
            "Failed to fetch account stats",
            lambda: self._http.get(f"accounts/{acc_id}/stats", params=params),
        )

    def download_logo(self, account_id: str | None = None) -> bytes:
        """``GET /accounts/{account_id}/logo`` — return raw image bytes."""
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
        buffer, file_name = _load_source(source)
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


def _stats_params(granularity: str, month: str | None) -> dict[str, str]:
    if not isinstance(granularity, str) or granularity not in {"monthly", "daily"}:
        raise ValidationError('granularity must be "monthly" or "daily"')
    if month is not None and (
        not isinstance(month, str) or re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None
    ):
        raise ValidationError("month must use YYYY-MM format")
    if granularity == "daily" and month is None:
        raise ValidationError("month is required for daily granularity")
    return {k: v for k, v in {"granularity": granularity, "month": month}.items() if v}
