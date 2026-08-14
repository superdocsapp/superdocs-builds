"""Job polling endpoint — the primary result-delivery mechanism."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import job_to_dict
from app.auth.context import TenantContext
from app.auth.dependencies import require_tenant
from app.db.repositories import JobRepository
from app.db.session import get_session

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    jobs = JobRepository(session, ctx)
    job = await jobs.get(job_id)
    # Cross-tenant/missing -> 404, never leak another tenant's job existence.
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job_to_dict(job)
