from __future__ import annotations

import builtins
from typing import Any

from ..errors import ValidationError
from ..types import SignerReference
from ..utils import QUERY_PARAM_ALIASES, clean_params, validate_datetime
from .base import BaseResource

_ASSIGNMENT_METHODS = frozenset({"virtual", "collect"})
_VERIFICATION_METHODS = frozenset({"Email", "Whatsapp", "DigitalCertificate"})
_NOTIFICATION_METHODS = frozenset({"Email", "Whatsapp"})
_SIGNER_REFERENCE_FIELDS = frozenset(
    {"id", "signer_id", "verification_method", "notification_methods", "step"}
)
_ASSIGNMENT_FIELDS = frozenset(
    {"method", "signers", "signer_ids", "message", "expires_at", "copy_receivers", "entries"}
)
_ESTIMATE_FIELDS = frozenset({"method", "signers", "signer_ids", "entries"})
_ESTIMATE_SIGNER_FIELDS = frozenset(
    {"id", "signer_id", "verification_method", "notification_methods"}
)


def build_assignment_payload(
    payload: dict[str, Any],
    allow_signers_without_id: bool = False,
    allow_empty: bool = False,
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
    if not isinstance(payload, dict):
        raise ValidationError("Assignment payload must be a mapping")
    unknown = payload.keys() - _ASSIGNMENT_FIELDS
    if unknown:
        raise ValidationError(f"Unknown assignment fields: {', '.join(sorted(unknown))}")
    if "signers" in payload and "signer_ids" in payload:
        raise ValidationError("Use signers or signer_ids, not both")
    method = payload.get("method", "virtual")
    if not isinstance(method, str) or method not in _ASSIGNMENT_METHODS:
        raise ValidationError('method must be "virtual" or "collect"')
    raw_signers = payload.get("signers") or payload.get("signer_ids") or []
    if not isinstance(raw_signers, (list, tuple)):
        raise ValidationError("signers must be a list")
    signers: list[SignerReference] = list(raw_signers)
    entries = payload.get("entries")
    if entries is not None and (
        not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries)
    ):
        raise ValidationError("entries must be a list")
    message = payload.get("message")
    if message is not None and not isinstance(message, str):
        raise ValidationError("message must be a string")
    expires_at = payload.get("expires_at")
    if expires_at is not None:
        validate_datetime(expires_at, "expires_at")
    copy_receivers = payload.get("copy_receivers")
    if copy_receivers is not None and (
        not isinstance(copy_receivers, list)
        or any(not isinstance(receiver, str) or not receiver for receiver in copy_receivers)
    ):
        raise ValidationError("copy_receivers must be a list of signer IDs")

    if not allow_empty and not signers:
        raise ValidationError(
            "At least one signer is required",
            {"signers": payload.get("signers") or payload.get("signer_ids")},
        )
    if not allow_empty and method == "collect" and not entries:
        raise ValidationError("collect assignments require at least one entry")

    body: dict[str, Any] = clean_params(
        {
            "method": method,
            "message": payload.get("message"),
            "expires_at": payload.get("expires_at"),
            "copy_receivers": copy_receivers,
            "entries": entries,
        }
    )
    if signers:
        normalised = [_normalise_signer_ref(ref, allow_signers_without_id) for ref in signers]
        _validate_signer_steps(normalised)
        body["signers"] = normalised
    return body


def _normalise_signer_ref(ref: SignerReference, allow_without_id: bool) -> dict[str, Any]:
    if isinstance(ref, str):
        if not ref:
            raise ValidationError("Signer ID cannot be empty")
        return {"id": ref}

    if isinstance(ref, dict):
        unknown = ref.keys() - _SIGNER_REFERENCE_FIELDS
        if unknown:
            raise ValidationError(f"Unknown signer fields: {', '.join(sorted(unknown))}")
        if "id" in ref and "signer_id" in ref:
            raise ValidationError("Use signer id or signer_id, not both")
        signer_id = ref.get("id") or ref.get("signer_id")
        if signer_id is not None and (not isinstance(signer_id, str) or not signer_id):
            raise ValidationError("Signer ID must be a non-empty string")
        verification_method = ref.get("verification_method")
        if verification_method is not None and (
            not isinstance(verification_method, str)
            or verification_method not in _VERIFICATION_METHODS
        ):
            raise ValidationError("Invalid signer verification_method")
        notification_methods = ref.get("notification_methods")
        if notification_methods is not None and (
            not isinstance(notification_methods, list)
            or any(
                not isinstance(item, str) or item not in _NOTIFICATION_METHODS
                for item in notification_methods
            )
        ):
            raise ValidationError("Invalid signer notification_methods")
        step = ref.get("step")
        if step is not None and (not isinstance(step, int) or isinstance(step, bool) or step < 1):
            raise ValidationError("Signer step must be a positive integer")
        normalised = clean_params(
            {
                "id": signer_id,
                "verification_method": verification_method,
                "notification_methods": notification_methods,
                "step": step,
            }
        )
        if signer_id or allow_without_id:
            return normalised

    raise ValidationError("Invalid signer reference", {"ref": ref})


