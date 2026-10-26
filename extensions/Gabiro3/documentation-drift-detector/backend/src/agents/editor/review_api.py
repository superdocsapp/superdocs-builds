import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from core.db import exec, exec_one, insert, update
from core.models import ReviewDecision
from core.superdocs_client import SuperDocsClient
from core.text import html_to_text
from core.trace import TraceLogger

logger = logging.getLogger(__name__)

app = FastAPI(title="Drift Detector â€” Agent #3 (Edit Engine / Review API)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
sd_client = SuperDocsClient()

# Applies are serialised. An edit is issued against the *focused* document in a
# SuperDocs session, so two applies running at once would fight over which
# document is focused and one could land its edit in the other's document.
# The byte Judge would catch that after the fact; not racing is better than
# detecting the race.
_apply_lock = asyncio.Lock()


class ApplyStatus:
    """What happened to an approved fix, as distinct from the human decision.

    `review_decisions.decision` records that a person said yes. This records
    whether the document actually changed — the two used to be conflated, so an
    approval that never reached the document looked identical to one that did.
    """

    QUEUED = "queued"
    APPLYING = "applying"
    APPLIED = "applied"
    BLOCKED = "blocked"
    FAILED = "failed"
    # The document itself is gone from SuperDocs, so no retry can succeed.
    # Distinct from FAILED because the remedy is different: re-ingest the
    # document rather than try again.
    DOCUMENT_MISSING = "document_missing"


class ApproveRequest(BaseModel):
    feedback: str = ""


class RejectRequest(BaseModel):
    feedback: str = ""


@app.on_event("startup")
async def _migrate():
    # This service writes findings.apply_status and the applied_edits history
    # columns; both arrive in a migration that initdb will not replay against
    # an existing volume.
    from core.migrate import apply_migrations

    await apply_migrations()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/review/{run_id}")
async def get_review(run_id: str):
    rows = await exec(
        """
        SELECT f.id, f.state, f.chunk_id, f.evidence_quote, f.evidence_chunk_id,
               f.proposed_old, f.proposed_new, f.ai_explanation,
               f.document_id, d.filename,
               f.apply_status, f.apply_reason, f.applied_at,
               rd.decision AS review_decision, rd.feedback AS review_feedback
        FROM findings f
        LEFT JOIN review_decisions rd ON rd.finding_id = f.id
        LEFT JOIN documents d ON d.id = f.document_id
        WHERE f.run_id = :rid
        ORDER BY f.state, f.created_at
        """,
        {"rid": run_id},
    )
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "state": r["state"],
            "chunk_id": r["chunk_id"],
            "evidence_quote": r["evidence_quote"],
            "evidence_chunk_id": r["evidence_chunk_id"],
            "proposed_old": r["proposed_old"],
            "proposed_new": r["proposed_new"],
            "ai_explanation": r["ai_explanation"],
            "document_id": r["document_id"],
            "filename": r["filename"],
            "review_decision": r["review_decision"],
            "review_feedback": r["review_feedback"],
            "apply_status": r["apply_status"],
            "apply_reason": r["apply_reason"],
            "applied_at": r["applied_at"],
        })
    return {"run_id": run_id, "findings": results}


