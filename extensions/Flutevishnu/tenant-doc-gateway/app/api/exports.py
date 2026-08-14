"""Export endpoint: enqueue an export job (exports are free ops upstream)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_idempotency_key
from app.api.schemas import ExportRequest
from app.auth.context import TenantContext
from app.auth.dependencies import require_tenant
from app.db.models import DocumentStatus, JobType
from app.db.repositories import DocumentRepository, JobRepository
from app.db.session import get_session
from app.services.idempotency import run_idempotent
from app.services.queue import JobQueue, get_job_queue

router = APIRouter(prefix="/v1/documents", tags=["exports"])


@router.post("/{document_id}/export", status_code=status.HTTP_202_ACCEPTED)
async def create_export(
    document_id: uuid.UUID,
    body: ExportRequest,
    ctx: TenantContext = Depends(require_tenant),
    idempotency_key: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(get_session),
    queue: JobQueue = Depends(get_job_queue),
) -> JSONResponse:
    docs = DocumentRepository(session, ctx)
    document = await docs.get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if document.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Document is not ready to export."
        )

    request_payload = {"op": "export", "document_id": str(document_id), "format": body.format}

    async def producer(s: AsyncSession):
        jobs = JobRepository(s, ctx)
        job = await jobs.create(
            type=JobType.EXPORT,
            document_id=document.id,
            webhook_url=str(body.webhook_url) if body.webhook_url else None,
            checkpoint={"format": body.format},
        )
        return (
            status.HTTP_202_ACCEPTED,
            {"job_id": str(job.id), "status": job.status.value},
            job.id,
        )

    outcome = await run_idempotent(session, ctx, idempotency_key, request_payload, producer)
    if not outcome.replayed:
        await queue.enqueue("process_job", outcome.job_id)  # type: ignore[arg-type]
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)