def _validate_signer_steps(signers: list[dict[str, Any]]) -> None:
    steps = [signer.get("step") for signer in signers]
    if any(step is not None for step in steps):
        if any(step is None for step in steps):
            raise ValidationError("Every signer must provide step when signing order is used")
        numbered_steps = [
            step for step in steps if isinstance(step, int) and not isinstance(step, bool)
        ]
        if len(numbered_steps) != len(steps):
            raise ValidationError("Signer steps must be positive integers")
        if set(numbered_steps) != set(range(1, max(numbered_steps) + 1)):
            raise ValidationError("Signer steps must be contiguous starting at 1")
    for signer, step in zip(signers, steps, strict=True):
        if (
            signer.get("verification_method") == "DigitalCertificate"
            and sum(other_step == step for other_step in steps) > 1
        ):
            raise ValidationError("DigitalCertificate signers must be alone in their step")


def _build_estimate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Assignment estimate payload must be a mapping")
    unknown = payload.keys() - _ESTIMATE_FIELDS
    if unknown:
        raise ValidationError(f"Unknown assignment estimate fields: {', '.join(sorted(unknown))}")
    raw_signers = payload.get("signers") or payload.get("signer_ids") or []
    if isinstance(raw_signers, (list, tuple)):
        for signer in raw_signers:
            if isinstance(signer, dict):
                signer_unknown = signer.keys() - _ESTIMATE_SIGNER_FIELDS
                if signer_unknown:
                    raise ValidationError(
                        "Unknown assignment estimate signer fields: "
                        f"{', '.join(sorted(signer_unknown))}"
                    )
    body = build_assignment_payload(
        payload,
        allow_signers_without_id=True,
        allow_empty=True,
    )
    if "signers" in body:
        body["signers"] = [
            {
                key: value
                for key, value in signer.items()
                if key in {"verification_method", "notification_methods"}
            }
            for signer in body["signers"]
        ]
    return body


