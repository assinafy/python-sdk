"""Live API smoke test for the Assinafy Python SDK.

Run with:
    ASSINAFY_API_KEY=... ASSINAFY_ACCOUNT_ID=... .venv/bin/python scripts/live_smoke.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Any, Callable

from assinafy import ApiError, AssinafyClient, AssinafyError


def step(label: str, fn: Callable[[], Any]) -> Any:
    print(f"\n=== {label} ===")
    try:
        result = fn()
    except AssinafyError as err:
        status = getattr(err, "status_code", None)
        print(f"  FAIL [{type(err).__name__}] status={status} message={err}")
        if isinstance(err, ApiError):
            print(f"  response_data={err.response_data!r}")
        return None
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return None
    print(f"  OK -> {_preview(result)}")
    return result


def _preview(value: Any, max_len: int = 240) -> str:
    text = repr(value)
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text


def _make_minimal_pdf() -> bytes:
    # Minimal valid one-page PDF (89 bytes-ish) generated programmatically.
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type/Catalog/Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type/Pages/Count 1/Kids[3 0 R]>> endobj\n"
        b"3 0 obj <</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<<>>>> endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000054 00000 n \n"
        b"0000000101 00000 n \n"
        b"trailer <</Size 4/Root 1 0 R>>\n"
        b"startxref\n171\n%%EOF\n"
    )
    return pdf


def main() -> int:
    api_key = os.environ.get("ASSINAFY_API_KEY")
    account_id = os.environ.get("ASSINAFY_ACCOUNT_ID")
    if not api_key or not account_id:
        print("Missing ASSINAFY_API_KEY / ASSINAFY_ACCOUNT_ID env vars", file=sys.stderr)
        return 2

    client = AssinafyClient(api_key=api_key, account_id=account_id)

    print(f"Base URL: {client.get_http_client().base_url}")

    # 1. Read-only endpoints first
    step("documents.statuses()", lambda: client.documents.statuses())
    step("fields.list_types()", lambda: client.fields.list_types())
    step("webhooks.list_event_types()", lambda: client.webhooks.list_event_types())

    step("documents.list(per_page=5)", lambda: client.documents.list({"per_page": 5}))
    step("signers.list(per_page=5)", lambda: client.signers.list({"per_page": 5}))
    step("templates.list(per_page=5)", lambda: client.templates.list({"per_page": 5}))
    step("fields.list()", lambda: client.fields.list())
    step("webhooks.get()", lambda: client.webhooks.get())
    step("webhooks.list_dispatches(per_page=5)", lambda: client.webhooks.list_dispatches({"per_page": 5}))

    step("authentication.get_api_key()", lambda: client.authentication.get_api_key())

    # 2. Write flow: signer create, then delete
    timestamp = int(time.time())
    signer_email = f"sdk-smoke+{timestamp}@assinafy.dev"
    signer = step(
        "signers.create() new signer",
        lambda: client.signers.create(
            {"full_name": "SDK Smoke Test", "email": signer_email}
        ),
    )
    signer_id = signer["id"] if isinstance(signer, dict) else None

    if signer_id:
        step(
            "signers.get()",
            lambda: client.signers.get(signer_id),
        )
        step(
            "signers.update()",
            lambda: client.signers.update(signer_id, {"full_name": "SDK Smoke Test 2"}),
        )
        step(
            "signers.find_by_email()",
            lambda: client.signers.find_by_email(signer_email),
        )

    # 3. Document upload + estimate-cost + cleanup
    pdf_bytes = _make_minimal_pdf()
    doc = step(
        "documents.upload()",
        lambda: client.documents.upload(
            {"buffer": pdf_bytes, "file_name": "sdk-smoke.pdf"}
        ),
    )
    doc_id = doc["id"] if isinstance(doc, dict) else None

    if doc_id:
        step("documents.get()", lambda: client.documents.get(doc_id))
        step("documents.activities()", lambda: client.documents.activities(doc_id))

        if signer_id:
            step(
                "assignments.estimate_cost()",
                lambda: client.assignments.estimate_cost(
                    doc_id,
                    {"method": "virtual", "signers": [{"id": signer_id}]},
                ),
            )

        step(
            "documents.wait_until_ready()",
            lambda: client.documents.wait_until_ready(doc_id, timeout=60),
        )
        step("documents.delete()", lambda: client.documents.delete(doc_id))

    if signer_id:
        step("signers.delete()", lambda: client.signers.delete(signer_id))

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