@app.post("/review/{finding_id}/approve")
async def approve_finding(
    finding_id: str,
    background: BackgroundTasks,
    body: ApproveRequest = ApproveRequest(),
):
    """Approve a finding and apply it to the document.

    Approval used to write a review_decisions row and stop there, so a fix a
    human had explicitly accepted never reached the document unless someone
    also pressed "Apply approved". The edit is now scheduled here.

    It runs in the background rather than inline: an apply is a SuperDocs
    chat job that is polled to completion, which can take minutes, and holding
    the HTTP request open that long would hand the caller a timeout instead of
    an answer. The finding carries `apply_status` so the outcome is
    observable — a background task that failed silently would be the same bug
    in a new place.
    """
    finding = await exec_one(
        "SELECT id, run_id FROM findings WHERE id = :fid",
        {"fid": finding_id},
    )
    if not finding:
        raise HTTPException(404, "Finding not found")

    rd = ReviewDecision(
        finding_id=UUID(finding_id),
        decision="approved",
        feedback=body.feedback or None,
        decided_at=datetime.now(timezone.utc),
    )

    existing = await exec_one(
        "SELECT id FROM review_decisions WHERE finding_id = :fid",
        {"fid": finding_id},
    )
    if existing:
        await update(
            "review_decisions",
            {"finding_id": str(finding_id)},
            {"decision": "approved", "feedback": body.feedback or None, "decided_at": datetime.now(timezone.utc)},
        )
    else:
        await insert("review_decisions", rd.model_dump())

    already = await exec_one(
        "SELECT id FROM applied_edits WHERE finding_id = :fid", {"fid": finding_id}
    )
    if already:
        return {"finding_id": finding_id, "status": "approved",
                "apply_status": ApplyStatus.APPLIED}

    await update(
        "findings",
        {"id": finding_id},
        {"apply_status": ApplyStatus.QUEUED, "apply_reason": None},
    )
    background.add_task(_apply_finding_in_background, finding_id)

    return {"finding_id": finding_id, "status": "approved",
            "apply_status": ApplyStatus.QUEUED}


async def _apply_finding_in_background(finding_id: str) -> None:
    """Run one apply off the request path, recording the outcome either way."""
    try:
        async with _apply_lock:
            row = await exec_one(_APPLY_SELECT + " WHERE f.id = :fid", {"fid": finding_id})
            if not row:
                return

            # The decision can change between approving and applying — a
            # rejection that arrives first must win, or we would edit a
            # document against the human's latest instruction.
            decision = await exec_one(
                "SELECT decision FROM review_decisions WHERE finding_id = :fid",
                {"fid": finding_id},
            )
            if not decision or decision["decision"] != "approved":
                await update(
                    "findings", {"id": finding_id},
                    {"apply_status": None, "apply_reason": None},
                )
                return

            await _apply_one(dict(row), str(row["run_id"]))
    except Exception as exc:
        logger.exception("Background apply failed for finding %s", finding_id)
        # Never let a background failure disappear: the UI polls apply_status.
        await update(
            "findings",
            {"id": finding_id},
            {"apply_status": ApplyStatus.FAILED, "apply_reason": str(exc)[:300]},
        )


@app.post("/review/{finding_id}/reject")
async def reject_finding(finding_id: str, body: RejectRequest = RejectRequest()):
    finding = await exec_one(
        "SELECT id FROM findings WHERE id = :fid",
        {"fid": finding_id},
    )
    if not finding:
        raise HTTPException(404, "Finding not found")

    rd = ReviewDecision(
        finding_id=UUID(finding_id),
        decision="rejected",
        feedback=body.feedback or None,
        decided_at=datetime.now(timezone.utc),
    )

    existing = await exec_one(
        "SELECT id FROM review_decisions WHERE finding_id = :fid",
        {"fid": finding_id},
    )
    if existing:
        await update(
            "review_decisions",
            {"finding_id": str(finding_id)},
            {"decision": "rejected", "feedback": body.feedback or None, "decided_at": datetime.now(timezone.utc)},
        )
    else:
        await insert("review_decisions", rd.model_dump())

    # An approval may already have queued an apply. Clearing the queued state
    # tells the worker to stand down; anything already applied keeps its
    # status, because that edit is a fact about the document now.
    await exec(
        "UPDATE findings SET apply_status = NULL, apply_reason = NULL "
        "WHERE id = :fid AND apply_status = :queued",
        {"fid": finding_id, "queued": ApplyStatus.QUEUED},
    )

    return {"finding_id": finding_id, "status": "rejected"}


# Every apply path needs the same columns; callers append their own WHERE.
_APPLY_SELECT = """
        SELECT f.id, f.run_id, f.chunk_id, f.evidence_chunk_id, f.proposed_old,
               f.proposed_new, f.document_id, d.superdocs_doc_id, d.session_id
          FROM findings f
          LEFT JOIN documents d ON d.id = f.document_id
"""