class AssignmentResource(BaseResource):
    """Assignment endpoints — invitations, signing, notifications.

    Assignment-returning methods expose this complete top-level shape::

        {"resource": "assignment", "id": "assignment-id",
         "sender_email": "sender@example.com", "method": "virtual",
         "expires_at": null, "message": null,
         "signers": [{"resource": "signer", "id": "signer-id",
                       "full_name": "Example Signer", "email": "signer@example.com",
                       "whatsapp_phone_number": null, "has_accepted_terms": false,
                       "verification_method": "Email",
                       "notification_methods": ["Email"], "step": 1,
                       "notified": true, "completed": false,
                       "notification_history": [
                           {"event": "signature_request", "status": "sent",
                            "error_code": null, "error_message": null,
                            "sent_at": "2026-08-26T12:00:00Z", "failed_at": null}
                       ]}],
         "copy_receivers": [],
         "items": [{"id": "item-id",
                    "page": {"id": "page-id", "number": 1, "height": 2100,
                             "width": 1275, "download_url": "https://api.example/page"},
                    "signer": {"id": "signer-id", "full_name": "Example Signer",
                               "email": "signer@example.com"},
                    "field": {"id": "field-id", "name": "Signature",
                              "type": "signature"},
                    "display_settings": {"left": 69, "top": 282, "width": 421,
                                         "height": 45.86, "fontFamily": "Arial",
                                         "fontSize": 18,
                                         "backgroundColor": "#D5EBFF"},
                    "value": null, "completed": false}],
         "summary": {"signer_count": 1, "completed_count": 0,
                     "signers": [{"id": "signer-id", "full_name": "Example Signer",
                                  "email": "signer@example.com", "completed": false}]},
         "signing_urls": [{"signer_id": "signer-id",
                           "url": "https://api.example/sign/document-id"}]}

    ``copy_receivers`` entries are objects, but the current OpenAPI does not
    define fields for those objects. Virtual/legacy items may return an empty
    or non-object ``display_settings`` value; collect items use the object shown.

    ``DigitalCertificate`` is a published assignment verification method, but
    the API prose points certificate signers to unlisted ``certificate/start``
    and ``certificate/complete`` operations. Their auth/body/response contract
    is not published, so this SDK does not guess those calls.
    """

    def list(
        self,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """``GET /assignments`` — list the account's assignments.

        The published contract documents ``page`` and ``per_page`` (sent as
        ``per-page``) and scopes results to *the authenticated credential's
        current account*. The SDK forwards the explicit or client-default
        account as an ``accountId`` context parameter and omits it for
        account-less token clients, but passing an ``account_id`` for a
        different workspace does not re-scope this endpoint — use a credential
        belonging to that workspace instead.
        Returns
        ``{"data": [...], "meta": {...}}`` when the API returns ``x-pagination-*``
        headers.

        Example response (``data`` envelope unwrapped)::

            {"data": [
                {"id": "103033c9...", "sender_email": "owner@example.com",
                 "method": "virtual", "expires_at": null,
                 "message": "Please sign this contract",
                 "signers": [
                    {"id": "19e6b92e...", "full_name": "John Doe",
                     "email": "john@example.com", "verification_method": "Email",
                     "notification_methods": ["Email"], "step": 1,
                     "notified": true, "completed": false,
                     "has_accepted_terms": false, "notification_history": []}
                 ]}
             ],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        query = clean_params(params if params is not None else {}, QUERY_PARAM_ALIASES)
        scoped_account_id = self._default_account_id if account_id is None else account_id
        if scoped_account_id is not None:
            if "accountId" in query:
                raise ValidationError("Pass account_id separately from params")
            query["accountId"] = self._path_id(scoped_account_id, "Account ID")
        return self._call_list(
            "Failed to list assignments",
            lambda: self._http.get("assignments", params=query),
        )

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

        A complete ``collect`` request places fields on document pages::

            {
              "method": "collect",
              "signers": [{"id": "signer-id", "verification_method": "Email",
                           "notification_methods": ["Email"], "step": 1}],
              "entries": [{
                "page_id": "page-id",
                "fields": [{
                  "signer_id": "signer-id", "field_id": "field-id",
                  "display_settings": {
                    "left": 69, "top": 282, "width": 421, "height": 45.86,
                    "fontSize": 18, "fontFamily": "Arial",
                    "backgroundColor": "#D5EBFF"
                  }
                }]
              }]
            }

        ``left``, ``top``, ``width``, ``height``, and ``fontSize`` are required
        150-DPI page-image pixel values; width/height/font size must be positive,
        coordinates non-negative, and the rectangle must stay within the page.
        ``fontFamily`` and ``backgroundColor`` are optional.

        Example response (``data`` envelope unwrapped)::

            {
              "resource": "assignment",
              "id": "assignment-id",
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
        doc_id = self._path_id(document_id, "Document ID")
        body = build_assignment_payload(payload)
        if not body.get("signers"):
            raise ValidationError(
                "At least one signer is required", {"signers": payload.get("signers")}
            )
        self._logger.info(
            "Creating assignment",
            {"document_id": doc_id, "signers": len(body.get("signers") or [])},
        )
        return self._call_dict(
            "Failed to create assignment",
            lambda: self._http.post(f"documents/{doc_id}/assignments", json=body),
        )

    def estimate_cost(
        self,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """``POST /documents/{document_id}/assignments/estimate-cost``.

        The published body accepts optional ``method``, ``entries``, and signer
        pricing descriptors containing only ``verification_method`` and
        ``notification_methods``. Legacy signer IDs are accepted as input but
        are omitted from the wire body because they are not part of the current
        estimate contract.

        Example request body (JSON)::

            {"method": "virtual",
             "signers": [{"verification_method": "Whatsapp",
                          "notification_methods": ["Whatsapp"]}]}

        Example response (``data`` envelope unwrapped)::

            {"documents": 1, "credits": 0.45, "needs_extra_document": false,
             "extra_document_cost": 0, "total_credits": 0.45,
             "breakdown": [{"code": "NotificationWhatsapp",
                            "name": "Whatsapp Notification", "cost": 0.45,
                            "quantity": 1, "unit_cost": 0.45}],
             "document_balance": 66, "credit_balance": 0,
             "has_sufficient_resources": true, "blocking_reason": null,
             "message": null}
        """
        doc_id = self._path_id(document_id, "Document ID")
        body = _build_estimate_payload(payload)
        return self._call_dict(
            "Failed to estimate assignment cost",
            lambda: self._http.post(
                f"documents/{doc_id}/assignments/estimate-cost",
                json=body,
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
        ``2030-08-03T21:00:00Z``) or ``None`` to clear the expiration. The key is
        always sent so the server can apply the change.

        Example request body (JSON)::

            {"expires_at": "2030-08-03T21:00:00Z"}   # or {"expires_at": null}

        Returns the complete assignment payload documented on
        :class:`AssignmentResource`, with ``expires_at`` updated.
        """
        doc_id = self._path_id(document_id, "Document ID")
        asg_id = self._path_id(assignment_id, "Assignment ID")
        validate_datetime(expires_at, "expires_at", allow_none=True)
        return self._call_dict(
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

        The unwrapped response uses the complete
        :class:`~assinafy.resources.documents.DocumentResource` payload, with
        its ``assignment`` and ``pages`` fields expanded for the signer view.
        ``has_accepted_terms`` must be boolean when provided. Digital-certificate
        signers must confirm their identity data and accept the terms before the
        certificate flow can begin.
        """
        access_code = self._require_id(signer_access_code, "Signer access code")
        if has_accepted_terms is not None and not isinstance(has_accepted_terms, bool):
            raise ValidationError("has_accepted_terms must be boolean")
        return self._call_dict(
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
        entries: builtins.list[dict[str, Any]],
        signer_access_code: str,
    ) -> dict[str, Any]:
        """``POST /documents/{document_id}/assignments/{assignment_id}``.

        Submits a signer's completed items. ``entries`` is sent as the raw JSON
        request body. Virtual assignments have no input fields and use ``[]``
        after :meth:`~assinafy.resources.signers.SignerResource.confirm_data`.
        Collect assignments use ``{itemId, fieldId, pageId, value}`` objects.

        Example request body (JSON array)::

            [{"itemId": "615605f8...", "fieldId": "61521202...",
              "pageId": "615213ed...", "value": "John Doe"}]

        The documented success payload is an empty object (``data: {}``).
        """
        doc_id = self._path_id(document_id, "Document ID")
        asg_id = self._path_id(assignment_id, "Assignment ID")
        access_code = self._require_id(signer_access_code, "Signer access code")
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict)
            or any(
                not isinstance(entry.get(field), str) or not entry[field]
                for field in ("itemId", "fieldId", "pageId")
            )
            or not isinstance(entry.get("value"), str)
            for entry in entries
        ):
            raise ValidationError("Invalid assignment entry list")
        return self._call_dict(
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

        OpenAPI returns ``data: []`` on success; the SDK maps that empty result
        to ``None``.
        """
        doc_id = self._path_id(document_id, "Document ID")
        asg_id = self._path_id(assignment_id, "Assignment ID")
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
    ) -> builtins.list[dict[str, Any]]:
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
        doc_id = self._path_id(document_id, "Document ID")
        asg_id = self._path_id(assignment_id, "Assignment ID")
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

        Resends a signer's signature-request notification and can send a real
        message. The notification channel is charged again; call
        :meth:`estimate_resend_cost` first when cost must be known.

        Example response (``data`` envelope unwrapped)::

            {"is_sent": true, "document_id": "1031ff86...",
             "signer_id": "1031ff86..."}
        """
        doc_id = self._path_id(document_id, "Document ID")
        asg_id = self._path_id(assignment_id, "Assignment ID")
        sid = self._path_id(signer_id, "Signer ID")
        return self._call_dict(
            "Failed to resend signer notification",
            lambda: self._http.put(f"documents/{doc_id}/assignments/{asg_id}/signers/{sid}/resend"),
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

            {"documents": 1, "credits": 0.45, "needs_extra_document": false,
             "extra_document_cost": 0, "total_credits": 0.45,
             "breakdown": [{"code": "NotificationWhatsapp",
                            "name": "Whatsapp Notification", "cost": 0.45,
                            "quantity": 1, "unit_cost": 0.45}],
             "document_balance": 66, "credit_balance": 0,
             "has_sufficient_resources": true, "blocking_reason": null,
             "message": null}
        """  # noqa: E501
        doc_id = self._path_id(document_id, "Document ID")
        asg_id = self._path_id(assignment_id, "Assignment ID")
        sid = self._path_id(signer_id, "Signer ID")
        return self._call_dict(
            "Failed to estimate resend cost",
            lambda: self._http.post(
                f"documents/{doc_id}/assignments/{asg_id}/signers/{sid}/estimate-resend-cost"
            ),
        )
