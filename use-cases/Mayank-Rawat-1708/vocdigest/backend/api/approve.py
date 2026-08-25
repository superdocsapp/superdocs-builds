"""
@file: backend/api/approve.py
@description: The human approval gate's HTTP surface. Lists pending items grouped by
    type, accepts per-item decisions, and resumes the run once nothing is left pending.
    Rejecting one item never affects the others — each carries its own status.
@flow: GET /runs/{id}/approval-items returns the queue -> the reviewer decides ->
    POST /runs/{id}/approve records approved_ids and rejected_ids -> if no items remain
    PENDING the run is resumed in the background from exactly where it paused.
@dependencies:
    - backend.models.ApprovalItem: the persisted decisions
    - backend.agents.graph.execute_run: resumption after the gate clears
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.agents.graph import execute_run
from backend.db.database import session_scope
from backend.models import ApprovalItem, ApprovalStatus, Run, utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs", tags=["approval"])


class ApprovalDecision(BaseModel):
    approved_ids: list[uuid.UUID] = Field(default_factory=list)
    rejected_ids: list[uuid.UUID] = Field(default_factory=list)
    notes: dict[str, str] = Field(
        default_factory=dict, description="item_id -> reviewer note"
    )


def _serialise_item(item: ApprovalItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "item_type": item.item_type.value,
        "status": item.status.value,
        "content": item.content,
        "reviewer_note": item.reviewer_note,
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "created_at": item.created_at.isoformat(),
    }


@router.get("/{run_id}/approval-items")
async def list_approval_items(run_id: uuid.UUID) -> dict[str, Any]:
    """Return the review queue, grouped by type so the UI can present it sensibly."""
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        items = list(
            (
                await session.execute(
                    select(ApprovalItem)
                    .where(ApprovalItem.run_id == run_id)
                    .order_by(ApprovalItem.created_at)
                )
            ).scalars()
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item.item_type.value, []).append(_serialise_item(item))

    pending = sum(1 for i in items if i.status == ApprovalStatus.PENDING)
    return {
        "run_id": str(run_id),
        "total": len(items),
        "pending": pending,
        "approved": sum(1 for i in items if i.status == ApprovalStatus.APPROVED),
        "rejected": sum(1 for i in items if i.status == ApprovalStatus.REJECTED),
        "gate_open": pending > 0,
        "groups": grouped,
    }


@router.post("/{run_id}/approve", status_code=202)
async def submit_decisions(
    run_id: uuid.UUID, payload: ApprovalDecision, background: BackgroundTasks
) -> dict[str, Any]:
    """Record decisions and resume the run once the queue is clear."""
    if not payload.approved_ids and not payload.rejected_ids:
        raise HTTPException(400, "Provide at least one approved_id or rejected_id")

    overlap = set(payload.approved_ids) & set(payload.rejected_ids)
    if overlap:
        raise HTTPException(
            400, f"Item(s) both approved and rejected: {[str(i) for i in overlap]}"
        )

    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")

        items = {
            item.id: item
            for item in (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_id)
                )
            ).scalars()
        }

        unknown = (set(payload.approved_ids) | set(payload.rejected_ids)) - set(items)
        if unknown:
            raise HTTPException(
                404, f"Unknown approval item(s): {[str(i) for i in unknown]}"
            )

        for item_id in payload.approved_ids:
            item = items[item_id]
            item.status = ApprovalStatus.APPROVED
            item.decided_at = utcnow()
            if str(item_id) in payload.notes:
                item.reviewer_note = payload.notes[str(item_id)]

        for item_id in payload.rejected_ids:
            item = items[item_id]
            item.status = ApprovalStatus.REJECTED
            item.decided_at = utcnow()
            if str(item_id) in payload.notes:
                item.reviewer_note = payload.notes[str(item_id)]

        remaining = sum(
            1 for i in items.values() if i.status == ApprovalStatus.PENDING
        )

    resumed = False
    if remaining == 0:
        # Gate cleared. Resume from the checkpoint — earlier stages are not re-run.
        background.add_task(_resume, run_id)
        resumed = True

    return {
        "run_id": str(run_id),
        "approved": len(payload.approved_ids),
        "rejected": len(payload.rejected_ids),
        "pending": remaining,
        "resumed": resumed,
    }


@router.post("/{run_id}/approve-all", status_code=202)
async def approve_all(
    run_id: uuid.UUID, background: BackgroundTasks
) -> dict[str, Any]:
    """Bulk-approve everything still pending, then resume."""
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        items = list(
            (
                await session.execute(
                    select(ApprovalItem).where(
                        ApprovalItem.run_id == run_id,
                        ApprovalItem.status == ApprovalStatus.PENDING,
                    )
                )
            ).scalars()
        )
        for item in items:
            item.status = ApprovalStatus.APPROVED
            item.decided_at = utcnow()
        count = len(items)

    if count:
        background.add_task(_resume, run_id)
    return {"run_id": str(run_id), "approved": count, "resumed": bool(count)}


async def _resume(run_uuid: uuid.UUID) -> None:
    try:
        await execute_run(run_uuid)
    except Exception:  # noqa: BLE001 - background boundary
        logger.exception("Resume after approval failed for run %s", run_uuid)
