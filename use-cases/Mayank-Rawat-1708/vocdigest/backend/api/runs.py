"""
@file: backend/api/runs.py
@description: Run lifecycle endpoints: create, list, inspect, resume, cost report,
    export download, and a Server-Sent Events stream for live stage updates. Run
    execution happens in a background task so the HTTP request returns immediately —
    a digest takes minutes, which is far longer than any sensible request timeout.
@flow: POST /runs writes the row and schedules execution -> the client polls GET
    /runs/{id} or subscribes to GET /runs/{id}/events -> when the graph pauses at the
    gate the status becomes AWAITING_APPROVAL -> POST /runs/{id}/resume continues it
    after decisions are recorded.
@dependencies:
    - fastapi: routing, background tasks, streaming responses
    - backend.agents.graph: create_run / execute_run
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.agents.graph import NODE_SEQUENCE, create_run, execute_run, load_state
from backend.agents.state import STAGES, state_summary
from backend.config import settings
from backend.db.database import session_scope
from backend.models import ApprovalItem, ApprovalStatus, Run, RunStatus, Theme, utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs", tags=["runs"])

# Stages an operator may not skip. Derived from the nodes' own declared dependencies
# rather than listed by hand, so the API and the graph cannot disagree about which
# stages other stages are built from — plus human_gate, which is protected because
# skipping it would publish unreviewed content, not because anything reads its output.
PROTECTED_STAGES: frozenset[str] = frozenset(
    {"human_gate"}
    | {
        required
        for _name, node_cls in NODE_SEQUENCE
        for required in getattr(node_cls, "requires", ())
    }
)


class CreateRunRequest(BaseModel):
    conversations_path: str = Field(..., description="Path to CSV/JSON/TXT conversations")
    last_digest_path: str | None = Field(None, description="Path to prior digest")
    quarter_label: str = "Q3 2026"
    prior_quarter_label: str = "Q2 2026"


class RunSummary(BaseModel):
    id: str
    status: str
    current_stage: str | None
    created_at: str
    updated_at: str
    quarter_label: str
    error_message: str | None
    export_available: bool
    pending_approvals: int


def _serialise_run(run: Run, pending: int = 0) -> RunSummary:
    return RunSummary(
        id=str(run.id),
        status=run.status.value,
        current_stage=run.current_stage,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        quarter_label=run.quarter_label,
        error_message=run.error_message,
        export_available=bool(run.export_path and Path(run.export_path).is_file()),
        pending_approvals=pending,
    )


async def _execute_in_background(run_uuid: uuid.UUID) -> None:
    """Run the graph outside the request cycle, never letting an error escape."""
    try:
        await execute_run(run_uuid)
    except Exception:  # noqa: BLE001 - background boundary
        logger.exception("Background execution failed for run %s", run_uuid)


@router.post("", status_code=202)
async def start_run(payload: CreateRunRequest, background: BackgroundTasks) -> dict[str, Any]:
    """Create a run and begin executing it in the background."""
    source = Path(payload.conversations_path)
    if not source.is_file():
        raise HTTPException(400, f"Conversations file not found: {source}")
    if payload.last_digest_path and not Path(payload.last_digest_path).is_file():
        raise HTTPException(400, f"Prior digest not found: {payload.last_digest_path}")

    run_uuid = await create_run(
        str(source),
        payload.last_digest_path,
        quarter_label=payload.quarter_label,
        prior_quarter_label=payload.prior_quarter_label,
    )
    background.add_task(_execute_in_background, run_uuid)
    return {"run_id": str(run_uuid), "status": RunStatus.PENDING.value}


@router.post("/upload", status_code=202)
async def start_run_from_upload(
    background: BackgroundTasks,
    conversations: UploadFile = File(...),
    last_digest: UploadFile | None = File(None),
    quarter_label: str = Form("Q3 2026"),
) -> dict[str, Any]:
    """Create a run from uploaded files.

    Files are streamed to disk in chunks rather than read into memory, so a large export
    never has to fit in the process heap.
    """
    upload_dir = Path(settings.data_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]

    async def _save(upload: UploadFile) -> Path:
        target = upload_dir / f"{token}-{Path(upload.filename or 'upload').name}"
        with target.open("wb") as fh:
            while chunk := await upload.read(1024 * 1024):
                fh.write(chunk)
        return target

    conv_path = await _save(conversations)
    digest_path = await _save(last_digest) if last_digest else None

    run_uuid = await create_run(
        str(conv_path), str(digest_path) if digest_path else None, quarter_label=quarter_label
    )
    background.add_task(_execute_in_background, run_uuid)
    return {"run_id": str(run_uuid), "status": RunStatus.PENDING.value}


@router.get("")
async def list_runs(limit: int = 50) -> list[RunSummary]:
    async with session_scope() as session:
        runs = list(
            (
                await session.execute(
                    select(Run).order_by(Run.created_at.desc()).limit(limit)
                )
            ).scalars()
        )
        out = []
        for run in runs:
            pending = len(
                list(
                    (
                        await session.execute(
                            select(ApprovalItem).where(
                                ApprovalItem.run_id == run.id,
                                ApprovalItem.status == ApprovalStatus.PENDING,
                            )
                        )
                    ).scalars()
                )
            )
            out.append(_serialise_run(run, pending))
        return out


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID) -> dict[str, Any]:
    """Full run detail: status, per-stage timeline, decision log, and state summary."""
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        pending = len(
            list(
                (
                    await session.execute(
                        select(ApprovalItem).where(
                            ApprovalItem.run_id == run_id,
                            ApprovalItem.status == ApprovalStatus.PENDING,
                        )
                    )
                ).scalars()
            )
        )
        stages_raw = (run.checkpoint_data or {}).get("stages", {})
        cost_stages = (run.cost_report or {}).get("stages", {})
        summary = _serialise_run(run, pending)
        decision_log = list(run.decision_log or [])

    # Render the full stage list, including ones that have not started, so the UI can
    # draw the whole timeline immediately rather than growing it as work progresses.
    timeline = []
    for stage in STAGES:
        record = stages_raw.get(stage)
        cost = cost_stages.get(stage, {})
        timeline.append(
            {
                "stage": stage,
                "status": (record or {}).get("status", "PENDING"),
                "started_at": (record or {}).get("started_at"),
                "completed_at": (record or {}).get("completed_at"),
                "attempts": (record or {}).get("attempts", 0),
                "error": (record or {}).get("error"),
                "duration_seconds": cost.get("duration_seconds"),
                "groq_tokens_used": cost.get("groq_tokens_used", 0),
                "estimated_cost_usd": cost.get("estimated_cost_usd", 0.0),
                "superdocs_operations": cost.get("superdocs_operations", 0),
            }
        )

    state = await load_state(run_id)
    return {
        **summary.model_dump(),
        "timeline": timeline,
        "decision_log": decision_log,
        "summary": state_summary(state),
    }


@router.post("/{run_id}/resume", status_code=202)
async def resume_run(run_id: uuid.UUID, background: BackgroundTasks) -> dict[str, Any]:
    """Continue a paused, failed, or awaiting-approval run from its checkpoint."""
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        if run.status == RunStatus.COMPLETE:
            raise HTTPException(409, "Run already complete")
        status = run.status.value

    background.add_task(_execute_in_background, run_id)
    return {"run_id": str(run_id), "resumed_from": status}


class StageAction(BaseModel):
    stage: str = Field(..., description="Stage name, e.g. 'compare'")


@router.post("/{run_id}/stages/retry", status_code=202)
async def retry_stage(
    run_id: uuid.UUID, payload: StageAction, background: BackgroundTasks
) -> dict[str, Any]:
    """Clear one stage's checkpoint so it re-runs, then resume.

    Only that stage is invalidated — every other completed stage keeps its checkpoint
    and is still skipped, so a retry costs one stage rather than a whole pipeline.
    """
    if payload.stage not in STAGES:
        raise HTTPException(400, f"Unknown stage: {payload.stage}")

    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        data = dict(run.checkpoint_data or {})
        stages = dict(data.get("stages") or {})
        if payload.stage not in stages:
            raise HTTPException(409, f"Stage {payload.stage} has not run yet")
        stages.pop(payload.stage)
        # Stages after this one are invalidated too: their results were computed from
        # output this stage is about to replace, so keeping them would mix generations.
        idx = STAGES.index(payload.stage)
        for later in STAGES[idx + 1:]:
            stages.pop(later, None)
        data["stages"] = stages
        run.checkpoint_data = data
        run.error_message = None
        run.status = RunStatus.PENDING

    background.add_task(_execute_in_background, run_id)
    return {"run_id": str(run_id), "retrying": payload.stage,
            "invalidated": STAGES[STAGES.index(payload.stage):]}


@router.post("/{run_id}/stages/skip", status_code=202)
async def skip_stage(
    run_id: uuid.UUID, payload: StageAction, background: BackgroundTasks
) -> dict[str, Any]:
    """Mark a stage SKIPPED so the pipeline moves past it, then resume.

    Only stages nothing downstream is built from can be skipped. The protected set is
    every stage that another stage's output is assembled from: skipping one of those does
    not shorten the pipeline, it feeds the rest of it nothing — which is exactly how a
    413 in extract ended up as an approval gate holding zero items and reporting itself
    as a normal waiting state. Skipping the gate is refused for a different reason: it
    would publish unreviewed content, which is the one thing this system exists to
    prevent.
    """
    if payload.stage not in STAGES:
        raise HTTPException(400, f"Unknown stage: {payload.stage}")
    if payload.stage in PROTECTED_STAGES:
        raise HTTPException(
            409,
            f"Stage '{payload.stage}' cannot be skipped. Every later stage is built from "
            f"its output, so skipping it would leave the rest of the run analysing "
            f"nothing (or, for the approval gate, publishing unreviewed content). "
            f"Retry it instead: POST /runs/{run_id}/stages/retry.",
        )

    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        data = dict(run.checkpoint_data or {})
        stages = dict(data.get("stages") or {})
        stages[payload.stage] = {
            "stage": payload.stage,
            "status": "SKIPPED",
            "result": {"state_delta": {}},
            "started_at": None,
            "completed_at": utcnow().isoformat(),
            "error": None,
            "attempts": int((stages.get(payload.stage) or {}).get("attempts", 0)),
        }
        data["stages"] = stages
        run.checkpoint_data = data
        run.error_message = None
        run.status = RunStatus.PENDING
        log = list(run.decision_log or [])
        log.append({
            "at": utcnow().isoformat(),
            "stage": payload.stage,
            "decision": "SKIPPED_BY_OPERATOR",
            "reason": "An operator skipped this stage manually from the run view.",
            "metadata": {},
        })
        run.decision_log = log

    background.add_task(_execute_in_background, run_id)
    return {"run_id": str(run_id), "skipped": payload.stage}


@router.post("/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: uuid.UUID) -> dict[str, Any]:
    """Cancel a run.

    Takes effect at the next stage boundary — every node checks for cancellation on
    entry. It cannot interrupt an in-flight provider call, so a stage already waiting on
    an HTTP response will finish that call first. That is why MAX_TOKENS_PER_RUN exists
    as well: a bound on spend should not depend on somebody watching.
    """
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        if run.status in (RunStatus.COMPLETE, RunStatus.FAILED, RunStatus.CANCELLED):
            raise HTTPException(
                409, f"Run is already {run.status.value} and cannot be cancelled"
            )

        previous = run.status.value
        run.status = RunStatus.CANCELLED
        run.error_message = "Cancelled by operator"
        log = list(run.decision_log or [])
        log.append({
            "at": utcnow().isoformat(),
            "stage": run.current_stage or "unknown",
            "decision": "CANCEL_REQUESTED",
            "reason": "An operator cancelled this run. It will stop at the next stage "
                      "boundary; any provider call already in flight will finish first.",
            "metadata": {"previous_status": previous},
        })
        run.decision_log = log
        tokens = int(((run.cost_report or {}).get("totals") or {}).get("groq_tokens_used", 0))

    return {
        "run_id": str(run_id),
        "cancelled_from": previous,
        "tokens_spent": tokens,
        "note": "Completed stages are preserved. The run is not resumable once cancelled.",
    }


@router.get("/active/summary")
async def active_runs() -> dict[str, Any]:
    """Runs currently consuming budget, and what they have spent.

    Exists because every run on one API key competes for the same provider allowance, so
    a forgotten run can starve a new one with no visible cause. This makes that visible
    and gives something to cancel.
    """
    working = {
        RunStatus.PENDING, RunStatus.INGESTING, RunStatus.CLASSIFYING,
        RunStatus.EXTRACTING, RunStatus.THEMING, RunStatus.ANONYMIZING,
        RunStatus.COMPARING, RunStatus.DRAFTING, RunStatus.UPLOADING,
    }
    async with session_scope() as session:
        runs = list(
            (await session.execute(select(Run).where(Run.status.in_(working)))).scalars()
        )
        active = [
            {
                "run_id": str(r.id),
                "status": r.status.value,
                "current_stage": r.current_stage,
                "started_at": r.created_at.isoformat(),
                "tokens_spent": int(
                    ((r.cost_report or {}).get("totals") or {}).get("groq_tokens_used", 0)
                ),
            }
            for r in runs
        ]

    total = sum(a["tokens_spent"] for a in active)
    return {
        "active_count": len(active),
        "total_tokens_spent_by_active_runs": total,
        "runs": active,
        "note": (
            "All runs share one provider allowance. Cancel anything unwanted with "
            "POST /runs/{id}/cancel before starting new work."
        ),
    }


@router.get("/{run_id}/cost")
async def get_cost(run_id: uuid.UUID) -> dict[str, Any]:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        report = run.cost_report or {}
    return {
        "run_id": str(run_id),
        "stages": list((report.get("stages") or {}).values()),
        "totals": report.get("totals", {}),
    }


@router.get("/{run_id}/themes")
async def get_themes(run_id: uuid.UUID) -> list[dict[str, Any]]:
    async with session_scope() as session:
        themes = list(
            (
                await session.execute(
                    select(Theme)
                    .where(Theme.run_id == run_id)
                    .order_by(Theme.volume_count.desc())
                )
            ).scalars()
        )
        return [
            {
                "id": str(t.id),
                "name": t.name,
                "description": t.description,
                "volume_count": t.volume_count,
                "volume_share": t.volume_share,
                "volume_trend": t.volume_trend.value,
                "growth_rate": t.growth_rate,
                "prior_quarter_count": t.prior_quarter_count,
                "prior_theme_name": t.prior_theme_name,
                "representative_quotes": t.representative_quotes,
                "evidence_refs": t.evidence_refs,
                "confidence_note": t.confidence_note,
            }
            for t in themes
        ]


@router.get("/{run_id}/export")
async def download_export(run_id: uuid.UUID) -> FileResponse:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        export_path = run.export_path

    if not export_path or not Path(export_path).is_file():
        raise HTTPException(
            409, "No export available yet. The run must reach COMPLETE first."
        )
    return FileResponse(
        export_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=Path(export_path).name,
    )


@router.get("/{run_id}/events")
async def stream_events(run_id: uuid.UUID) -> StreamingResponse:
    """Server-Sent Events stream of stage transitions.

    Polls the run row and emits only on change, so an idle run costs one small query
    per interval rather than a constant stream of identical frames.
    """

    async def event_source() -> AsyncIterator[str]:
        last_signature: str | None = None
        terminal = {RunStatus.COMPLETE, RunStatus.FAILED}
        for _ in range(600):  # ~30 minutes at 3s, then the client reconnects
            async with session_scope() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    yield f"event: error\ndata: {json.dumps({'error': 'run not found'})}\n\n"
                    return
                stages = (run.checkpoint_data or {}).get("stages", {})
                payload = {
                    "run_id": str(run_id),
                    "status": run.status.value,
                    "current_stage": run.current_stage,
                    "stages": {k: v.get("status") for k, v in stages.items()},
                    "updated_at": run.updated_at.isoformat(),
                }
                is_terminal = run.status in terminal

            signature = json.dumps(payload, sort_keys=True)
            if signature != last_signature:
                last_signature = signature
                yield f"event: stage\ndata: {signature}\n\n"

            if is_terminal:
                yield f"event: done\ndata: {json.dumps({'status': payload['status']})}\n\n"
                return
            await asyncio.sleep(3)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )