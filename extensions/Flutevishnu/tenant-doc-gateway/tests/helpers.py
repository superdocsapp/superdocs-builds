"""Small DB helpers for assertions in tests."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db.models import Document, Job


async def count_documents(sessionmaker, tenant_id: str) -> int:
    async with sessionmaker() as s:
        r = await s.execute(
            select(func.count()).select_from(Document).where(
                Document.tenant_id == uuid.UUID(tenant_id)
            )
        )
        return int(r.scalar_one())


async def count_jobs(sessionmaker, tenant_id: str) -> int:
    async with sessionmaker() as s:
        r = await s.execute(
            select(func.count()).select_from(Job).where(Job.tenant_id == uuid.UUID(tenant_id))
        )
        return int(r.scalar_one())
