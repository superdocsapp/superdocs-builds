"""Liveness/readiness probes used by the container host."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    # Cheap process-alive check (no dependencies touched).
    return {"status": "ok"}


@router.get("/health/deep")
async def health_deep(session: AsyncSession = Depends(get_session)) -> dict:
    # Verifies the DB actually answers, not just that the process is up.
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
