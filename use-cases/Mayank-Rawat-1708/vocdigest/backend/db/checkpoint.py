"""
@file: backend/db/checkpoint.py
@description: Checkpoint persistence. This is the mechanism behind two of the required
    behaviours: surviving being stopped, and idempotency. Each node asks whether its
    stage already completed; if so it returns the cached result without re-calling any
    LLM. If not it runs, then writes its result before control moves on.
@flow: Node entry -> load_checkpoint(run_id, stage) -> if COMPLETE, return cached
    payload and skip the work entirely -> else do the work -> save_checkpoint() writes
    the payload plus status under runs.checkpoint_data -> next node repeats.
@dependencies:
    - sqlalchemy: SELECT ... FOR UPDATE row locking so concurrent runs cannot interleave
    - backend.models.Run: checkpoint_data / cost_report / decision_log JSONB columns
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Run, RunStatus, utcnow

logger = logging.getLogger(__name__)

STAGE_COMPLETE = "COMPLETE"
STAGE_RUNNING = "RUNNING"
STAGE_FAILED = "FAILED"
STAGE_SKIPPED = "SKIPPED"


@dataclass(slots=True)
class StageCheckpoint:
    """One stage's persisted outcome."""

    stage: str
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    attempts: int = 0

    @property
    def is_complete(self) -> bool:
        return self.status == STAGE_COMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageCheckpoint":
        return cls(
            stage=data["stage"],
            status=data.get("status", STAGE_RUNNING),
            result=data.get("result") or {},
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            attempts=int(data.get("attempts", 0)),
        )


async def _locked_run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    """Fetch a run with a row lock held for the rest of the transaction.

    SELECT ... FOR UPDATE is what keeps two workers touching the same run from
    clobbering each other's checkpoint writes. Runs with different ids never contend,
    so concurrent runs proceed in parallel.
    """
    stmt = select(Run).where(Run.id == run_id).with_for_update()
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        raise LookupError(f"Run {run_id} not found")
    return run


async def load_checkpoint(
    session: AsyncSession, run_id: uuid.UUID, stage: str
) -> StageCheckpoint | None:
    """Return the stored checkpoint for a stage, or None if it never ran."""
    run = await session.get(Run, run_id)
    if run is None:
        raise LookupError(f"Run {run_id} not found")
    raw = (run.checkpoint_data or {}).get("stages", {}).get(stage)
    return StageCheckpoint.from_dict(raw) if raw else None


async def is_stage_complete(
    session: AsyncSession, run_id: uuid.UUID, stage: str
) -> tuple[bool, dict[str, Any]]:
    """Convenience for the guard clause at the top of every node.

    Returns (True, cached_result) when the stage already finished — the node returns
    immediately and no LLM call is made. This is what makes a rerun free and a resumed
    run pick up mid-pipeline instead of starting over.
    """
    checkpoint = await load_checkpoint(session, run_id, stage)
    if checkpoint and checkpoint.is_complete:
        return True, checkpoint.result
    return False, {}


async def claim_stage(
    session: AsyncSession, run_id: uuid.UUID, stage: str, status: RunStatus
) -> tuple[bool, dict[str, Any], int]:
    """Atomically decide whether to run a stage, and claim it if so.

    This replaces a check-then-act pair that had a real race: two workers on the same
    run could both read "not complete" before either wrote "running", and both would
    then execute the stage — duplicating LLM spend and SuperDocs operations.

    The row lock is taken FIRST and held for the whole decision, so the read and the
    claim are one indivisible step. Returns (already_complete, cached_result, attempt).
    When already_complete is True the caller must not do the work.
    """
    run = await _locked_run(session, run_id)  # lock held for the rest of the txn

    stages = dict((run.checkpoint_data or {}).get("stages") or {})
    existing = stages.get(stage)
    if existing and existing.get("status") in {STAGE_COMPLETE, STAGE_SKIPPED}:
        return True, existing.get("result") or {}, int(existing.get("attempts", 1))

    attempts = int((existing or {}).get("attempts", 0)) + 1
    data = dict(run.checkpoint_data or {})
    stages[stage] = StageCheckpoint(
        stage=stage,
        status=STAGE_RUNNING,
        result=(existing or {}).get("result") or {},
        started_at=utcnow().isoformat(),
        attempts=attempts,
    ).to_dict()
    data["stages"] = stages

    run.checkpoint_data = data
    run.status = status
    run.current_stage = stage
    run.stage_started_at = utcnow()
    run.updated_at = utcnow()
    await session.flush()
    return False, {}, attempts


