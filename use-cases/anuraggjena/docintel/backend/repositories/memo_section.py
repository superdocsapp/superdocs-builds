from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memo_section import MemoSection
from backend.repositories.base import BaseRepository


class MemoSectionRepository(BaseRepository[MemoSection]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, MemoSection)

    async def list_by_run(self, workflow_run_id: UUID) -> List[MemoSection]:
        result = await self.session.execute(
            select(MemoSection)
            .where(MemoSection.workflow_run_id == workflow_run_id)
            .order_by(MemoSection.section_order)
        )
        return list(result.scalars().all())

    async def get_by_run_and_type(
        self,
        workflow_run_id: UUID,
        section_type: str,
    ) -> Optional[MemoSection]:
        result = await self.session.execute(
            select(MemoSection).where(
                MemoSection.workflow_run_id == workflow_run_id,
                MemoSection.section_type == section_type,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, workflow_run_id: UUID, status: str) -> List[MemoSection]:
        result = await self.session.execute(
            select(MemoSection)
            .where(
                MemoSection.workflow_run_id == workflow_run_id,
                MemoSection.status == status,
            )
            .order_by(MemoSection.section_order)
        )
        return list(result.scalars().all())
