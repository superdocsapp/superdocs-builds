from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.export import Export


class ExportRepository(BaseRepository[Export]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Export)

    async def list_by_workspace(self, workspace_id: UUID, limit: int = 100) -> List[Export]:
        """List exports for a workspace"""
        result = await self.session.execute(
            select(Export)
            .where(Export.workspace_id == str(workspace_id))
            .order_by(Export.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_workflow_run(self, workflow_run_id: UUID) -> Optional[Export]:
        """Get export for a workflow run"""
        result = await self.session.execute(
            select(Export)
            .where(Export.workflow_run_id == str(workflow_run_id))
            .order_by(Export.created_at.desc())
        )
        return result.scalar_one_or_none()
