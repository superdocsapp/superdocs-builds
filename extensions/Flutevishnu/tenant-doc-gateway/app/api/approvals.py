"""Approval endpoint pair (human-in-the-loop).

- GET  proposed-changes           -> list the pending items
- POST proposed-changes/{id}/decision -> approve OR reject ONE item

Rejecting one item does NOT discard the others: each decision touches exactly one
ProposedChange row, so siblings remain pending and independently decidable.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_superdocs_client, require_idempotency_key
from app.api.schemas import DecisionRequest
from app.api.serializers import change_to_dict
from app.auth.context import TenantContext
from app.auth.dependencies import require_tenant
from app.db.models import ChangeStatus
from app.db.repositories import (
    DocumentRepository,
    JobRepository,
    ProposedChangeRepository,
)
from app.db.session import get_session
from app.integrations.superdocs.client import SuperDocsClient
from app.integrations.superdocs.exceptions import SuperDocsError
from app.logging import get_logger
from app.services.idempotency import run_idempotent

router = APIRouter(prefix="/v1/documents", tags=["approvals"])
_log = get_logger("approvals")


@router.get("/{document_id}/proposed-changes")
async def list_proposed_changes(
    document_id: uuid.UUID,
    only_pending: bool = True,
    ctx: TenantContext = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    docs = DocumentRepository(session, ctx)
    if await docs.get(document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    changes = ProposedChangeRepository(session, ctx)
    status_filter = ChangeStatus.PENDING if only_pending else None
    items = await changes.list_for_document(document_id, status=status_filter)
    return {"proposed_changes": [change_to_dict(c) for c in items]}


@router.post("/{document_id}/proposed-changes/{change_id}/decision")
async def decide_change(
    document_id: uuid.UUID,
    change_id: uuid.UUID,
    body: DecisionRequest,
    ctx: TenantContext = Depends(require_tenant),
    idempotency_key: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsClient = Depends(get_superdocs_client),
) -> JSONResponse:
    changes = ProposedChangeRepository(session, ctx)
    change = await changes.get(change_id)
    if change is None or change.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found.")
    if change.status != ChangeStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Change already {change.status.value}.",
        )

    jobs = JobRepository(session, ctx)
    job = await jobs.get(change.job_id)
    docs = DocumentRepository(session, ctx)
    document = await docs.get(document_id)

    request_payload = {
        "op": "decision",
        "change_id": str(change_id),
        "approved": body.approved,
        "feedback": body.feedback,
    }

    async def producer(s: AsyncSession):
        # Apply the decision locally first (this is our source of truth).
        change.status = ChangeStatus.APPROVED if body.approved else ChangeStatus.REJECTED
        change.feedback = body.feedback
        forward_error: str | None = None
        # Then forward it to SuperDocs. If forwarding fails we keep the local
        # decision and surface the error rather than crashing (graceful degrade).
        if (
            job
            and document
            and document.superdocs_session_id
            and job.superdocs_job_id
            and change.superdocs_change_ref
        ):
            try:
                await superdocs.decide_change(
                    session_id=document.superdocs_session_id,
                    job_id=job.superdocs_job_id,
                    change_id=change.superdocs_change_ref,
                    approved=body.approved,
                    feedback=body.feedback,
                )
            except SuperDocsError as exc:
                forward_error = str(exc)
                _log.warning("approval.forward_failed", change_id=str(change_id), error=str(exc))

        result = change_to_dict(change)
        if forward_error:
            result["forward_error"] = forward_error
        return status.HTTP_200_OK, result, None

    outcome = await run_idempotent(session, ctx, idempotency_key, request_payload, producer)
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)
