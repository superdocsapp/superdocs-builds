"""Propose (SuperDocs scoped edit), review (pending changes + amendment
letter + non-rate-content proof), and per-item decisions.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.backend.case_view import render_amendment_letter
from app.backend.lookups import get_case_or_404, get_run_or_404
from app.backend.schemas import DecisionsIn, PendingChangeOut, ReviewOut
from app.backend.store import store
from app.backend.superdocs_dependency import get_superdocs_http_client
from src.amendment_case import (
    Failure,
    apply_job_status,
    build_instruction,
    record_decision,
    touched_chunk_ids,
)
from src.case_state import CaseState, IllegalStateTransition
from src.integrations.superdocs_client import (
    SuperDocsError,
    approve_change as superdocs_approve_change,
    poll_job,
    propose_change,
    upload_document,
)

router = APIRouter()

_MAX_POLL_ATTEMPTS = 60
_POLL_INTERVAL_SECONDS = 3.0


@router.post("/runs/{run_id}/cases/{case_id}/propose", response_model=ReviewOut)
async def propose_case(
    run_id: str,
    case_id: str,
    idempotency_key: str,
    client: httpx.AsyncClient = Depends(get_superdocs_http_client),
):
    existing = store.get_idempotent_response(idempotency_key)
    if existing is not None:
        return existing

    run = get_run_or_404(run_id)
    case = get_case_or_404(run, case_id)

    if run.dry_run:
        raise HTTPException(
            status_code=409,
            detail={
                "what": f"case '{case_id}' belongs to a dry_run and cannot be proposed to SuperDocs",
                "likely_cause": "the intake run was submitted with dry_run=true",
                "next_action": "resubmit intake with dry_run=false to enable live SuperDocs proposals",
            },
        )

    if case.state != CaseState.ANALYSING:
        raise HTTPException(
            status_code=409,
            detail={
                "what": f"case '{case_id}' is in state '{case.state.value}', not ready to propose",
                "likely_cause": "the case is blocked, already proposed, or requires human review before a SuperDocs call can be made",
                "next_action": "check GET /runs/{run_id}/cases/{case_id} for blocking_reason and resolve it first",
            },
        )

    session_id = f"run-{run_id[:8]}-case-{case_id[:8]}"
    instruction = build_instruction(case)

    try:
        with open(case.analysis.document_id, "rb") as handle:
            content = handle.read()
        await upload_document(client, case.analysis.document_id.rsplit("/", 1)[-1], content, session_id)
        case.superdocs_session_id = session_id

        job_id = await propose_change(client, session_id, instruction)
        case.superdocs_job_id = job_id

        job_status = None
        for attempt in range(_MAX_POLL_ATTEMPTS):
            job_status = await poll_job(client, job_id)
            if job_status.status in ("awaiting_approval", "completed", "failed"):
                break
            if attempt < _MAX_POLL_ATTEMPTS - 1:
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        if job_status is None or job_status.status not in ("awaiting_approval", "completed", "failed"):
            raise SuperDocsError(
                what=f"SuperDocs job {job_id} did not reach a terminal state after {_MAX_POLL_ATTEMPTS} polls",
                likely_cause="the edit is taking longer than expected, or SuperDocs is under load",
                next_action="retry GET .../review shortly, or re-POST propose with a new idempotency_key if this one is abandoned",
            )

        apply_job_status(case, job_status)
    except SuperDocsError as exc:
        case.fail(Failure(**exc.to_dict()))
        raise HTTPException(status_code=502, detail=exc.to_dict()) from exc

    result = ReviewOut(
        case_id=case.case_id,
        state=case.state.value,
        pending_changes=[
            PendingChangeOut(
                change_id=c.change_id,
                chunk_id=c.chunk_id,
                old_html=c.old_html,
                new_html=c.new_html,
                ai_explanation=c.ai_explanation,
            )
            for c in case.pending_changes
        ],
        untouched_proof_note=(
            f"SuperDocs proposed changes to {len(touched_chunk_ids(case))} chunk(s) only; "
            f"all other sections of the document were not included in any proposed change."
        ),
        amendment_letter_markdown=render_amendment_letter(case),
        instruction_sent=instruction,
    )
    store.save_idempotent_response(idempotency_key, result)
    return result


@router.get("/runs/{run_id}/cases/{case_id}/review", response_model=ReviewOut)
async def get_review(run_id: str, case_id: str):
    run = get_run_or_404(run_id)
    case = get_case_or_404(run, case_id)

    def decision_for(change_id: str) -> bool | None:
        if change_id in case.approvals:
            return case.approvals[change_id]
        return None

    return ReviewOut(
        case_id=case.case_id,
        state=case.state.value,
        pending_changes=[
            PendingChangeOut(
                change_id=c.change_id,
                chunk_id=c.chunk_id,
                old_html=c.old_html,
                new_html=c.new_html,
                ai_explanation=c.ai_explanation,
                decision=decision_for(c.change_id),
            )
            for c in case.pending_changes
        ],
        untouched_proof_note=(
            f"SuperDocs proposed changes to {len(touched_chunk_ids(case))} chunk(s) only; "
            f"all other sections of the document were not included in any proposed change."
        ),
        amendment_letter_markdown=render_amendment_letter(case),
        instruction_sent=None,
    )


@router.post("/runs/{run_id}/cases/{case_id}/decisions", response_model=ReviewOut)
async def submit_decisions(
    run_id: str,
    case_id: str,
    payload: DecisionsIn,
    client: httpx.AsyncClient = Depends(get_superdocs_http_client),
):
    existing = store.get_idempotent_response(payload.idempotency_key)
    if existing is not None:
        return existing

    run = get_run_or_404(run_id)
    case = get_case_or_404(run, case_id)

    if case.state not in (CaseState.PROPOSED, CaseState.PARTIALLY_APPROVED):
        raise HTTPException(
            status_code=409,
            detail={
                "what": f"case '{case_id}' is in state '{case.state.value}', not open for decisions",
                "likely_cause": "decisions can only be submitted once SuperDocs has proposed changes and before all changes are resolved",
                "next_action": "check GET .../review for the case's current state",
            },
        )

    known_ids = {c.change_id for c in case.pending_changes}
    for decision in payload.decisions:
        if decision.change_id not in known_ids:
            raise HTTPException(
                status_code=422,
                detail={
                    "what": f"change_id '{decision.change_id}' is not a pending change on this case",
                    "likely_cause": "the frontend sent a stale or mistyped change_id",
                    "next_action": "re-fetch GET .../review for the current pending_changes list",
                },
            )

    try:
        for decision in payload.decisions:
            await superdocs_approve_change(
                client,
                session_id=case.superdocs_session_id,
                job_id=case.superdocs_job_id,
                change_id=decision.change_id,
                approved=decision.approved,
                feedback=decision.feedback,
            )
            record_decision(case, decision.change_id, decision.approved)
    except SuperDocsError as exc:
        case.fail(Failure(**exc.to_dict()))
        raise HTTPException(status_code=502, detail=exc.to_dict()) from exc
    except IllegalStateTransition as exc:
        raise HTTPException(status_code=409, detail=exc.to_dict()) from exc

    result = ReviewOut(
        case_id=case.case_id,
        state=case.state.value,
        pending_changes=[
            PendingChangeOut(
                change_id=c.change_id,
                chunk_id=c.chunk_id,
                old_html=c.old_html,
                new_html=c.new_html,
                ai_explanation=c.ai_explanation,
                decision=case.approvals.get(c.change_id),
            )
            for c in case.pending_changes
        ],
        untouched_proof_note=(
            f"SuperDocs proposed changes to {len(touched_chunk_ids(case))} chunk(s) only; "
            f"all other sections of the document were not included in any proposed change."
        ),
        amendment_letter_markdown=render_amendment_letter(case),
        instruction_sent=None,
    )
    store.save_idempotent_response(payload.idempotency_key, result)
    return result
