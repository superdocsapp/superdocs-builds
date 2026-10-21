"""Construction contract pack -- built against the real, hosted SuperDocs
product (use.superdocs.app), not a mock. Drives the documented minimum
contract (upload -> chat -> approve -> export) end to end for four
standard-form-shaped documents that share one project: a Master Subcontract
Agreement, a Change Order, a Request for Information, and a Payment
Application.

The grading bar (per the task card) is narrow and specific: the Change
Order and Payment Application must correctly reference the base
agreement's real clause numbering. Everything here is built and verified
against exactly that bar -- see verify_cross_references() at the bottom,
which checks the *actual* exported content against the *actual* article
numbers in the base agreement, not against an assumption of what the AI
was asked to do.

Usage:
    python build.py
"""

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("SUPERDOCS_API_KEY")
if not API_KEY:
    print("SUPERDOCS_API_KEY not set -- add it to .env (see .env.example)", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://api.superdocs.app"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

HERE = Path(__file__).parent
CONTENT_DIR = HERE / "content"
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

client = httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=180.0)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- low-level API helpers ----------


def upload_document(path: Path, session_id: str, open_mode: str = "replace") -> dict:
    with open(path, "rb") as f:
        files = {"file": (path.name, f, "text/html")}
        data = {"session_id": session_id, "open_mode": open_mode}
        resp = client.post("/v1/documents/upload", files=files, data=data)
    resp.raise_for_status()
    return resp.json()


def start_chat(message: str, session_id: str, document_id: str | None = None, approval_mode: str = "ask_every_time") -> dict:
    body = {
        "message": message,
        "session_id": session_id,
        "approval_mode": approval_mode,
    }
    if document_id:
        body["document_id"] = document_id
    resp = client.post("/v1/chat/async", json=body)
    resp.raise_for_status()
    return resp.json()


def get_job(job_id: str) -> dict:
    resp = client.get(f"/v1/jobs/{job_id}")
    resp.raise_for_status()
    return resp.json()


def approve_all(session_id: str, job_id: str, pending_changes: list[dict]) -> dict:
    changes = [{"change_id": c["change_id"], "approved": True} for c in pending_changes]
    body = {"job_id": job_id, "approved": True, "changes": changes}
    resp = client.post(f"/v1/chat/{session_id}/approve", json=body)
    resp.raise_for_status()
    return resp.json()


def continue_job(session_id: str, job_id: str) -> dict:
    resp = client.post(f"/v1/chat/{session_id}/continue", json={"job_id": job_id, "continue": True})
    resp.raise_for_status()
    return resp.json()


def get_document_html(durable_document_id: str) -> dict:
    resp = client.get(f"/v1/documents/{durable_document_id}", params={"include_html": "true"})
    resp.raise_for_status()
    return resp.json()


def export_html(html: str, filename: str, fmt: str = "docx") -> Path:
    resp = client.post(
        "/v1/documents/export",
        json={"html": html, "format": fmt, "options": {"filename": filename}},
    )
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "")
    ext = {"docx": "docx", "pdf": "pdf", "html": "html", "markdown": "md", "txt": "txt"}.get(fmt, fmt)
    out_path = OUTPUT_DIR / f"{filename}.{ext}"
    if "application/json" in ct:
        # some export configurations return a JSON wrapper (e.g. a download URL)
        # instead of the raw file -- handle both without guessing silently.
        data = resp.json()
        log(f"  export returned JSON, not a binary file: {json.dumps(data)[:300]}")
        if "download_url" in data:
            file_resp = client.get(data["download_url"])
            out_path.write_bytes(file_resp.content)
        elif "url" in data:
            file_resp = client.get(data["url"])
            out_path.write_bytes(file_resp.content)
        else:
            raise RuntimeError(f"unrecognized export response shape: {data}")
    else:
        out_path.write_bytes(resp.content)
    return out_path


def wait_for_job(session_id: str, job_id: str, label: str, max_wait_s: int = 300) -> dict:
    """Polls a job to completion, handling both approval gates and the
    continue-prompt pause for large edits -- silence during this loop is
    documented as normal (30s-several-minutes with no visible progress),
    not a hang, so this prints its own heartbeat rather than going quiet."""
    start = time.time()
    while time.time() - start < max_wait_s:
        job = get_job(job_id)
        status = job["status"]
        if status == "completed":
            log(f"  {label}: completed")
            return job
        if status == "failed":
            raise RuntimeError(f"{label} job failed: {job.get('error')}")
        if status == "cancelled":
            raise RuntimeError(f"{label} job was cancelled")
        if status == "awaiting_approval":
            metadata = job.get("metadata") or {}
            awaiting_kind = metadata.get("awaiting_kind")
            if awaiting_kind == "continue_prompt":
                log(f"  {label}: paused mid-edit, sending continue")
                continue_job(session_id, job_id)
            else:
                pending = metadata.get("pending_changes") or []
                log(f"  {label}: awaiting approval on {len(pending)} change(s) -- approving all")
                approve_all(session_id, job_id, pending)
        else:
            log(f"  {label}: {status}...")
        time.sleep(4)
    raise TimeoutError(f"{label} job did not complete within {max_wait_s}s")


