from __future__ import annotations

from typing import Any, cast

from ..errors import ValidationError
from ..types import NOTIFICATION_PREFERENCE_CODES, NotificationPreferenceCode
from .accounts import _stats_params
from .base import BaseResource


class UserResource(BaseResource):
    """Authenticated-user endpoints under ``/users/self``.

    The documented complete user payload is::

        {"id": "user-id", "name": "Example User", "email": "user@example.com",
         "telephone": null, "government_id": null, "is_email_verified": true,
         "has_accepted_terms": true, "created_at": "2026-06-03T03:54:16Z",
         "to_be_deleted_at": null}
    """

    def me(self) -> dict[str, Any]:
        """``GET /users/self`` — return the authenticated user.

        OpenAPI documents a direct user object containing ``id``, ``name``,
        ``email``, nullable ``telephone`` / ``government_id``, verification and
        terms flags, ``created_at``, and nullable ``to_be_deleted_at``. The live
        API may wrap that user beside ``accounts``; this method preserves the
        returned data shape without discarding either representation.
        """
        return self._call_dict("Failed to fetch current user", lambda: self._http.get("users/self"))

    def stats(
        self,
        granularity: str = "monthly",
        month: str | None = None,
    ) -> list[dict[str, Any]]:
        """``GET /users/self/stats`` — return cross-account KPI rows.

        This follows the current published contract. The sandbox returned 404
        for this published route on 2026-08-20.

        The response uses the complete KPI-row shape documented by
        :meth:`~assinafy.resources.accounts.AccountResource.stats`.
        """
        params = _stats_params(granularity, month)
        return self._call_plain_list(
            "Failed to fetch user stats",
            lambda: self._http.get("users/self/stats", params=params),
        )

    def notification_preferences(self) -> dict[NotificationPreferenceCode, bool]:
        """``GET /users/self/notification-preferences`` — return all preferences.

        This follows the current published contract. The sandbox returned 404
        for this published route on 2026-08-20.

        Complete unwrapped response::

            {"DocumentCompleted": true, "SignerDeclined": true,
             "DocumentCancelled": true, "DocumentAboutToExpire": true,
             "DocumentExpired": true, "DocumentExpirationReset": true,
             "DocumentProcessingFailed": true,
             "TemplateProcessingFailed": true, "SignerWhatsappFailed": true}
        """
        return cast(
            dict[NotificationPreferenceCode, bool],
            self._call_dict(
                "Failed to fetch notification preferences",
                lambda: self._http.get("users/self/notification-preferences"),
            ),
        )

    def update_notification_preferences(
        self,
        preferences: dict[NotificationPreferenceCode, bool],
    ) -> dict[NotificationPreferenceCode, bool]:
        """``PUT /users/self/notification-preferences`` — merge a partial map.

        Send one or more of the nine keys documented by
        :meth:`notification_preferences`; values must be booleans. Omitted keys
        keep their values. The request is the supplied partial map; the
        response is the complete nine-key map shown by
        :meth:`notification_preferences`.
        """
        if not isinstance(preferences, dict):
            raise ValidationError("Notification preferences must be a mapping")
        if not preferences:
            raise ValidationError("At least one notification preference is required")
        for code, enabled in preferences.items():
            if code not in NOTIFICATION_PREFERENCE_CODES:
                raise ValidationError(f"Unknown notification preference: {code}")
            if not isinstance(enabled, bool):
                raise ValidationError(f"Notification preference {code} must be boolean")
        return cast(
            dict[NotificationPreferenceCode, bool],
            self._call_dict(
                "Failed to update notification preferences",
                lambda: self._http.put("users/self/notification-preferences", json=preferences),
            ),
        )
