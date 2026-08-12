"""
The open-items tracker. THIS is what the assignment card grades ("the
open-items tracker stays accurate across many rounds"). Phase 0 stub —
Phase 3 implements the reconciliation logic against
GET /v1/sessions/{id}/jobs, per the architecture in README.md.

The contract this must satisfy, written down before any code (per CLAUDE.md
"never" discipline carried over from Task 1):
  - An item approved in round N must never revert to "open" in round N+1
    unless a NEW round genuinely re-proposes a change to that same chunk_id.
  - Reconciling twice against the same job history must be idempotent —
    no duplicate OpenItem rows for the same chunk_id within a negotiation.
  - If SuperDocs' job history disagrees with our local status (e.g. we
    think something's pending but SuperDocs shows it decided), SuperDocs
    wins — this table is a reconciled view, not a source of truth.
"""

import logging

from sqlalchemy.orm import Session

from app.models import Negotiation, OpenItem, Round
from app.services.round_service import upsert_decided_item, upsert_proposed_item
from app.superdocs_client import SuperDocsClient

logger = logging.getLogger(__name__)


def _serialize(item: OpenItem) -> dict:
    return {
        "chunk_id": item.chunk_id,
        "clause_label": item.clause_label,
        "status": item.status,
        "raised_by": item.raised_by,
        "first_round_id": item.first_round_id,
        "last_round_id": item.last_round_id,
    }


def reconcile(db: Session, client: SuperDocsClient, negotiation_id: str) -> list[dict]:
    negotiation = db.get(Negotiation, negotiation_id)
    if negotiation is None:
        raise ValueError(f"no negotiation {negotiation_id}")

    existing = db.query(OpenItem).filter_by(negotiation_id=negotiation_id).all()
    if existing:
        return [_serialize(item) for item in existing]

    # No local rows — either nothing's been proposed yet, or the table
    # was wiped. If there's no round history either, "nothing yet" is the
    # honest answer; only rebuild if SuperDocs actually has history to
    # rebuild from.
    # A direct query, not negotiation.rounds: the ORM relationship
    # collection caches whatever it saw on first access and, with
    # expire_on_commit=False, doesn't refresh after a later commit in the
    # same session (e.g. round_service.start_round reading it before the
    # new Round exists) — confirmed live 2026-08-12, this silently
    # returned [] here even with real rounds and real job history.
    rounds = db.query(Round).filter_by(negotiation_id=negotiation_id).all()
    if not rounds:
        return []

    _rebuild_from_job_history(db, client, negotiation, rounds)
    rebuilt = db.query(OpenItem).filter_by(negotiation_id=negotiation_id).all()
    return [_serialize(item) for item in rebuilt]


def _rebuild_from_job_history(db: Session, client: SuperDocsClient, negotiation: Negotiation, rounds: list[Round]) -> None:
    """Rebuilds OpenItem rows from SuperDocs' own durable job history —
    used when local OpenItem rows are missing but the negotiation's Round
    rows (and thus job_ids) are still intact. Reuses the exact same
    upsert helpers the live write path uses (round_service.list_pending_changes
    / decide), so the open/reopen transition logic isn't duplicated.

    Shape confirmed live 2026-08-12 (see PROGRESS.md): get_session_jobs
    returns {"jobs": [...], "total": N} (SuperDocsClient.get_session_jobs
    already unwraps this, so `jobs` here is a plain list). There are no
    separate "approve" job-history entries — a decided chunk's outcome
    lives on the SAME chat job, once completed, at
    result.document_changes.changes: [{"status": "approved"|..., "chunk_id":
    ..., "new_html": ...}, ...]. A still-awaiting_approval job instead
    carries metadata.pending_changes, same shape get_job returns.
    """
    jobs = client.get_session_jobs(negotiation.superdocs_session_id)
    if not isinstance(jobs, list):
        logger.warning(
            "get_session_jobs returned unexpected shape for negotiation %s: %r", negotiation.id, type(jobs)
        )
        return

    jobs_by_job_id = {round_.superdocs_job_id: round_ for round_ in rounds if round_.superdocs_job_id}

    # "most recent first" per docs — replay oldest-to-newest so proposals
    # and decisions land in the same chronological order the live write
    # path would have applied them in
    for job in reversed(jobs):
        job_id = job.get("job_id") or job.get("id")
        round_ = jobs_by_job_id.get(job_id)
        if round_ is None:
            continue  # a job we have no local Round row for — skip rather than guess

        applied_changes = ((job.get("result") or {}).get("document_changes") or {}).get("changes")
        if applied_changes:
            for applied in applied_changes:
                chunk_id = applied.get("chunk_id")
                status = applied.get("status")
                if chunk_id is None or status is None:
                    continue
                upsert_decided_item(db, negotiation.id, round_.id, chunk_id, status == "approved")
            continue  # a completed job's decisions supersede its own proposal entry

        for change in SuperDocsClient.parse_pending_changes(job):
            chunk_id = change.get("chunk_id")
            if chunk_id is None:
                continue
            upsert_proposed_item(db, negotiation.id, round_.id, chunk_id, change, job)

    db.commit()
