from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params
from .base import BaseResource


def build_assignment_payload(
    payload: dict[str, Any],
    allow_signers_without_id: bool = False,
) -> dict[str, Any]:
    """Normalize assignment payloads into the documented request body.

    Accepts ``signers`` as a list of either plain string IDs (legacy convenience)
    or ``{id, verification_method, notification_methods}`` dicts. Also accepts
    the legacy ``signer_ids`` key as a synonym for ``signers``. Drops ``None``
    values from the optional fields (``message``, ``expires_at``,
    ``copy_receivers``, ``entries``) so the request body matches the API docs
    exactly.

    ``allow_signers_without_id`` is for ``estimate-cost`` callers that supply
    signer descriptors without IDs.
    """
    method = payload.get("method", "virtual")
    raw_signers = payload.get("signers") or payload.get("signer_ids") or []
    signers = list(raw_signers) if isinstance(raw_signers, (list, tuple)) else []
    entries = payload.get("entries")

    if not signers and not (method == "collect" and entries):
        raise ValidationError(
            "At least one signer is required",
            {"signers": payload.get("signers") or payload.get("signer_ids")},
        )

    body: dict[str, Any] = clean_params(
        {
            "method": method,
            "message": payload.get("message"),
            "expires_at": payload.get("expires_at"),
            "copy_receivers": payload.get("copy_receivers"),
            "entries": entries,
        }
    )
    if signers:
        body["signers"] = [
            _normalise_signer_ref(ref, allow_signers_without_id) for ref in signers
        ]
    return body


def _normalise_signer_ref(ref: Any, allow_without_id: bool) -> dict[str, Any]:
    if isinstance(ref, str):
        if not ref:
            raise ValidationError("Signer ID cannot be empty")
        return {"id": ref}

    if isinstance(ref, dict):
        signer_id = ref.get("id") or ref.get("signer_id")
        normalised = clean_params(
            {
                "id": signer_id,
                "verification_method": ref.get("verification_method"),
                "notification_methods": ref.get("notification_methods"),
            }
        )
        if signer_id or allow_without_id:
            return normalised

    raise ValidationError("Invalid signer reference", {"ref": ref})


