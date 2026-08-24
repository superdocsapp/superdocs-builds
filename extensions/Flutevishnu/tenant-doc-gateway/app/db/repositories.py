"""Data-access layer.

Architectural Design for Tenant Isolation:
- Handlers can omit a `WHERE tenant_id = ?` clause. A repository mitigates this risk: every
  tenant-scoped method requires a `TenantContext` and injects the filter autonomously.
- Reads for a missing OR cross-tenant ID return None -> the API translates this to
  a 404 (never 403), preventing existence oracles and IDOR vulnerabilities.
- This layer serves as the single source of truth for auditing isolation correctness.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import TenantContext
from app.db.models import (
    ApiKey,
    ChangeStatus,
    Document,
    Job,
    ProposedChange,
    Tenant,
)


class TenantRepository:
    """Tenant + API key lookups used by auth (NOT tenant-scoped by design)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_tenant(self, name: str) -> Tenant:
        tenant = Tenant(name=name)
        self.session.add(tenant)
        await self.session.flush()
        return tenant

    async def add_api_key(
        self, tenant_id: uuid.UUID, key_hash: str, key_prefix: str, name: str
    ) -> ApiKey:
        api_key = ApiKey(
            tenant_id=tenant_id, key_hash=key_hash, key_prefix=key_prefix, name=name
        )
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def get_active_key_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
        return result.scalar_one_or_none()


class DocumentRepository:
    """All methods are scoped to ctx.tenant_id — no exceptions."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    async def create(self, **kwargs) -> Document:
        # tenant_id is set from context, never from client input.
        doc = Document(tenant_id=self.ctx.tenant_id, **kwargs)
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def get(self, document_id: uuid.UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == self.ctx.tenant_id,  # the isolation gate
            )
        )
        return result.scalar_one_or_none()

    async def list(self, limit: int = 100) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.tenant_id == self.ctx.tenant_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class JobRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    async def create(self, **kwargs) -> Job:
        job = Job(tenant_id=self.ctx.tenant_id, **kwargs)
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        result = await self.session.execute(
            select(Job).where(Job.id == job_id, Job.tenant_id == self.ctx.tenant_id)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Job).where(Job.tenant_id == self.ctx.tenant_id)
        )
        return int(result.scalar_one())


class ProposedChangeRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    async def create(self, **kwargs) -> ProposedChange:
        change = ProposedChange(tenant_id=self.ctx.tenant_id, **kwargs)
        self.session.add(change)
        await self.session.flush()
        return change

    async def get(self, change_id: uuid.UUID) -> ProposedChange | None:
        result = await self.session.execute(
            select(ProposedChange).where(
                ProposedChange.id == change_id,
                ProposedChange.tenant_id == self.ctx.tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_document(
        self, document_id: uuid.UUID, status: ChangeStatus | None = None
    ) -> list[ProposedChange]:
        stmt = select(ProposedChange).where(
            ProposedChange.document_id == document_id,
            ProposedChange.tenant_id == self.ctx.tenant_id,
        )
        if status is not None:
            stmt = stmt.where(ProposedChange.status == status)
        result = await self.session.execute(stmt.order_by(ProposedChange.created_at.asc()))
        return list(result.scalars().all())