async def mark_stage_running(
    session: AsyncSession, run_id: uuid.UUID, stage: str, status: RunStatus
) -> int:
    """Record that a stage started; returns the attempt number (1-based).

    Retained for direct use in tests. Production code paths go through claim_stage(),
    which folds this together with the completeness check under one lock.
    """
    run = await _locked_run(session, run_id)
    data = dict(run.checkpoint_data or {})
    stages = dict(data.get("stages") or {})
    prior = stages.get(stage) or {}
    attempts = int(prior.get("attempts", 0)) + 1

    stages[stage] = StageCheckpoint(
        stage=stage,
        status=STAGE_RUNNING,
        result=prior.get("result") or {},
        started_at=utcnow().isoformat(),
        attempts=attempts,
    ).to_dict()
    data["stages"] = stages

    run.checkpoint_data = data
    run.status = status
    run.current_stage = stage
    run.stage_started_at = utcnow()
    run.updated_at = utcnow()
    await session.flush()
    return attempts


async def save_checkpoint(
    session: AsyncSession,
    run_id: uuid.UUID,
    stage: str,
    result: dict[str, Any],
    *,
    status: str = STAGE_COMPLETE,
    error: str | None = None,
) -> None:
    """Persist a stage outcome. Called before control moves to the next node."""
    run = await _locked_run(session, run_id)
    data = dict(run.checkpoint_data or {})
    stages = dict(data.get("stages") or {})
    prior = stages.get(stage) or {}

    stages[stage] = StageCheckpoint(
        stage=stage,
        status=status,
        result=result,
        started_at=prior.get("started_at"),
        completed_at=utcnow().isoformat(),
        error=error,
        attempts=int(prior.get("attempts", 1)),
    ).to_dict()
    data["stages"] = stages

    run.checkpoint_data = data
    run.updated_at = utcnow()
    await session.flush()
    logger.info("Checkpoint saved: run=%s stage=%s status=%s", run_id, stage, status)


async def record_stage_cost(
    session: AsyncSession,
    run_id: uuid.UUID,
    stage: str,
    *,
    started_at: datetime,
    completed_at: datetime,
    groq_usage: dict[str, Any] | None = None,
    superdocs_operations: int = 0,
    notes: str | None = None,
) -> None:
    """Append one stage's timing and spend to the run's cost report."""
    run = await _locked_run(session, run_id)
    report = dict(run.cost_report or {})
    stages = dict(report.get("stages") or {})
    usage = groq_usage or {}

    stages[stage] = {
        "stage": stage,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        "groq_tokens_used": int(usage.get("total_tokens", 0)),
        "groq_prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "groq_completion_tokens": int(usage.get("completion_tokens", 0)),
        "groq_calls": int(usage.get("calls", 0)),
        "estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
        "superdocs_operations": superdocs_operations,
        "notes": notes,
    }
    report["stages"] = stages
    report["totals"] = {
        "groq_tokens_used": sum(s.get("groq_tokens_used", 0) for s in stages.values()),
        "estimated_cost_usd": round(
            sum(float(s.get("estimated_cost_usd", 0.0)) for s in stages.values()), 6
        ),
        "superdocs_operations": sum(
            s.get("superdocs_operations", 0) for s in stages.values()
        ),
        "duration_seconds": round(
            sum(float(s.get("duration_seconds", 0.0)) for s in stages.values()), 3
        ),
    }
    run.cost_report = report
    run.updated_at = utcnow()
    await session.flush()


async def append_decision(
    session: AsyncSession,
    run_id: uuid.UUID,
    stage: str,
    decision: str,
    reason: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log a branching decision so the UI can show why the agent did what it did.

    This is the visible-reasoning surface: every skip, every fallback, every "evidence
    too thin to claim this" lands here and is rendered in the run timeline.
    """
    run = await _locked_run(session, run_id)
    log = list(run.decision_log or [])
    log.append(
        {
            "at": utcnow().isoformat(),
            "stage": stage,
            "decision": decision,
            "reason": reason,
            "metadata": metadata or {},
        }
    )
    run.decision_log = log
    run.updated_at = utcnow()
    await session.flush()


async def set_run_status(
    session: AsyncSession,
    run_id: uuid.UUID,
    status: RunStatus,
    *,
    error_message: str | None = None,
) -> None:
    run = await _locked_run(session, run_id)
    run.status = status
    if error_message is not None:
        run.error_message = error_message
    run.updated_at = utcnow()
    await session.flush()
