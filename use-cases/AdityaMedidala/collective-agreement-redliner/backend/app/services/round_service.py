"""
Runs one redline round, lists its pending changes for review, and records
decisions. The OpenItem upserts here (upsert_proposed_item,
upsert_decided_item) are the tracker's write path — tracker_service.reconcile
reuses them verbatim for its rebuild-from-job-history path, so the
open/reopen transition logic only lives in one place.
"""

import logging

from sqlalchemy.orm import Session

from app.models import Negotiation, OpenItem, OpenItemStatus, Round, RoundStatus
from app.services.polling import poll_job
from app.superdocs_client import SuperDocsClient

logger = logging.getLogger(__name__)

DEFAULT_ROUND_PROMPT = (
    "Compare the current agreement against the attached union and employer "
    "position papers. Propose redlines that reconcile differences where "
    "possible, and flag anywhere the two sides still disagree."
)

# per docs/superdocs-api-reference.md, chat/async jobs land on
# awaiting_approval once redlines are ready; completed/failed also stop
# the poll (a round can need no changes, or error out)
TERMINAL_ROUND_STATUSES = {RoundStatus.AWAITING_APPROVAL, RoundStatus.COMPLETED, RoundStatus.FAILED}

# after a decision is submitted, only these two mean the job has actually
# resolved one way or another
DECISION_TERMINAL_STATUSES = {RoundStatus.COMPLETED, RoundStatus.FAILED}


def _is_round_job_terminal(job: dict) -> bool:
    # inclusion check, not exclusion: a live response showed status
    # "in_progress" (undocumented, not "pending"/"processing"), which an
    # exclusion-based check ("not in pending/processing") wrongly treated
    # as terminal — inclusion fails safe, bounded polling just times out
    # to FAILED on any other unrecognized in-flight status instead
    return job.get("status") in TERMINAL_ROUND_STATUSES


def _is_decision_job_terminal(job: dict) -> bool:
    return job.get("status") in DECISION_TERMINAL_STATUSES


# best-effort only, per CLAUDE.md: if the round's own text plainly names a
# side, use it; otherwise "unknown" is an honest answer, not a bug. See
# PROGRESS.md "raised_by" limitation entry. ai_explanation/old_html/new_html
# are the live-confirmed field names (2026-08-12); message/summary/etc are
# kept as speculative fallbacks in case other operation types use them.
def _infer_raised_by(job: dict, change: dict) -> str:
    text_parts: list[str] = []
    for key in ("ai_explanation", "old_html", "new_html", "message", "summary", "explanation", "rationale", "reasoning"):
        val = change.get(key)
        if isinstance(val, str):
            text_parts.append(val)
    content = change.get("content")
    if isinstance(content, dict):
        text_parts.extend(v for v in content.values() if isinstance(v, str))
    elif isinstance(content, str):
        text_parts.append(content)
    for key in ("message", "summary"):
        val = job.get(key) or job.get("metadata", {}).get(key)
        if isinstance(val, str):
            text_parts.append(val)

    text = " ".join(text_parts).lower()
    mentions_union = "union" in text
    mentions_employer = "employer" in text
    if mentions_union and not mentions_employer:
        return "union"
    if mentions_employer and not mentions_union:
        return "employer"
    return "unknown"


def upsert_proposed_item(
    db: Session, negotiation_id: str, round_id: str, chunk_id: str, change: dict, job: dict
) -> OpenItem:
    """New proposal against chunk_id. New chunk -> OPEN. A chunk previously
    decided (APPROVED/REJECTED) -> REOPENED, per the card's core contract.
    A chunk already OPEN/REOPENED (still undecided) just gets its snapshot
    and round link refreshed — it doesn't need a status change."""
    item = db.query(OpenItem).filter_by(negotiation_id=negotiation_id, chunk_id=chunk_id).one_or_none()
    inferred = _infer_raised_by(job, change)

    if item is None:
        item = OpenItem(
            negotiation_id=negotiation_id,
            chunk_id=chunk_id,
            status=OpenItemStatus.OPEN,
            raised_by=inferred,
            first_round_id=round_id,
            last_round_id=round_id,
            last_diff_snapshot=change,
        )
        db.add(item)
        return item

    if item.status in (OpenItemStatus.APPROVED, OpenItemStatus.REJECTED):
        item.status = OpenItemStatus.REOPENED
    item.last_round_id = round_id
    item.last_diff_snapshot = change
    if inferred != "unknown":
        item.raised_by = inferred
    return item


