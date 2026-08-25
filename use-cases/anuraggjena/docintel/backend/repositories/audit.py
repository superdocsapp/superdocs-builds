from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.audit import AuditLog


class AuditRepository(BaseRepository[AuditLog]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, AuditLog)

    async def list_by_workspace(
        self,
        workspace_id: UUID,
        event_type: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditLog]:
        query = select(AuditLog).where(AuditLog.workspace_id == str(workspace_id))
        if event_type:
            query = query.where(AuditLog.event_type == event_type)
        result = await self.session.execute(
            query.order_by(AuditLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_resource(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 50
    ) -> List[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == resource_id
            )
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
