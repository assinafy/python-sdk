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
    or ``{id, verification_method, notification_methods, step}`` dicts. Also
    accepts the legacy ``signer_ids`` key as a synonym for ``signers``. Drops
    ``None`` values from the optional fields (``message``, ``expires_at``,
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
                "step": ref.get("step"),
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
        """``POST /documents/{document_id}/assignments`` — request signatures.

        ``payload`` may contain ``method`` (``virtual``/``collect``),
        ``signers``, ``signer_ids`` (legacy alias), ``message``, ``expires_at``,
        ``copy_receivers``, and (collect-only) ``entries``. Each ``signers``
        entry may carry ``verification_method``, ``notification_methods`` and a
        ``step`` (sequential signing order). See :func:`build_assignment_payload`
        for full normalization rules.

        Example request body (JSON)::

            {
              "method": "virtual",
              "message": "Please sign",
              "signers": [
                {"id": "1031ff86...", "verification_method": "Email",
                 "notification_methods": ["Email"], "step": 1}
              ]
            }

        Example response (``data`` envelope unwrapped, trimmed)::

            {
              "resource": "assignment",
              "id": "1031ff87acb9870bb5a0f5a97f16",
              "sender_email": "owner@example.com",
              "method": "virtual",
              "expires_at": null,
              "message": "Please sign",
              "signers": [
                {"id": "1031ff86...", "full_name": "John Doe",
                 "email": "john@example.com", "verification_method": "Email",
                 "notification_methods": ["Email"], "step": 1, "notified": true,
                 "completed": false}
              ],
              "copy_receivers": [],
              "items": [{"id": "1031ff87...", "field": {"type": "virtual"},
                         "completed": false}],
              "summary": {"signer_count": 1, "completed_count": 0},
              "signing_urls": [{"signer_id": "1031ff86...",
                                "url": "https://app.assinafy.com.br/sign/..."}]
            }
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

        Example request body (JSON)::

            {"method": "virtual",
             "signers": [{"verification_method": "Whatsapp",
                          "notification_methods": ["Whatsapp"]}]}

        Example response (``data`` envelope unwrapped)::

            {"documents": 1, "credits": 0, "needs_extra_document": false,
             "extra_document_cost": 0, "total_credits": 0, "breakdown": [],
             "document_balance": 66, "credit_balance": 0,
             "has_sufficient_resources": true, "blocking_reason": null,
             "message": null}
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
        expires_at: str | None,
    ) -> dict[str, Any]:
        """``PUT /documents/{document_id}/assignments/{assignment_id}/reset-expiration``.

        ``expires_at`` must be an ISO 8601 timestamp (e.g.
        ``2030-08-03T21:00:00Z``) or ``None``. Per the docs, a ``null`` value is
        accepted and clears the expiration (the assignment no longer expires);
        the key is always sent so the server can apply the change. An empty
        string is rejected as malformed.

        Example request body (JSON)::

            {"expires_at": "2030-08-03T21:00:00Z"}   # or {"expires_at": null}

        Example response (``data`` envelope unwrapped, trimmed)::

            {"resource": "assignment", "id": "1031ff87...",
             "method": "virtual", "expires_at": "2030-08-03T21:00:00Z",
             "signers": [...], "items": [...],
             "summary": {"signer_count": 2, "completed_count": 1}}
        """
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        if expires_at == "":
            raise ValidationError(
                "expires_at must be an ISO 8601 timestamp, or None to clear the expiration"
            )
        return self._call(
            "Failed to update assignment expiration",
            lambda: self._http.put(
                f"documents/{doc_id}/assignments/{asg_id}/reset-expiration",
                json={"expires_at": expires_at},
            ),
        )

    def get_for_signer(
        self,
        signer_access_code: str,
        has_accepted_terms: bool | None = None,
    ) -> dict[str, Any]:
        """``GET /sign?signer-access-code=...`` — assignment view for a signer.

        Returns the document-and-assignment view the signer is allowed to see.
        Requires a valid signer access code obtained through the signer
        verification flow; an invalid/expired code returns 401, and a 409 is
        returned while a virtual assignment's document is still being prepared.

        Example response (``data`` envelope unwrapped, trimmed)::

            {"id": "615213ed...", "name": "contract.pdf", "status": "pending",
             "assignment": {"id": "615606ef...", "method": "collect",
                            "signers": [...], "items": [...]},
             "artifacts": {"original": "https://.../download/original"},
             "current_signer": {"id": "6152...", "full_name": "Till Man"}}
        """
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

        Submits a signer's completed items. ``entries`` is the documented list
        of ``{itemId, fieldId, pageId, value}`` objects (sent as the raw JSON
        request body). For virtual assignments, the signer must have called
        :meth:`SignerResource.confirm_data` first.

        Example request body (JSON array)::

            [{"itemId": "615605f8...", "fieldId": "61521202...",
              "pageId": "615213ed...", "value": "John Doe"}]

        Returns the updated assignment object (``data`` envelope unwrapped).
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
        """``PUT /documents/{document_id}/assignments/{assignment_id}/reject``.

        Records a signer's refusal to sign. ``decline_reason`` is required.

        Example request body (JSON)::

            {"decline_reason": "I do not agree with the terms."}
        """
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
        """``GET /documents/{document_id}/assignments/{assignment_id}/whatsapp-notifications``.

        Lists the rendered WhatsApp notification messages sent for the
        assignment (header/body/buttons text exactly as the signer sees them).

        Example response (``data`` envelope unwrapped)::

            [{"sent_at": 1710000000,
              "header": "Documento para assinatura: Contrato",
              "body": "Oi, Maria.\\n\\nJoão enviou um documento...",
              "buttons": [{"text": "Abrir documento"}],
              "phone_number": "+5511999990001",
              "signer_id": "1031ff86..."}]
        """
        doc_id = self._require_id(document_id, "Document ID")
        asg_id = self._require_id(assignment_id, "Assignment ID")
        return self._call_plain_list(
            "Failed to list WhatsApp notifications",
            lambda: self._http.get(
                f"documents/{doc_id}/assignments/{asg_id}/whatsapp-notifications"
            ),
        )

    def resend_notification(
        self,
        document_id: str,
        assignment_id: str,
        signer_id: str,
    ) -> dict[str, Any]:
        """``PUT /documents/{document_id}/assignments/{assignment_id}/signers/{signer_id}/resend``.

        Resends a signer's signature-request notification.

        Example response (``data`` envelope unwrapped)::

            {"is_sent": true, "document_id": "1031ff86...",
             "signer_id": "1031ff86..."}
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
        """``POST /documents/{document_id}/assignments/{assignment_id}/signers/{signer_id}/estimate-resend-cost``.

        Estimates the cost of resending a signer's notification.

        Example response (``data`` envelope unwrapped)::

            {"total": 0,
             "breakdown": [{"code": "NotificationEmailResend",
                            "name": "Email Notification Resend", "cost": 0}],
             "credit_balance": 0, "has_sufficient_credits": true}
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
