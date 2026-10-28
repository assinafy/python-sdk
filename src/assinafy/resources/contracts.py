from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from ..errors import ValidationError
from ..types import CONTRACT_RELATION_TYPES, CONTRACT_STATUSES
from ..utils import QUERY_PARAM_ALIASES, clean_params, validate_datetime
from .base import BaseResource

_TERM_FIELDS = {
    "status",
    "counterparty_name",
    "counterparty_taxpayer_id",
    "value",
    "currency",
    "start_date",
    "end_date",
    "auto_renew",
    "renewal_term_months",
    "notice_period_days",
    "owner_id",
    "metadata",
    "external_references",
    "parent_document_id",
    "relation_type",
    "updated_at",
}


class ContractResource(BaseResource):
    """Contract lifecycle tracking on existing workspace documents.

    Reads require ``documents:read`` for OAuth, writes ``documents:write`` and
    a plan with contract tracking. Tracking does not upload or sign a document.
    Lifecycle transitions, membership, CPF/CNPJ validity and amendment ordering
    are checked by the API. Its field errors remain in ``ApiError.response_data``.
    """

    def list(
        self, params: dict[str, Any] | None = None, account_id: str | None = None
    ) -> dict[str, Any]:
        """GET /v1/accounts/{accountId}/contracts — list tracked contracts.

        No request body. Query example::

            {"status": "active,expired", "counterparty": "Example Company",
             "search": "Services", "end_date_from": "2027-01-01",
             "end_date_to": "2027-12-31", "ending_within_days": 30,
             "external_system": "crm", "external_id": "contract-1",
             "sort": "-updated_at", "expand": "document", "page": 1, "per_page": 20}

        ``per_page`` becomes ``per-page``. Statuses are comma-separated, sort is
        ``end_date`` or ``updated_at`` with optional ``-``, and ``expand=document``
        includes the document. ``ending_within_days`` is 0–3650, inclusive, using
        Brasília calendar days. Pages contain at most 100 records.
        Filters combine; omit any unused filter.
        Default order is most recently updated first. Page until ``updated_at``
        predates the last sync to recover changes after a missed webhook.

        Response (pagination metadata comes from headers)::

            {"data": [{"resource": "document_contract", "document_id": "doc-1",
              "status": "active", "counterparty_name": "Example Company",
              "counterparty_taxpayer_id": null, "value": 1200.50, "currency": "BRL",
              "start_date": "2026-11-01", "end_date": "2027-10-31",
              "auto_renew": true, "renewal_term_months": 12, "notice_period_days": 30,
              "term": 1, "owner_id": null, "metadata": {"department": "sales"},
              "external_references": [{"system": "crm", "id": "contract-1"}],
              "created_at": "2026-10-28T12:00:00Z", "updated_at": "2026-10-28T12:00:00Z"}],
             "meta": {"current_page": 1, "per_page": 20, "total": 1, "last_page": 1}}
        """
        aid = self._account_id(account_id)
        query = clean_params({} if params is None else params, QUERY_PARAM_ALIASES)
        allowed = {
            "status",
            "counterparty",
            "search",
            "end_date_from",
            "end_date_to",
            "ending_within_days",
            "external_system",
            "external_id",
            "sort",
            "expand",
            "page",
            "per-page",
        }
        _check_fields(query, allowed)
        for key, value in query.items():
            if key in {"page", "per-page", "ending_within_days"}:
                _integer(
                    value,
                    key,
                    0 if key == "ending_within_days" else 1,
                    {"ending_within_days": 3650, "per-page": 100}.get(key),
                )
            elif not isinstance(value, str):
                raise ValidationError(f"{key} must be a string")
        if "status" in query and any(
            s not in CONTRACT_STATUSES for s in query["status"].split(",")
        ):
            raise ValidationError("Invalid contract status filter")
        for key in ("end_date_from", "end_date_to"):
            if key in query:
                _date(query[key], key, minimum_year=1)
        if "sort" in query and query["sort"] not in {
            "end_date",
            "-end_date",
            "updated_at",
            "-updated_at",
        }:
            raise ValidationError("sort must be end_date or updated_at, optionally prefixed with -")
        if "expand" in query and query["expand"] != "document":
            raise ValidationError("expand must be document")
        return self._call_list(
            "Failed to list contracts",
            lambda: self._http.get(f"accounts/{aid}/contracts", params=query),
        )

    def get(self, document_id: str, account_id: str | None = None) -> dict[str, Any]:
        """GET /v1/accounts/{accountId}/documents/{documentId}/contract — read terms.

        No request body or query. A missing contract raises ``ApiError`` (404).
        Response for a contract includes its applied then pending amendments::

            {"resource": "document_contract", "document_id": "doc-1", "status": "active",
             "counterparty_name": "Example Company", "counterparty_taxpayer_id": null,
             "value": 1200.50, "currency": "BRL", "start_date": "2026-11-01",
             "end_date": "2027-10-31", "auto_renew": true, "renewal_term_months": 12,
             "notice_period_days": 30, "term": 1, "owner_id": null, "metadata": null,
             "external_references": [], "amendments": [],
             "created_at": "2026-10-28T12:00:00Z", "updated_at": "2026-10-28T12:00:00Z"}

        Reading an amendment document returns its link instead::

            {"resource": "document_contract_amendment", "document_id": "amendment-1",
             "document_name": "Amendment.pdf", "parent_document_id": "doc-1",
             "relation_type": "amendment", "number": null, "status": "pending",
             "document_status": "pending_signature", "apply_error": null, "currency": "BRL",
             "terms": {"value": 1300}, "changes": {"value": {"from": 1200.50, "to": 1300}},
             "applied_at": null, "created_at": "2026-10-28T13:00:00Z",
             "updated_at": "2026-10-28T13:00:00Z"}

        An applied link has ``status=applied``, its sequence ``number`` and
        ``applied_at``. ``terms`` and ``changes`` can be null; ``apply_error``
        explains a pending signed instrument. Save the returned ``updated_at``
        for writes with optimistic concurrency control.
        """
        path = self._path(document_id, account_id)
        return self._call_dict("Failed to get contract", lambda: self._http.get(path))

    def update(
        self, document_id: str, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """PUT /v1/accounts/{accountId}/documents/{documentId}/contract — set terms.

        Creates terms or changes only keys sent. Unlike most SDK mappings,
        explicit ``None`` values are sent as JSON null: they clear a term,
        reset ``auto_renew`` to false, or reset ``currency`` to BRL while a value
        exists. ``status`` and ``relation_type`` cannot be null.
        ``external_references`` replaces the entire list; [] or null clears it.
        ``updated_at`` is an optional RFC 3339 precondition (null disables it);
        stale writes raise ``ApiError`` (409), without changing the contract.

        Request (all keys optional; at least one required)::

            {"status": "active", "counterparty_name": "Example Company",
             "counterparty_taxpayer_id": null, "value": 1200.50, "currency": "BRL",
             "start_date": "2026-11-01", "end_date": "2027-10-31", "auto_renew": true,
             "renewal_term_months": 12, "notice_period_days": 30, "owner_id": null,
             "metadata": {"department": "sales"},
             "external_references": [{"system": "crm", "id": "contract-1"}]}

        Values are finite, nonnegative and at most 9999999999999.99 with two
        decimal places. Currency is three letters. Dates use YYYY-MM-DD from
        year 1000; end is not before start. Renewal months are 1–600 and notice
        days 0–3650. Counterparty names have at most 255 characters; taxpayer
        IDs are valid CPF/CNPJ, formatted or not. Owner IDs name active members.
        Metadata has at most 50 keys (1–40 letters/digits/_.-), with plain text
        values up to 500 characters. External references have at most 20 items:
        system is 1–64 letters/digits/_.-, id is 1–255 characters without emoji
        or other four-byte characters. The API handles reference deduplication.

        Response::

            {"resource": "document_contract", "document_id": "doc-1", "status": "active",
             "counterparty_name": "Example Company", "counterparty_taxpayer_id": null,
             "value": 1200.50, "currency": "BRL", "start_date": "2026-11-01",
             "end_date": "2027-10-31", "auto_renew": true, "renewal_term_months": 12,
             "notice_period_days": 30, "term": 1, "owner_id": null,
             "metadata": {"department": "sales"},
             "external_references": [{"system": "crm", "id": "contract-1"}],
             "created_at": "2026-10-28T12:00:00Z", "updated_at": "2026-10-28T12:00:00Z"}

        To link a separate document as a signed instrument, send its ID as
        ``document_id`` and, for example::

            {"parent_document_id": "doc-1", "relation_type": "amendment", "value": 1300}

        ``relation_type`` is amendment, renewal or termination and is required
        on the first link. Renewal deltas take end_date/value, termination only
        end_date; amendment deltas take value/currency, dates, auto_renew,
        renewal_term_months, notice_period_days, counterparty fields and metadata.
        A later PUT merges a pending delta; null drops its key. A null
        parent_document_id unlinks it. The response is the amendment shape in
        :meth:`get`; terms apply only when certificated, in signing order.
        Applied links are read-only. The API checks state-dependent rules and
        existing parent terms without the SDK issuing an extra read.
        """
        path = self._path(document_id, account_id)
        body = _validate_payload(payload, _TERM_FIELDS)
        if not body:
            raise ValidationError("Contract terms require at least one field")
        return self._call_dict("Failed to update contract", lambda: self._http.put(path, json=body))

    def related(self, document_id: str, account_id: str | None = None) -> dict[str, Any]:
        """GET /v1/accounts/{accountId}/documents/{documentId}/contract/related.

        No body or query. Reads a family's root from any member document.
        Missing terms raise ``ApiError`` (404). Response::

            {"resource": "document_contract", "document_id": "doc-1", "status": "active",
             "counterparty_name": "Example Company", "counterparty_taxpayer_id": null,
             "value": 1200.50, "currency": "BRL", "start_date": "2026-11-01",
             "end_date": "2027-10-31", "auto_renew": false, "renewal_term_months": 12,
             "notice_period_days": 30, "term": 1, "owner_id": null, "metadata": null,
             "external_references": [], "amendments": [],
             "created_at": "2026-10-28T12:00:00Z", "updated_at": "2026-10-28T12:00:00Z"}

        ``amendments`` contains links with the complete shape shown in :meth:`get`,
        applied first by number, then pending instruments.
        """
        path = self._path(document_id, account_id)
        return self._call_dict(
            "Failed to get related contracts", lambda: self._http.get(f"{path}/related")
        )

    def renew(
        self, document_id: str, payload: dict[str, Any], account_id: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/accounts/{accountId}/documents/{documentId}/contract/renew.

        Start the next term; expired contracts reopen, terminated ones return 400.
        Send the current ``term`` or a new ``end_date`` after the current one.
        Absent, empty or null end_date advances by renewal_term_months (default
        12), until in the future, and requires term. Both guards prevent duplicate
        renewals; the SDK never retries automatically. Optional ``updated_at``
        adds a 409 precondition. Omitted value is unchanged; null clears it.

        Request by term: ``{"term": 1, "value": 1300}``. Explicit-date request::

            {"end_date": "2028-10-31", "value": 1300,
             "updated_at": "2026-10-28T12:00:00Z"}

        Response::

            {"resource": "document_contract", "document_id": "doc-1", "status": "active",
             "counterparty_name": "Example Company", "counterparty_taxpayer_id": null,
             "value": 1300, "currency": "BRL", "start_date": "2026-11-01",
             "end_date": "2028-10-31", "auto_renew": false, "renewal_term_months": 12,
             "notice_period_days": 30, "term": 2, "owner_id": null, "metadata": null,
             "external_references": [], "created_at": "2026-10-28T12:00:00Z",
             "updated_at": "2027-10-15T12:00:00Z"}
        """
        path = self._path(document_id, account_id)
        body = _validate_payload(payload, {"end_date", "value", "term", "updated_at"}, renewal=True)
        if not body.get("end_date") and "term" not in body:
            raise ValidationError("Renewal requires term or end_date")
        return self._call_dict(
            "Failed to renew contract", lambda: self._http.post(f"{path}/renew", json=body)
        )

    def terminate(
        self,
        document_id: str,
        payload: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/accounts/{accountId}/documents/{documentId}/contract/terminate.

        Close a contract and stop lifecycle alerts. Optional request::

            {"reason": "Replaced by a new agreement", "updated_at": "2026-10-28T12:00:00Z"}

        Reason is nullable text of at most 500 characters; the API strips HTML
        and records it in document_contract_terminated. A stale updated_at raises
        409; an already terminated contract raises 400. Response::

            {"resource": "document_contract", "document_id": "doc-1", "status": "terminated",
             "counterparty_name": "Example Company", "counterparty_taxpayer_id": null,
             "value": 1200.50, "currency": "BRL", "start_date": "2026-11-01",
             "end_date": "2027-10-31", "auto_renew": false, "renewal_term_months": 12,
             "notice_period_days": 30, "term": 1, "owner_id": null, "metadata": null,
             "external_references": [], "created_at": "2026-10-28T12:00:00Z",
             "updated_at": "2027-03-01T12:00:00Z"}
        """
        path = self._path(document_id, account_id)
        body = _validate_payload({} if payload is None else payload, {"reason", "updated_at"})
        return self._call_dict(
            "Failed to terminate contract", lambda: self._http.post(f"{path}/terminate", json=body)
        )

    def _path(self, document_id: str, account_id: str | None) -> str:
        aid = self._account_id(account_id)
        did = self._path_id(document_id, "Document ID")
        return f"accounts/{aid}/documents/{did}/contract"


def _check_fields(payload: dict[str, Any], allowed: set[str]) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("Contract parameters must be a mapping")
    if payload.keys() - allowed:
        raise ValidationError("Unknown contract fields")


def _integer(value: Any, name: str, minimum: int, maximum: int | None = None) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ValidationError(
            f"{name} must be an integer from {minimum}"
            + (f" to {maximum}" if maximum is not None else "")
        )


def _date(value: Any, name: str, *, minimum_year: int = 1000) -> None:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            if date.fromisoformat(value).year >= minimum_year:
                return
        except ValueError:
            pass
    raise ValidationError(f"{name} must be a valid YYYY-MM-DD date from year {minimum_year}")


def _text(value: Any, name: str, maximum: int | None = None) -> None:
    if not isinstance(value, str) or (maximum is not None and len(value) > maximum):
        raise ValidationError(
            f"{name} must be text"
            + (f" of at most {maximum} characters" if maximum is not None else "")
        )


def _validate_payload(
    payload: dict[str, Any], allowed: set[str], *, renewal: bool = False
) -> dict[str, Any]:
    _check_fields(payload, allowed)
    for key, value in payload.items():
        if key in {"status", "relation_type"}:
            choices = CONTRACT_STATUSES if key == "status" else CONTRACT_RELATION_TYPES
            if not isinstance(value, str) or value not in choices:
                raise ValidationError(f"Invalid contract {key}")
        elif key == "term":
            _integer(value, key, 1)
        elif value is None:
            continue
        elif key in {"start_date", "end_date"}:
            if not (renewal and key == "end_date" and value == ""):
                _date(value, key)
        elif key == "updated_at":
            validate_datetime(value, key)
        elif key == "value":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError("value must be a number")
            amount = Decimal(value) if isinstance(value, int) else Decimal(str(value))
            if not amount.is_finite() or not 0 <= amount <= Decimal("9999999999999.99"):
                raise ValidationError("value must be between 0 and 9999999999999.99")
            exponent = amount.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -2:
                raise ValidationError("value must have at most two decimal places")
        elif key == "currency":
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value):
                raise ValidationError("currency must contain three letters")
        elif key == "auto_renew":
            if not isinstance(value, bool):
                raise ValidationError("auto_renew must be a boolean")
        elif key in {"renewal_term_months", "notice_period_days"}:
            _integer(
                value,
                key,
                1 if key == "renewal_term_months" else 0,
                600 if key == "renewal_term_months" else 3650,
            )
        elif key == "metadata":
            if not isinstance(value, dict) or len(value) > 50:
                raise ValidationError("metadata must be an object with at most 50 keys")
            if value and list(value) == [str(index) for index in range(len(value))]:
                raise ValidationError("metadata keys must not form a list")
            for field, text in value.items():
                if not isinstance(field, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", field):
                    raise ValidationError("Invalid metadata key")
                _text(text, "metadata value", 500)
                if re.search(r"<[^>]+>", text):
                    raise ValidationError("metadata values must be plain text")
        elif key == "external_references":
            if not isinstance(value, list) or len(value) > 20:
                raise ValidationError("external_references must be a list of at most 20 items")
            for ref in value:
                _check_fields(ref, {"system", "id"})
                system, ref_id = ref.get("system"), ref.get("id")
                if not isinstance(system, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", system):
                    raise ValidationError("Invalid external reference system")
                _text(ref_id, "external reference id", 255)
                if not ref_id.strip() or any(ord(char) > 0xFFFF for char in ref_id):
                    raise ValidationError("Invalid external reference id")
        else:
            maximum = {"counterparty_name": 255, "counterparty_taxpayer_id": 20, "reason": 500}.get(
                key
            )
            _text(value, key, maximum)
            if key in {"owner_id", "parent_document_id"} and not value.strip():
                raise ValidationError(f"{key} must be non-empty")
            if key == "counterparty_name" and re.search(r"<[^>]+>", value):
                raise ValidationError("counterparty_name must be plain text")
    start, end = payload.get("start_date"), payload.get("end_date")
    if start and end and end < start:
        raise ValidationError("end_date must not be before start_date")
    return dict(payload)