async def _sync_stored_chunks(document_id: str, post_chunks: list[dict]) -> int:
    """Bring our stored copy of a document in line with the edited original.

    The document view, downloads and retrieval all read `chunks` from Postgres.
    Applying an edit in SuperDocs without writing it back here left the stored
    copy frozen at ingest time, so an approved fix was invisible in the very
    place a user goes to look at the document.

    Embeddings of changed chunks are dropped rather than kept: a vector that
    describes text the chunk no longer contains is worse than no vector, since
    the embedder treats a present embedding as a cache hit and would never
    recompute it.
    """
    if not document_id or not post_chunks:
        return 0

    stored = {
        r["chunk_id"]: r["content_hash"]
        for r in await exec(
            "SELECT chunk_id, content_hash FROM chunks WHERE document_id = :did",
            {"did": str(document_id)},
        )
    }

    changed = 0
    for chunk in post_chunks:
        cid = chunk.get("chunk_id")
        if cid is None or cid not in stored:
            # Only chunks we already track are updated here. A chunk appearing
            # or vanishing is a structural change the byte Judge should have
            # blocked, so it is not quietly reconciled.
            continue
        if stored[cid] == chunk.get("content_hash"):
            continue
        await exec(
            "UPDATE chunks SET html = :html, text_content = :text, "
            "content_hash = :hash, embedding = NULL "
            "WHERE document_id = :did AND chunk_id = :cid",
            {
                "html": chunk.get("html", ""),
                # Search must see the edited text, not the text it replaced.
                "text": html_to_text(chunk.get("html", "")),
                "hash": chunk.get("content_hash", ""),
                "did": str(document_id),
                "cid": cid,
            },
        )
        changed += 1

    return changed