class AssignmentResource(BaseResource):
    """Assignment endpoints — invitations, signing, notifications."""

    def create(
        self,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """``POST /documents/{document_id}/assignments``.

        ``payload`` may contain ``method`` (``virtual``/``collect``),
        ``signers``, ``signer_ids`` (legacy alias), ``message``, ``expires_at``,
        ``copy_receivers``, and (collect-only) ``entries``. See
        :func:`build_assignment_payload` for full normalization rules.
        """
        doc_id = self._require_id(document_id, "Document ID")
        body = build_assignment_payload(payload)
        self._logger.info(
            "Creating assignment",
            {"document_id": doc_id, "signers": len(payload.get("signers") or [])},
        )
        return self._call(
            "Failed to create assignment",
            lambda: self._http.post(f"documents/{doc_id}/assignments", json=body),
        )

    def estimate_cost(
        self,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """``POST /documents/{document_id}/assignments/estimate-cost``.

        Accepts the same payload shape as :meth:`create` and additionally
        permits signer descriptors without ``id`` (just channel hints).
        """
        doc_id = self._require_id(document_id, "Document ID")
        return self._call(
            "Failed to estimate assignment cost",
            lambda: self._http.post(
                f"documents/{doc_id}/assignments/estimate-cost",
                json=build_assignment_payload(payload, allow_signers_without_id=True),
            ),
        )

    def reset_expiration(
        self,
        document_id: str,
        assignment_id: str,
        expires_at: str,
    ) -> dict[str, Any]:
        """``PUT /documents/{document_id}/assignments/{assignment_id}/reset-expiration``.

        ``expires_at`` must be ISO 8601 (e.g. ``2030-08-03T21:00:00Z``).
        """
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        expiry = self._require_id(expires_at, "Expiration date")
        return self._call(
            "Failed to update assignment expiration",
            lambda: self._http.put(
                f"documents/{doc_id}/assignments/{asg_id}/reset-expiration",
                json={"expires_at": expiry},
            ),
        )

    def get_for_signer(
        self,
        signer_access_code: str,
        has_accepted_terms: bool | None = None,
    ) -> dict[str, Any]:
        """``GET /sign?signer-access-code=...`` — assignment view for signer."""
        access_code = self._require_id(signer_access_code, "Signer access code")
        return self._call(
            "Failed to fetch signer assignment",
            lambda: self._http.get(
                "sign",
                params=clean_params(
                    {
                        "signer_access_code": access_code,
                        "has_accepted_terms": has_accepted_terms,
                    },
                    QUERY_PARAM_ALIASES,
                ),
            ),
        )

    def sign(
        self,
        document_id: str,
        assignment_id: str,
        entries: list[dict[str, Any]],
        signer_access_code: str,
    ) -> dict[str, Any]:
        """``POST /documents/{document_id}/assignments/{assignment_id}``.

        For collect-method assignments. ``entries`` is the list of
        ``{itemId, fieldId, pageId, value}`` objects per the API docs. For
        virtual assignments, the signer must have called
        :meth:`SignerResource.confirm_data` first.
        """
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        if not entries:
            raise ValidationError("At least one assignment entry is required")
        return self._call(
            "Failed to sign assignment",
            lambda: self._http.post(
                f"documents/{doc_id}/assignments/{asg_id}",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json=entries,
            ),
        )

    def decline(
        self,
        document_id: str,
        assignment_id: str,
        decline_reason: str,
        signer_access_code: str,
    ) -> None:
        """``PUT /documents/{document_id}/assignments/{assignment_id}/reject``."""
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        reason = self._require_id(decline_reason, "Decline reason")
        self._call_void(
            "Failed to decline assignment",
            lambda: self._http.put(
                f"documents/{doc_id}/assignments/{asg_id}/reject",
                params=clean_params(
                    {"signer_access_code": access_code},
                    QUERY_PARAM_ALIASES,
                ),
                json={"decline_reason": reason},
            ),
        )

    def whatsapp_notifications(
        self,
        document_id: str,
        assignment_id: str,
    ) -> list[dict[str, Any]]:
        """``GET /documents/{document_id}/assignments/{assignment_id}/whatsapp-notifications``."""
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        result = self._call(
            "Failed to list WhatsApp notifications",
            lambda: self._http.get(
                f"documents/{doc_id}/assignments/{asg_id}/whatsapp-notifications"
            ),
        )
        return result if isinstance(result, list) else []

    def resend_notification(
        self,
        document_id: str,
        assignment_id: str,
        signer_id: str,
    ) -> dict[str, Any]:
        """Resend a signer's notification for an assignment.

        ``PUT /documents/{document_id}/assignments/{assignment_id}/signers/{signer_id}/resend``.
        """
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        sid = self._require_id(signer_id, "Signer ID")
        return self._call(
            "Failed to resend signer notification",
            lambda: self._http.put(
                f"documents/{doc_id}/assignments/{asg_id}/signers/{sid}/resend"
            ),
        )

    def estimate_resend_cost(
        self,
        document_id: str,
        assignment_id: str,
        signer_id: str,
    ) -> dict[str, Any]:
        """Estimate the cost of resending a signer's notification.

        ``POST /documents/{document_id}/assignments/{assignment_id}/signers/{signer_id}/estimate-resend-cost``.
        """  # noqa: E501
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        sid = self._require_id(signer_id, "Signer ID")
        return self._call(
            "Failed to estimate resend cost",
            lambda: self._http.post(
                f"documents/{doc_id}/assignments/{asg_id}/signers/{sid}/estimate-resend-cost"
            ),
        )
