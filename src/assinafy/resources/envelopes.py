from __future__ import annotations

import builtins
from typing import Any

from ..errors import ValidationError
from ..types import DOCUMENT_ARTIFACT_NAMES, DocumentArtifactName
from ..utils import QUERY_PARAM_ALIASES, clean_params, idempotency_headers, validate_credit_ceiling
from .assignments import build_assignment_payload
from .base import BaseResource


def _ids(value: Any, name: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError(f"{name} must be a nonempty list of unique IDs")
    return value


def _editable(payload: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.keys() - allowed:
        raise ValidationError("Invalid envelope fields")
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 255 or "<" in name:
            raise ValidationError("name must contain 1–255 characters without <")
    if payload.get("message") is not None and not isinstance(payload["message"], str):
        raise ValidationError("message must be text or null")
    if "max_total_credits" in payload and payload["max_total_credits"] is not None:
        validate_credit_ceiling(payload["max_total_credits"])
    return dict(payload)


def _document(payload: Any, signers: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.keys() - {
        "id",
        "method",
        "entries",
        "signer_ids",
        "expires_at",
        "copy_receiver_ids",
        "max_total_credits",
    }:
        raise ValidationError("Invalid envelope document fields")
    if not isinstance(payload.get("id"), str) or not payload["id"].strip():
        raise ValidationError("Envelope document id is required")
    ids = _ids(payload.get("signer_ids"), "signer_ids")
    if signers is not None and any(signer_id not in signers for signer_id in ids):
        raise ValidationError("Every document signer must belong to the envelope")
    assignment = build_assignment_payload(
        {
            **{
                key: value
                for key, value in payload.items()
                if key in {"method", "entries", "expires_at", "max_total_credits"}
            },
            "signers": [
                signers[signer_id] if signers is not None else {"id": signer_id}
                for signer_id in ids
            ],
            "copy_receivers": payload.get("copy_receiver_ids"),
        }
    )
    if assignment.get("method") == "collect" and any(
        not entry["fields"] for entry in assignment["entries"]
    ):
        raise ValidationError("Every collect page must have at least one field")
    return clean_params(dict(payload))


def _create_payload(payload: Any) -> dict[str, Any]:
    body = _editable(payload, {"name", "message", "signers", "documents", "max_total_credits"})
    if "name" not in body:
        raise ValidationError("Envelope name is required")
    for name, items in (("signers", body.get("signers")), ("documents", body.get("documents"))):
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            raise ValidationError(f"{name} must contain 1–20 items")
    signers = body["signers"]
    documents = body["documents"]
    by_id: dict[str, dict[str, Any]] = {}
    for signer in signers:
        if not isinstance(signer, dict) or signer.keys() - {
            "id",
            "verification_method",
            "notification_methods",
            "embedded",
        }:
            raise ValidationError("Invalid envelope signer fields; steps are not supported")
        normalized = build_assignment_payload({"signers": [signer]})["signers"][0]
        signer_id = normalized["id"]
        if not signer_id.strip() or signer_id in by_id:
            raise ValidationError("Envelope signer IDs must be nonempty and unique")
        by_id[signer_id] = normalized
    body["signers"] = list(by_id.values())
    body["documents"] = []
    for document in documents:
        if isinstance(document, dict) and "max_total_credits" in document:
            raise ValidationError("Set max_total_credits on the envelope, not its documents")
        body["documents"].append(_document(document, by_id))
    _ids([document["id"] for document in body["documents"]], "document IDs")
    used = {signer_id for document in body["documents"] for signer_id in document["signer_ids"]}
    if used != by_id.keys():
        raise ValidationError("Every envelope signer must be on at least one document")
    fields = sum(
        sum(len(entry["fields"]) for entry in document["entries"])
        if document.get("method") == "collect"
        else len(document["signer_ids"])
        for document in body["documents"]
    )
    copies = sum(len(document.get("copy_receiver_ids", [])) for document in body["documents"])
    if fields > 2000 or copies > 100:
        raise ValidationError("An envelope allows at most 2000 fields and 100 copy receivers")
    return clean_params(body)


class EnvelopeResource(BaseResource):
    """Send documents together while retaining each document's assignment and artifacts.

    Object responses from create/get/update/add_document/remove_document have::

        {"resource": "envelope", "id": "envelope-id", "name": "Agreement",
         "message": null, "created_at": "2026-11-11T12:00:00Z",
         "documents": [{"id": "document-id", "position": 1, "name": "agreement.pdf",
             "status": "pending_signature", "artifacts": {"original": "https://..."},
             "signers": [{"id": "signer-id", "full_name": "Example Signer",
                 "email": "signer@example.com", "whatsapp_phone_number": null,
                 "completed": false, "signed_at": null}]}],
         "counts": {"pending_signature": 1},
         "signing_urls": [{"signer_id": "signer-id", "url": "https://...",
             "embedded": false}]}

    ``counts`` is null when no documents remain; the envelope has no status of
    its own. Embedded signers have a null signing URL. URLs are credentials:
    never log them. Lists omit ``resource`` and expose only thumbnail artifacts.
    Reads need documents:read, writes documents:write; create/estimate/add also
    require the Envelopes plan feature. HTTP 200 creation does not guarantee
    delivery: inspect each assignment's notification_history.
    """

    def _collection_path(self, account_id: str | None = None) -> str:
        return f"accounts/{self._account_id(account_id)}/envelopes"

    def _path(self, envelope_id: str, account_id: str | None = None) -> str:
        envelope_id = self._path_id(envelope_id, "envelope_id")
        return f"{self._collection_path(account_id)}/{envelope_id}"

    def list(
        self, params: dict[str, Any] | None = None, account_id: str | None = None
    ) -> dict[str, Any]:
        """GET /accounts/{accountId}/envelopes; no body.

        Query: page, per_page (default 20, server caps at 50), search (name),
        status (open/closed). Returns {data: [envelope objects], meta: pagination}.
        Open means at least one document remains open; newest envelopes first.
        """
        query = clean_params(params if params is not None else {}, QUERY_PARAM_ALIASES)
        if query.get("status") is not None and query["status"] not in ("open", "closed"):
            raise ValidationError("status must be open or closed")
        if "search" in query and not isinstance(query["search"], str):
            raise ValidationError("search must be text")
        path = self._collection_path(account_id)
        return self._call_list("envelopes.list", lambda: self._http.get(path, params=query))

    def get(self, envelope_id: str, account_id: str | None = None) -> dict[str, Any]:
        """GET /accounts/{accountId}/envelopes/{envelopeId}; no body.

        Returns the envelope object documented on this class; 404 if absent.
        """
        path = self._path(envelope_id, account_id)
        return self._call_dict("envelopes.get", lambda: self._http.get(path))

    def create(
        self,
        payload: dict[str, Any],
        account_id: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST /accounts/{accountId}/envelopes; returns the envelope object.

        JSON: {name: str (1–255, no '<'), message?: str|null,
        max_total_credits?: nonnegative number or numeric text,
        signers: [{id, verification_method?, notification_methods?, embedded?}],
        documents: [{id, signer_ids: [id], method?: virtual|collect, entries?:
        [{page_id, fields: [{signer_id, field_id, display_settings: {left, top,
        width, height, fontSize, fontFamily?, backgroundColor?}}]}],
        expires_at?: ISO date/datetime|Unix seconds|null, copy_receiver_ids?: [id]}]}.

        Up to 20 unique signers and documents; every signer must appear on a
        document. No signing steps. Certificate signers require virtual and are
        alone on each document. Collect fields must belong exactly to its signers.
        All documents must be metadata_ready and unassigned; the server checks
        membership, state, contact details, plan and balance. Envelope limits:
        2000 fields and 100 copy receivers. Notification/biometric charges count
        once per signer; certificate charges count on every document signed.

        Optional Idempotency-Key header identifies one creation permanently in
        this workspace; reuse returns the first envelope regardless of body.
        409 IdempotencyKeyInUse means creation is in progress; CreditCeilingExceeded
        means the total exceeds the ceiling. The SDK never retries automatically.
        """
        path = self._collection_path(account_id)
        body = _create_payload(payload)
        headers = idempotency_headers(idempotency_key)
        return self._call_dict(
            "envelopes.create", lambda: self._http.post(path, json=body, headers=headers)
        )

    def estimate_cost(
        self, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """POST /accounts/{accountId}/envelopes/estimate-cost.

        JSON: the complete create() body; max_total_credits is ignored. No
        documents, invitations or charges are created. Returns {documents,
        credits, needs_extra_document, extra_document_cost, total_credits,
        breakdown: [{code, name, quantity, unit_cost, cost}], document_balance,
        credit_balance, has_sufficient_resources, blocking_reason, message}.
        Balances/reason/message can be null; reason is PendingPayment,
        InsufficientDocuments or InsufficientCredits. Contact/page existence
        and race-dependent state must still pass at creation.
        """
        path = f"{self._collection_path(account_id)}/estimate-cost"
        if isinstance(payload, dict):
            payload = {k: v for k, v in payload.items() if k != "max_total_credits"}
        body = _create_payload(payload)
        return self._call_dict("envelopes.estimate_cost", lambda: self._http.post(path, json=body))

    def update(
        self, envelope_id: str, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """PATCH /accounts/{accountId}/envelopes/{envelopeId}.

        JSON: {name?: str (1–255, no '<'), message?: str|null,
        document_ids?: [every current document ID once in its new order]}.
        Omitted values stay unchanged; message=null clears it. Returns the
        envelope object. Sends no notices; later notices use the new values.
        Works on closed envelopes too. Invalid changes are rejected atomically.
        """
        path = self._path(envelope_id, account_id)
        body = _editable(payload, {"name", "message", "document_ids"})
        if "document_ids" in body:
            _ids(body["document_ids"], "document_ids")
        return self._call_dict("envelopes.update", lambda: self._http.patch(path, json=body))

    def delete(self, envelope_id: str, account_id: str | None = None) -> None:
        """DELETE /accounts/{accountId}/envelopes/{envelopeId}; no body; returns None.

        Every document must be closed (409 EnvelopeOpen otherwise). Documents
        and certificates remain; the envelope and its idempotency lookup disappear.
        """
        path = self._path(envelope_id, account_id)
        self._call_void("envelopes.delete", lambda: self._http.delete(path))

    def cancel(self, envelope_id: str, account_id: str | None = None) -> builtins.list[Any]:
        """PUT /accounts/{accountId}/envelopes/{envelopeId}/cancel; no body.

        Returns [{id, status, cancelled: bool}] in document order. Cancels open
        documents and notifies owners/signers/copy receivers. Closed, fully signed
        and certificating documents stay unchanged. Repeating cancels nothing new.
        """
        path = f"{self._path(envelope_id, account_id)}/cancel"
        return self._call_plain_list("envelopes.cancel", lambda: self._http.put(path))

    def resend_notification(
        self, envelope_id: str, signer_id: str, account_id: str | None = None
    ) -> dict[str, Any]:
        """PUT /accounts/{accountId}/envelopes/{envelopeId}/signers/{signerId}/resend.

        No body. Returns {is_sent: bool, envelope_id, signer_id}. Sends one reminder
        for the envelope, charging paid channels once per sent message. 400 if the
        signer has nothing left to sign/insufficient credits, 409 EnvelopeClosed
        if all documents closed, 404 if signer/envelope absent.
        """
        signer_id = self._path_id(signer_id, "signer_id")
        path = f"{self._path(envelope_id, account_id)}/signers/{signer_id}/resend"
        return self._call_dict("envelopes.resend_notification", lambda: self._http.put(path))

    def add_document(
        self, envelope_id: str, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """POST /accounts/{accountId}/envelopes/{envelopeId}/documents.

        JSON: one documents[] entry from create(), optionally max_total_credits
        for this document alone. Returns the updated envelope. Only existing
        envelope signers can be named. Sends them a new envelope invitation;
        charges only digital-certificate signatures. The server checks the
        envelope-wide limits and existing signers' certificate constraints.
        409 EnvelopeClosed or CreditCeilingExceeded leaves it unchanged.
        """
        path = f"{self._path(envelope_id, account_id)}/documents"
        body = _document(payload)
        return self._call_dict("envelopes.add_document", lambda: self._http.post(path, json=body))

    def remove_document(
        self, envelope_id: str, document_id: str, account_id: str | None = None
    ) -> dict[str, Any]:
        """DELETE /accounts/{accountId}/envelopes/{envelopeId}/documents/{documentId}.

        No body. Cancels and removes an open document, notifying its recipients;
        returns the envelope object. Its original invitation still reaches the
        other documents. 409 DocumentClosed if it can no longer be cancelled;
        404 if absent/already removed. Other documents continue unchanged.
        """
        document_id = self._path_id(document_id, "document_id")
        path = f"{self._path(envelope_id, account_id)}/documents/{document_id}"
        return self._call_dict("envelopes.remove_document", lambda: self._http.delete(path))

    def activities(
        self,
        envelope_id: str,
        params: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /accounts/{accountId}/envelopes/{envelopeId}/activities; no body.

        Query: page, per_page (20 default, at most 50), sort (-id default or id).
        Returns {data: [document activity plus document_id/document_name], meta}.
        Includes removed documents, excluding deleted ones. Activities carry id,
        event, message, payload (object/array/null), origin ({ip, user-agent} or
        null), created_at and document identifiers.
        """
        path = f"{self._path(envelope_id, account_id)}/activities"
        query = clean_params(params if params is not None else {}, QUERY_PARAM_ALIASES)
        return self._call_list("envelopes.activities", lambda: self._http.get(path, params=query))

    def download(
        self,
        envelope_id: str,
        artifact_name: DocumentArtifactName = "certificated",
        account_id: str | None = None,
    ) -> bytes:
        """GET /accounts/{accountId}/envelopes/{envelopeId}/download/{artifactName}.

        No body. Returns ZIP bytes for original, certificated, certificate-page,
        pades or bundle. Only documents with the requested artifact are included,
        in envelope order, named '1 - document.pdf' (bundle: a folder per document).
        404 when no document has the artifact; pades includes certificate signatures.
        """
        if not isinstance(artifact_name, str) or artifact_name not in DOCUMENT_ARTIFACT_NAMES:
            raise ValidationError("Invalid envelope artifact_name")
        path = f"{self._path(envelope_id, account_id)}/download/{artifact_name}"
        return self._call_binary("envelopes.download", lambda: self._http.get(path))