async def _apply_one(row: dict, run_id: str) -> dict:
    """Apply a single approved finding under the two-phase byte Judge."""
    from agents.editor.editor import ApplyOutcome, Editor

    finding_id = str(row["id"])
    target_chunk = row["evidence_chunk_id"] or row["chunk_id"]
    superdocs_doc_id = row["superdocs_doc_id"]
    document_id = row.get("document_id")

    async def _fail(reason: str, status: str = ApplyStatus.FAILED) -> dict:
        await update(
            "findings",
            {"id": finding_id},
            {"apply_status": status, "apply_reason": reason[:300]},
        )
        return {"finding_id": finding_id, "status": ApplyOutcome.FAILED, "reason": reason}

    if not superdocs_doc_id:
        # An empty id means the upload never produced a durable document.
        # Retrying the apply cannot fix that; re-ingesting can.
        return await _fail(
            "This document has no SuperDocs document id, so it was never stored "
            "durably. Re-ingest it from its source file before applying fixes.",
            ApplyStatus.DOCUMENT_MISSING,
        )
    if not target_chunk:
        return await _fail("finding names no target chunk")
    if not row["proposed_old"] or not row["proposed_new"]:
        return await _fail("finding has no concrete old->new replacement")

    # Idempotency: never apply the same finding twice.
    existing = await exec_one(
        "SELECT id FROM applied_edits WHERE finding_id = :fid", {"fid": finding_id}
    )
    if existing:
        return {"finding_id": finding_id, "status": "ALREADY_APPLIED"}

    await update(
        "findings",
        {"id": finding_id},
        {"apply_status": ApplyStatus.APPLYING, "apply_reason": None},
    )

    editor = Editor(sd_client, TraceLogger(UUID(run_id)))
    result = await editor.apply_fix(
        superdocs_doc_id=superdocs_doc_id,
        target_chunk_id=target_chunk,
        old_text=row["proposed_old"],
        new_text=row["proposed_new"],
        # Editing is session-scoped, and each document lives in its own
        # session. Using the global one would edit the wrong document.
        session_id=row.get("session_id"),
    )

    if result["status"] == ApplyOutcome.APPLIED:
        applied_at = datetime.now(timezone.utc)

        # The history row carries the before/after text, not just SuperDocs
        # ids: ids prove an edit happened, content shows what it did.
        await insert(
            "applied_edits",
            {
                "finding_id": finding_id,
                "document_id": str(document_id) if document_id else None,
                "chunk_id": target_chunk,
                "superdocs_job_id": result.get("job_id", ""),
                "superdocs_change_id": ",".join(result.get("change_ids", []))[:200] or None,
                "before_html": result.get("before_html"),
                "after_html": result.get("after_html"),
                "before_hash": result.get("before_hash"),
                "after_hash": result.get("after_hash"),
                "proposed_old": row["proposed_old"],
                "proposed_new": row["proposed_new"],
                "applied_at": applied_at,
            },
        )

        synced = await _sync_stored_chunks(document_id, result.get("post_chunks") or [])
        result["chunks_synced"] = synced

        await update(
            "findings",
            {"id": finding_id},
            {
                "judge_verdict": "byte-verified",
                "apply_status": ApplyStatus.APPLIED,
                "apply_reason": None,
                "applied_at": applied_at,
            },
        )
    elif result["status"] in (ApplyOutcome.NEEDS_ESCALATION, ApplyOutcome.ALARM):
        # Commit blocked. Record why so it surfaces instead of vanishing.
        await update(
            "findings",
            {"id": finding_id},
            {
                "judge_verdict": f"{result['status']}: {result.get('reason', '')[:300]}",
                "apply_status": ApplyStatus.BLOCKED,
                "apply_reason": f"{result['status']}: {result.get('reason', '')[:280]}",
            },
        )
        await insert(
            "queues",
            {
                "finding_id": finding_id,
                "kind": "failed",
                "reason": f"{result['status']}: {result.get('reason', '')[:400]}",
                "created_at": datetime.now(timezone.utc),
            },
        )
    elif result["status"] == ApplyOutcome.FAILED:
        await update(
            "findings",
            {"id": finding_id},
            {
                # A missing document is not a retryable failure.
                "apply_status": (
                    ApplyStatus.DOCUMENT_MISSING
                    if result.get("document_missing")
                    else ApplyStatus.FAILED
                ),
                "apply_reason": str(result.get("reason", ""))[:300],
            },
        )

    # The full post-edit document is an implementation detail of the write-back
    # and has no place in an API response.
    result.pop("post_chunks", None)
    return {"finding_id": finding_id, **result}


@app.post("/apply/{run_id}")
async def apply_approved(run_id: str):
    """Apply every approved-but-unapplied finding for a run.

    Each edit is scoped to one chunk and gated by the byte Judge: Phase A
    rejects a batch that strays outside the approved chunk before anything
    lands, Phase B proves every other chunk is byte-identical afterwards.
    """
    rows = await exec(
        _APPLY_SELECT
        + """
          JOIN review_decisions rd ON rd.finding_id = f.id
         WHERE f.run_id = :rid AND rd.decision = 'approved'
        """,
        {"rid": run_id},
    )

    async with _apply_lock:
        results = [await _apply_one(dict(r), run_id) for r in rows]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    return {
        "run_id": run_id,
        "considered": len(results),
        "counts": counts,
        "items": results,
    }


@app.post("/apply/finding/{finding_id}")
async def apply_single_finding(finding_id: str):
    """Apply one approved finding — the per-item path used by the UI."""
    row = await exec_one(_APPLY_SELECT + " WHERE f.id = :fid", {"fid": finding_id})
    if not row:
        raise HTTPException(404, "Finding not found")

    decision = await exec_one(
        "SELECT decision FROM review_decisions WHERE finding_id = :fid",
        {"fid": finding_id},
    )
    if not decision or decision["decision"] != "approved":
        raise HTTPException(409, "Finding must be approved before it can be applied")

    async with _apply_lock:
        return await _apply_one(dict(row), str(row["run_id"]))


@app.get("/export/{run_id}")
async def export_document(run_id: str):
    url = await sd_client.request_download_url(format="docx")
    return {"run_id": run_id, "download_url": url}