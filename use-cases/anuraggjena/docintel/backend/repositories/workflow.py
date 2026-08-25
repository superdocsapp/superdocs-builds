from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from backend.repositories.base import BaseRepository
from backend.models.workflow import WorkflowRun, Workflow, WorkflowStage
from backend.models.evidence import Evidence
from backend.models.document import Document


class WorkflowRepository(BaseRepository[Workflow]):
    """Repository for Workflow entity"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Workflow)

    async def get_by_slug(self, slug: str) -> Optional[Workflow]:
        """Get workflow by slug"""
        result = await self.session.execute(
            select(self.model).where(self.model.slug == slug)
        )
        return result.scalar_one_or_none()


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    """Repository for WorkflowRun entity"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, WorkflowRun)

    async def list_by_workspace(
        self,
        workspace_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowRun]:
        """List workflow runs by workspace"""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.workspace_id == workspace_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_workflow(
        self,
        workflow_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowRun]:
        """List workflow runs by workflow"""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.workflow_id == workflow_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_recent_successful_runs(
        self,
        workspace_id: UUID,
        limit: int = 10
    ) -> List[WorkflowRun]:
        """Get recent successful runs in workspace for focused update detection"""
        result = await self.session.execute(
            select(self.model)
            .where(
                self.model.workspace_id == workspace_id,
                self.model.status == "completed"
            )
            .order_by(self.model.completed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_status(self, statuses: list) -> List[WorkflowRun]:
        """Get all runs matching any of the given statuses."""
        result = await self.session.execute(
            select(self.model).where(self.model.status.in_(statuses))
        )
        return list(result.scalars().all())

    async def get_document_for_run(self, run_id: UUID) -> Optional[Document]:
        """Get the primary document for a workflow run via Evidence"""
        # Get first evidence record for this run (they all reference same document)
        result = await self.session.execute(
            select(Evidence.document_id)
            .where(Evidence.workflow_run_id == run_id)
            .limit(1)
        )
        document_id = result.scalar_one_or_none()

        if not document_id:
            return None

        # Get document
        doc_result = await self.session.execute(
            select(Document)
            .where(Document.id == document_id)
        )
        return doc_result.scalar_one_or_none()


class WorkflowStageRepository(BaseRepository[WorkflowStage]):
    """Repository for WorkflowStage entity"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, WorkflowStage)

    async def list_by_run(self, run_id: UUID) -> List[WorkflowStage]:
        """List all stages for a workflow run"""
        result = await self.session.execute(
            select(WorkflowStage)
            .where(WorkflowStage.run_id == run_id)
            .order_by(WorkflowStage.created_at)
        )
        return list(result.scalars().all())

    async def get_by_run_and_name(self, run_id: UUID, stage_name: str) -> Optional[WorkflowStage]:
        """Get stage by run ID and name"""
        result = await self.session.execute(
            select(WorkflowStage)
            .where(WorkflowStage.run_id == run_id)
            .where(WorkflowStage.stage_name == stage_name)
        )
        return result.scalar_one_or_none()
