"""The Supporting Memo - a first-class generated artifact.

The close pack previously produced only per-section sheets assembled at export time.
The memo is the one narrative artifact that summarises the period from the uploaded
source evidence: what was provided, what the checklist attests to, what SuperDocs
proposed and how each proposal was decided, and who signed.

It is generated when the close pack is generated (so it is visible in the UI as soon as
generation finishes) and rebuilt at export time so the packaged copy reflects the review
decisions and sign-offs made after generation.
"""

from typing import Any

from . import storage
from .clock import now_iso
from .closes import new_id
from .pdf import build_pdf

SUPPORTING_MEMO_NAME = "Supporting Memo.pdf"
SUPPORTING_MEMO_KIND = "SUPPORTING_MEMO"


def _evidence_lines(close: dict[str, Any]) -> list[str]:
    ready = [doc for doc in close.get("documents", []) if doc.get("status") == "READY"]
    if not ready:
        return ["  (no classified source documents)"]
    return [
        f"  - {doc['document_type']}: {doc['filename']} "
        f"({doc.get('size', 0)} bytes, sha256 {str(doc.get('sha256') or '')[:12]})"
        for doc in ready
    ]


def _checklist_lines(close: dict[str, Any]) -> list[str]:
    checklist = close.get("checklist") or []
    if not checklist:
        return ["  (no checklist items)"]
    return [
        f"  [{'x' if item['status'] == 'COMPLETE' else ' '}] {item['title']}"
        f" - {item.get('completed_by') or 'unassigned'}"
        for item in checklist
    ]


def _change_lines(close: dict[str, Any]) -> list[str]:
    reviews = close.get("reviews") or []
    if not reviews:
        return ["  (SuperDocs proposed no changes)"]
    lines: list[str] = []
    for review in reviews:
        decided = review.get("reviewed_by") or "undecided"
        lines.append(f"  [{review['status']}] {review['section']} - {decided}")
        lines.append(f"        source: {review.get('source_reference') or 'n/a'}")
        if review.get("reason"):
            lines.append(f"        reason: {review['reason']}")
    return lines


def _signoff_lines(close: dict[str, Any]) -> list[str]:
    signoffs = close.get("signoffs") or []
    if not signoffs:
        return ["  (no sign-offs required)"]
    return [
        f"  {item['role']}: {item.get('person') or 'unsigned'} ({item['status']})" for item in signoffs
    ]


def build_supporting_memo_bytes(close: dict[str, Any], readiness: dict[str, Any]) -> bytes:
    documents = readiness["documents"]
    checklist = readiness["checklist"]
    reviews = readiness["reviews"]
    signoffs = readiness["signoffs"]

    lines = [
        f"Entity : {close['entity']}",
        f"Period : {close['period']}",
        f"Owner  : {close['owner']}",
        f"Status : {'CLOSED' if close.get('closed_at') else 'OPEN'}",
        "",
        "SOURCE EVIDENCE",
        f"  {documents['present']} of {documents['required']} required document types provided",
        *_evidence_lines(close),
        "",
        "CHECKLIST",
        f"  {checklist['complete']} of {checklist['required']} complete",
        *_checklist_lines(close),
        "",
        "SUPERDOCS PROPOSED CHANGES",
        f"  {reviews['resolved']} of {reviews['total']} decided",
        *_change_lines(close),
        "",
        "SIGN-OFFS",
        f"  {signoffs['approved']} of {signoffs['required']} approved",
        *_signoff_lines(close),
    ]
    return build_pdf(f"Supporting Memo - {close['entity']} {close['period']}", lines)


def upsert_supporting_memo(close: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    """Generate (or regenerate) the memo and record it as a generated artifact.

    Called from generation and again from export, so the packaged copy is never older
    than the decisions it describes.
    """
    content = build_supporting_memo_bytes(close, readiness)
    artifacts: list[dict[str, Any]] = close.setdefault("generated_artifacts", [])
    existing = next((item for item in artifacts if item.get("kind") == SUPPORTING_MEMO_KIND), None)

    artifact_id = existing["id"] if existing else new_id("art")
    key = f"closes/{close['id']}/generated/{artifact_id}/{SUPPORTING_MEMO_NAME}"
    stored = storage.put_bytes(key, content)

    artifact = {
        "id": artifact_id,
        "name": SUPPORTING_MEMO_NAME,
        "kind": SUPPORTING_MEMO_KIND,
        "content_type": "application/pdf",
        "storage_key": key,
        "size": stored["size"],
        "sha256": stored["sha256"],
        "generated_at": now_iso(),
        "description": "Period close summary built from the uploaded source evidence.",
    }
    if existing:
        existing.update(artifact)
        return existing
    artifacts.append(artifact)
    return artifact


def find_artifact(close: dict[str, Any], artifact_id: str) -> dict[str, Any] | None:
    for artifact in close.get("generated_artifacts") or []:
        if artifact["id"] == artifact_id:
            return artifact
    return None
