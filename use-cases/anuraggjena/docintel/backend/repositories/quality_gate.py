from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.quality_gate import QualityGateConfig, QualityGateResult


class QualityGateConfigRepository(BaseRepository[QualityGateConfig]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, QualityGateConfig)

    async def get_by_workspace(self, workspace_id: UUID) -> Optional[QualityGateConfig]:
        result = await self.session.execute(
            select(QualityGateConfig).where(
                QualityGateConfig.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()


class QualityGateResultRepository(BaseRepository[QualityGateResult]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, QualityGateResult)

    async def get_by_run(self, workflow_run_id: UUID) -> Optional[QualityGateResult]:
        result = await self.session.execute(
            select(QualityGateResult).where(
                QualityGateResult.workflow_run_id == workflow_run_id
            )
        )
        return result.scalars().first()
