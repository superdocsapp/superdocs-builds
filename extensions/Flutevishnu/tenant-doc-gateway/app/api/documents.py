"""Document endpoints: upload (streamed), fetch, list."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_idempotency_key
from app.api.serializers import document_to_dict
from app.auth.context import TenantContext
from app.auth.dependencies import require_tenant
from app.config import Settings, get_settings
from app.db.models import DocumentStatus, JobType
from app.db.repositories import DocumentRepository, JobRepository
from app.db.session import get_session
from app.services.idempotency import run_idempotent
from app.services.queue import JobQueue, get_job_queue
from app.services.storage import stream_upload_to_disk

router = APIRouter(prefix="/v1/documents", tags=["documents"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_tenant),
    idempotency_key: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    queue: JobQueue = Depends(get_job_queue),
) -> JSONResponse:
    # Stream to disk in chunks BEFORE any DB work. The file is never fully loaded
    # into memory, and the size cap is enforced mid-stream (see storage.py).
    stored = await stream_upload_to_disk(
        file,
        upload_dir=settings.upload_dir,
        tenant_id=ctx.tenant_id,
        chunk_size=settings.upload_chunk_size,
        max_bytes=settings.max_upload_bytes,
    )

    request_payload = {
        "op": "upload",
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
    }

    async def producer(s: AsyncSession):
        docs = DocumentRepository(s, ctx)
        jobs = JobRepository(s, ctx)
        document = await docs.create(
            filename=stored.filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            storage_path=stored.path,
            status=DocumentStatus.UPLOADING,
        )
        job = await jobs.create(type=JobType.UPLOAD, document_id=document.id)
        body = {
            "document": document_to_dict(document),
            "job": {"job_id": str(job.id), "status": job.status.value},
        }
        return status.HTTP_202_ACCEPTED, body, job.id

    outcome = await run_idempotent(session, ctx, idempotency_key, request_payload, producer)

    if outcome.replayed:
        # Duplicate request: discard the freshly streamed file and replay.
        from app.services.storage import _safe_unlink

        _safe_unlink(stored.path)
    else:
        await queue.enqueue("process_job", outcome.job_id)  # type: ignore[arg-type]

    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    docs = DocumentRepository(session, ctx)
    document = await docs.get(document_id)
    # 404 (not 403) on a cross-tenant/missing id: no existence oracle.
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document_to_dict(document)


@router.get("")
async def list_documents(
    ctx: TenantContext = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    docs = DocumentRepository(session, ctx)
    return {"documents": [document_to_dict(d) for d in await docs.list()]}