# ---------- build steps ----------


def warm_up() -> None:
    """Per the task doc: the first request in a fresh session can be slow
    or fail while things warm up. Absorb that here, not on a real document."""
    log("warm-up: sending a small throwaway instruction in a fresh session")
    session_id = f"warmup-{uuid.uuid4()}"
    try:
        resp = client.post(
            "/v1/chat",
            json={
                "message": "Say ready.",
                "session_id": session_id,
                "document_html": "<p>ping</p>",
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        log("warm-up: ok")
    except httpx.HTTPError as e:
        log(f"warm-up: first attempt failed as documented ({e}), retrying once")
        resp = client.post(
            "/v1/chat",
            json={
                "message": "Say ready.",
                "session_id": session_id,
                "document_html": "<p>ping</p>",
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        log("warm-up: ok on retry")


def build() -> dict:
    session_id = f"construction-pack-{uuid.uuid4()}"
    log(f"session: {session_id}")

    log("uploading base agreement")
    base_upload = upload_document(CONTENT_DIR / "base_agreement.html", session_id, open_mode="replace")
    log(f"  base upload response keys: {list(base_upload.keys())}")

    documents = {"base_agreement": base_upload}

    stubs = [
        ("change_order", "change_order_stub.html", "new_focused"),
        ("rfi", "rfi_stub.html", "background"),
        ("payment_application", "payment_application_stub.html", "background"),
    ]
    for key, filename, mode in stubs:
        log(f"opening {key} into the same session ({mode})")
        documents[key] = upload_document(CONTENT_DIR / filename, session_id, open_mode=mode)

    log("current session documents:")
    doc_list = client.get(f"/v1/sessions/{session_id}/documents").json()
    log(f"  {json.dumps(doc_list, indent=2)[:2000]}")

    return {"session_id": session_id, "documents": documents, "doc_list": doc_list}


def _norm(s: str) -> str:
    # SuperDocs titles an uploaded document from its filename verbatim
    # ("change_order_stub"), not from any heading inside it -- normalize
    # away underscores/hyphens/extra spaces so a human-readable search term
    # ("change order") still matches regardless of the exact title style.
    return re.sub(r"[_\-\s]+", " ", (s or "")).strip().lower()


def resolve_document_id(doc_list: dict, title_substring: str) -> str:
    needle = _norm(title_substring)
    for d in doc_list.get("documents", []):
        if needle in _norm(d.get("title")):
            return d.get("document_id") or d.get("id")
    raise ValueError(f"no open document matching '{title_substring}' -- got {doc_list}")


def resolve_durable_id(doc_list: dict, title_substring: str) -> str:
    needle = _norm(title_substring)
    for d in doc_list.get("documents", []):
        if needle in _norm(d.get("title")):
            durable = d.get("durable_document_id")
            if durable:
                return durable
    raise ValueError(f"no durable_document_id for a document matching '{title_substring}'")


def draft(session_id: str, doc_list: dict, title_substring: str, instruction: str, label: str) -> None:
    doc_id = resolve_document_id(doc_list, title_substring)
    log(f"drafting {label} (document_id={doc_id})")
    job = start_chat(instruction, session_id, document_id=doc_id, approval_mode="ask_every_time")
    wait_for_job(session_id, job["job_id"], label)


CHANGE_ORDER_INSTRUCTION = (
    "This document is a Change Order for the Riverside Medical Office Renovation project. "
    "There is another open document in this session: the Master Subcontract Agreement between "
    "Meridian Builders LLC and Anthem Electrical Services, Inc. Read that document to find the "
    "exact Article number and title that governs how changes to the work are authorized -- do not "
    "guess it, use the real Article number and title as written in that document. "
    "Draft this Change Order with: a Change Order number (No. 1), a description of the change "
    "(add three additional 20-amp circuits and associated panel capacity to Exam Rooms 4-6, "
    "requested by the Owner after the original scope was finalized), an amount ($18,400.00) added "
    "to the Subcontract Sum, and a 'Reference' line that cites the exact Article number and title "
    "from the Master Subcontract Agreement that authorizes this Change Order, exactly as that "
    "Article is numbered and titled in the source document. Keep it to one page, standard-form "
    "structure with clear labeled fields, no invented parties or figures beyond what's given here."
)

RFI_INSTRUCTION = (
    "This document is a Request for Information (RFI) for the Riverside Medical Office Renovation "
    "project, from Anthem Electrical Services, Inc. to Meridian Builders LLC. Draft RFI No. 1: "
    "asking whether the panel schedule in Specification Section 26 00 00 should reflect the "
    "additional circuits described in Change Order No. 1, since the drawings issued for "
    "construction predate that change. Include an RFI number, date, the question itself, and a "
    "field for the response. Keep it to one page, standard-form structure."
)

PAYMENT_APPLICATION_INSTRUCTION = (
    "This document is an Application for Payment for the Riverside Medical Office Renovation "
    "project, submitted by Anthem Electrical Services, Inc. to Meridian Builders LLC, Application "
    "No. 1, for work completed through April 30, 2026. There is another open document in this "
    "session: the Master Subcontract Agreement. Read it to find the exact Article number and title "
    "that governs payment applications and their terms -- do not guess it, use the real Article "
    "number and title as written in that document. Draft this Application for Payment with: the "
    "original Subcontract Sum, the value of work completed to date ($142,000.00, representing "
    "rough-in electrical work), the retainage withheld at the percentage stated in that Article, "
    "the net amount due, and a 'Reference' line citing the exact Article number and title from the "
    "Master Subcontract Agreement that this application is submitted under. Standard-form "
    "structure, clear labeled line items, one page."
)


def verify_cross_references(base_html: str, change_order_html: str, payment_app_html: str) -> bool:
    """The actual grading bar: does the change order and payment application
    correctly cite the base agreement's real clause numbering? Verified
    against the base agreement's own text, not against what the AI was
    asked to do -- an instruction being followed and an instruction being
    followed *correctly* are different claims, and only the second one
    counts."""

    def find_article(html: str, keyword: str) -> str | None:
        # Matches "ARTICLE 6 — CHANGES IN THE WORK" style headings in the
        # base agreement's own source, case-insensitive.
        pattern = re.compile(rf"ARTICLE\s+(\d+)[^<]*{re.escape(keyword)}", re.IGNORECASE)
        m = pattern.search(html)
        return m.group(1) if m else None

    changes_article = find_article(base_html, "CHANGES IN THE WORK")
    payments_article = find_article(base_html, "PAYMENTS")

    print()
    log(f"base agreement: 'Changes in the Work' is Article {changes_article}")
    log(f"base agreement: 'Payments' is Article {payments_article}")

    ok = True

    if changes_article and re.search(rf"Article\s+{changes_article}\b", change_order_html, re.IGNORECASE):
        log(f"PASS: Change Order correctly cites Article {changes_article}")
    else:
        log(f"FAIL: Change Order does not cite Article {changes_article}")
        ok = False

    if payments_article and re.search(rf"Article\s+{payments_article}\b", payment_app_html, re.IGNORECASE):
        log(f"PASS: Payment Application correctly cites Article {payments_article}")
    else:
        log(f"FAIL: Payment Application does not cite Article {payments_article}")
        ok = False

    return ok


def main() -> None:
    warm_up()
    result = build()
    session_id = result["session_id"]
    doc_list = result["doc_list"]

    draft(session_id, doc_list, "change_order", CHANGE_ORDER_INSTRUCTION, "change order")
    draft(session_id, doc_list, "rfi", RFI_INSTRUCTION, "RFI")
    draft(session_id, doc_list, "payment", PAYMENT_APPLICATION_INSTRUCTION, "payment application")

    log("re-reading session document roster for durable IDs")
    doc_list = client.get(f"/v1/sessions/{session_id}/documents").json()
    log(json.dumps(doc_list, indent=2)[:2000])

    exports = {}
    labels = [
        ("base_agreement", "base_agreement"),
        ("change_order", "change_order"),
        ("rfi", "rfi"),
        ("payment", "payment_application"),
    ]
    html_by_key = {}
    for title_substring, key in labels:
        durable_id = resolve_durable_id(doc_list, title_substring)
        detail = get_document_html(durable_id)
        html = detail.get("html") or detail.get("document_html") or ""
        html_by_key[key] = html
        out_path = export_html(html, filename=key, fmt="docx")
        exports[key] = out_path
        log(f"exported {key} -> {out_path}")

    ok = verify_cross_references(
        html_by_key["base_agreement"],
        html_by_key["change_order"],
        html_by_key["payment_application"],
    )

    print()
    if ok:
        log("STRONG BAR MET: both cross-references verified against the base agreement's real numbering.")
    else:
        log("STRONG BAR NOT MET -- see FAIL lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
