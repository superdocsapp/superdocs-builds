from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.workspace import Workspace


class WorkspaceRepository(BaseRepository[Workspace]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Workspace)

    async def list_by_owner(self, owner_user_id, limit: int = 100) -> List[Workspace]:
        """List workspaces for a specific owner"""
        result = await self.session.execute(
            select(Workspace)
            .where(Workspace.owner_user_id == owner_user_id)
            .where(Workspace.deleted_at.is_(None))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, id) -> Workspace | None:
        """Get workspace by ID, excluding soft-deleted"""
        result = await self.session.execute(
            select(Workspace)
            .where(Workspace.id == id)
            .where(Workspace.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()