def upsert_decided_item(db: Session, negotiation_id: str, round_id: str, chunk_id: str, approved: bool) -> OpenItem:
    """A decision was made on chunk_id this round. Creates the OpenItem
    defensively if a decision arrives for a chunk we never recorded a
    proposal for (shouldn't normally happen, but a decided item existing
    beats a crash)."""
    item = db.query(OpenItem).filter_by(negotiation_id=negotiation_id, chunk_id=chunk_id).one_or_none()
    if item is None:
        item = OpenItem(
            negotiation_id=negotiation_id,
            chunk_id=chunk_id,
            raised_by="unknown",
            first_round_id=round_id,
            last_round_id=round_id,
        )
        db.add(item)
    item.status = OpenItemStatus.APPROVED if approved else OpenItemStatus.REJECTED
    item.last_round_id = round_id
    return item


def start_round(db: Session, client: SuperDocsClient, negotiation_id: str, prompt: str | None = None) -> Round:
    negotiation = db.get(Negotiation, negotiation_id)
    if negotiation is None:
        raise ValueError(f"no negotiation {negotiation_id}")

    prompt_used = prompt or DEFAULT_ROUND_PROMPT
    # a direct query, not len(negotiation.rounds): the ORM relationship
    # collection caches whatever it saw on first access and, with
    # expire_on_commit=False, doesn't refresh after a later commit in the
    # same session — confirmed live 2026-08-12 this under-counts (and
    # tracker_service.reconcile hit the same trap, see there)
    round_number = db.query(Round).filter_by(negotiation_id=negotiation_id).count() + 1

    start_response = client.start_round(negotiation.superdocs_session_id, prompt_used)
    job_id = start_response["job_id"]

    round_ = Round(
        negotiation_id=negotiation_id,
        round_number=round_number,
        superdocs_job_id=job_id,
        status=RoundStatus.PENDING,
        prompt_used=prompt_used,
    )
    db.add(round_)
    db.commit()
    db.refresh(round_)

    job = poll_job(client, job_id, _is_round_job_terminal)
    status = job.get("status")
    if status in TERMINAL_ROUND_STATUSES:
        round_.status = status
    else:
        logger.warning("round %s job %s stuck on status %r after max poll attempts", round_.id, job_id, status)
        round_.status = RoundStatus.FAILED
    db.commit()
    db.refresh(round_)
    return round_


def list_pending_changes(db: Session, client: SuperDocsClient, round_id: str) -> list[dict]:
    round_ = db.get(Round, round_id)
    if round_ is None:
        raise ValueError(f"no round {round_id}")

    job = client.get_job(round_.superdocs_job_id)
    changes = SuperDocsClient.parse_pending_changes(job)
    for change in changes:
        chunk_id = change.get("chunk_id")
        if chunk_id is None:
            continue
        upsert_proposed_item(db, round_.negotiation_id, round_.id, chunk_id, change, job)
    db.commit()
    return changes


def decide(db: Session, client: SuperDocsClient, round_id: str, decisions: list[dict]) -> Round:
    """decisions: [{"chunk_id": ..., "approved": bool, "feedback": str|None}, ...] —
    our domain API stays chunk_id-keyed (chunk_id is the stable cross-round
    identifier OpenItem tracks), but the live approve endpoint is keyed by
    change_id (the per-proposal id, confirmed 2026-08-12 — see PROGRESS.md),
    one decision per call. So this re-fetches the round's current pending
    changes to build the chunk_id -> change_id map before submitting."""
    round_ = db.get(Round, round_id)
    if round_ is None:
        raise ValueError(f"no round {round_id}")
    if round_.superdocs_job_id is None:
        raise ValueError(f"round {round_id} has no job to decide on")

    negotiation = round_.negotiation
    pending = SuperDocsClient.parse_pending_changes(client.get_job(round_.superdocs_job_id))
    change_id_by_chunk = {c["chunk_id"]: c.get("change_id") for c in pending if c.get("chunk_id")}

    for decision in decisions:
        chunk_id = decision.get("chunk_id")
        approved = decision.get("approved")
        if chunk_id is None or approved is None:
            continue
        change_id = change_id_by_chunk.get(chunk_id)
        if change_id is None:
            logger.warning("decide: no pending change_id found for chunk_id %s on round %s, skipping", chunk_id, round_.id)
            continue
        client.approve_change(
            negotiation.superdocs_session_id,
            round_.superdocs_job_id,
            change_id,
            approved,
            decision.get("feedback"),
        )
        upsert_decided_item(db, round_.negotiation_id, round_.id, chunk_id, approved)

    job = poll_job(client, round_.superdocs_job_id, _is_decision_job_terminal)
    status = job.get("status")
    if status in TERMINAL_ROUND_STATUSES:
        round_.status = status
    else:
        logger.warning(
            "round %s job %s stuck on status %r after decisions, after max poll attempts",
            round_.id,
            round_.superdocs_job_id,
            status,
        )
        round_.status = RoundStatus.FAILED
    db.commit()
    db.refresh(round_)
    return round_
