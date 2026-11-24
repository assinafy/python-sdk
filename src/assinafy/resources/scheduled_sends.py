from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..utils import QUERY_PARAM_ALIASES, clean_params, validate_expiration
from .assignments import build_assignment_payload
from .base import BaseResource
from .envelopes import build_envelope_payload


class ScheduledSendResource(BaseResource):
    """Schedule assignments and envelopes; available on staging before production.

    Every operation needs documents:write for OAuth, including listing. Objects
    returned by create_assignment/create_envelope/cancel/send have this shape::

        {"resource": "scheduled_send", "id": "send-id", "type": "assignment",
         "document_ids": ["document-id"], "status": "pending",
         "send_at": "2026-12-01T12:00:00Z", "assignment_id": null,
         "envelope_id": null, "failure_reason": null,
         "created_at": "2026-11-24T12:00:00Z", "processed_at": null}

    type is assignment/envelope. status is pending/processing/sent/cancelled/failed.
    Sent results contain assignment_id or envelope_id; failure_reason is nullable
    Portuguese text. processed_at is nullable ISO 8601. Deleted documents are
    omitted from document_ids; deleting the envelope clears envelope_id.

    The server requires send_at one hour to 90 days ahead, and each expiration
    at least two hours after it. It checks the queue every five minutes and uses
    the scheduling member's permissions and the plan/balance at execution time.
    Scheduling sends/charges nothing and does not reserve documents or credits.
    A document may belong to only one pending/processing send. Background failure
    emails that member, or active owners if the member left. No automatic retries.
    """

    def create_assignment(self, document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /documents/{documentId}/scheduled-sends.

        JSON: the complete assignments.create() body plus send_at::

            {"send_at": "2026-12-01T12:00:00Z", "method": "virtual",
             "signers": [{"id": "signer-id", "sign_as": "Witness"}],
             "message": "Please sign", "expires_at": null,
             "copy_receivers": [], "max_total_credits": 0}

        Collect uses entries as documented by assignments.create(). send_at is
        an ISO datetime (no offset means UTC) or integer Unix seconds. Returns
        the scheduled-send object documented on this class. No Idempotency-Key.
        """
        doc_id = self._path_id(document_id, "Document ID")
        send_at, request = _split_payload(payload)
        body = {**build_assignment_payload(request), "send_at": send_at}
        return self._call_dict(
            "Failed to schedule assignment",
            lambda: self._http.post(f"documents/{doc_id}/scheduled-sends", json=body),
        )

    def create_envelope(
        self, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """POST /accounts/{accountId}/scheduled-sends.

        JSON: the complete envelopes.create() body plus send_at::

            {"send_at": "2026-12-01T12:00:00Z", "name": "Agreement",
             "signers": [{"id": "signer-id"}],
             "documents": [{"id": "document-id", "signer_ids": ["signer-id"]}]}

        Optional message, max_total_credits, per-document expiration, copies and
        collect entries follow envelopes.create(). Returns the scheduled-send
        object documented on this class with type=envelope. Requires Envelopes.
        No Idempotency-Key is read: every call schedules a separate send.
        """
        acc_id = self._account_id(account_id)
        send_at, request = _split_payload(payload)
        body = {**build_envelope_payload(request), "send_at": send_at}
        return self._call_dict(
            "Failed to schedule envelope",
            lambda: self._http.post(f"accounts/{acc_id}/scheduled-sends", json=body),
        )

    def list(
        self, params: dict[str, Any] | None = None, account_id: str | None = None
    ) -> dict[str, Any]:
        """GET /accounts/{accountId}/scheduled-sends; no body.

        Query: page, per_page (wire: per-page, default 20), document_id. Returns
        {"data": [scheduled-send objects], "meta": {"current_page": 1,
        "per_page": 20, "total": 1, "last_page": 1}} using pagination headers.
        Includes every status, newest first. OAuth needs documents:write.
        """
        acc_id = self._account_id(account_id)
        query = clean_params({} if params is None else params, QUERY_PARAM_ALIASES)
        if query.keys() - {"page", "per-page", "document_id"}:
            raise ValidationError("Unknown scheduled-send query fields")
        if "document_id" in query:
            self._require_id(query["document_id"], "Document ID")
        return self._call_list(
            "Failed to list scheduled sends",
            lambda: self._http.get(f"accounts/{acc_id}/scheduled-sends", params=query),
        )

    def cancel(self, scheduled_send_id: str, account_id: str | None = None) -> dict[str, Any]:
        """PUT /accounts/{accountId}/scheduled-sends/{scheduledSendId}/cancel; no body.

        Returns the class's scheduled-send object with status=cancelled and a
        processed_at timestamp. Only pending sends can be cancelled; others
        return 409. Sends and charges nothing; 404 for a missing send/workspace.
        """
        path = self._path(scheduled_send_id, account_id)
        return self._call_dict(
            "Failed to cancel scheduled send", lambda: self._http.put(f"{path}/cancel")
        )

    def send(self, scheduled_send_id: str, account_id: str | None = None) -> dict[str, Any]:
        """PUT /accounts/{accountId}/scheduled-sends/{scheduledSendId}/send; no body.

        Sends a pending request now, inviting recipients and charging as normal
        creation does. Returns the class's scheduled-send object with status=sent
        and assignment_id/envelope_id. Other statuses return 409. A creation
        refusal leaves the send pending, without email or charges; cancel it to
        prevent its later execution. A lost response is ambiguous; list before
        deciding what to do. This method never retries automatically.
        """
        path = self._path(scheduled_send_id, account_id)
        return self._call_dict(
            "Failed to execute scheduled send", lambda: self._http.put(f"{path}/send")
        )

    def _path(self, scheduled_send_id: str, account_id: str | None) -> str:
        acc_id = self._account_id(account_id)
        send_id = self._path_id(scheduled_send_id, "Scheduled send ID")
        return f"accounts/{acc_id}/scheduled-sends/{send_id}"


def _split_payload(payload: Any) -> tuple[str | int, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValidationError("Scheduled-send payload must be a mapping")
    send_at = payload.get("send_at")
    if isinstance(send_at, bool) or not isinstance(send_at, (str, int)) or not send_at:
        raise ValidationError("send_at must be an ISO datetime or integer Unix seconds")
    if isinstance(send_at, int) and send_at < 0:
        raise ValidationError("send_at must be positive Unix seconds")
    if isinstance(send_at, str) and "T" not in send_at and "t" not in send_at:
        raise ValidationError("send_at must be an ISO datetime or integer Unix seconds")
    validate_expiration(send_at, "send_at")
    return send_at, {key: value for key, value in payload.items() if key != "send_at"}
