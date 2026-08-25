from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.review import Review
from backend.models.claim import Claim


class ReviewRepository(BaseRepository[Review]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Review)

    async def list_by_workspace(self, workspace_id: UUID, limit: int = 100) -> List[Review]:
        """List reviews for a workspace"""
        result = await self.session.execute(
            select(Review)
            .where(Review.workspace_id == workspace_id)
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_workflow_run(self, workflow_run_id: UUID) -> Optional[Review]:
        """Get review for a workflow run"""
        result = await self.session.execute(
            select(Review)
            .where(Review.workflow_run_id == workflow_run_id)
            .order_by(Review.created_at.desc())
        )
        return result.scalars().first()

    async def list_by_workflow_run(self, workflow_run_id: UUID) -> List[Review]:
        """List reviews for a workflow run"""
        result = await self.session.execute(
            select(Review)
            .where(Review.workflow_run_id == workflow_run_id)
            .order_by(Review.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_run(self, workflow_run_id: UUID) -> List[Review]:
        """List reviews for a workflow run (alias for list_by_workflow_run)"""
        return await self.list_by_workflow_run(workflow_run_id)


class ClaimRepository(BaseRepository[Claim]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Claim)

    async def list_by_workflow_run(self, workflow_run_id: UUID) -> List[Claim]:
        """List claims for a workflow run"""
        result = await self.session.execute(
            select(Claim)
            .where(Claim.workflow_run_id == workflow_run_id)
            .order_by(Claim.created_at)
        )
        return list(result.scalars().all())

    async def list_by_run(self, workflow_run_id: UUID) -> List[Claim]:
        """List claims for a workflow run (alias for list_by_workflow_run)"""
        return await self.list_by_workflow_run(workflow_run_id)

    async def list_by_review(self, review_id: UUID) -> List[Claim]:
        """List claims for a review"""
        result = await self.session.execute(
            select(Claim)
            .where(Claim.review_id == review_id)
            .order_by(Claim.created_at)
        )
        return list(result.scalars().all())

    async def get_approved_claims_for_run(self, workflow_run_id: UUID) -> List[Claim]:
        """Get approved claims for a workflow run"""
        result = await self.session.execute(
            select(Claim)
            .where(
                Claim.workflow_run_id == workflow_run_id,
                Claim.status == "approved"
            )
            .order_by(Claim.created_at)
        )
        return list(result.scalars().all())

    async def list_by_superdocs_job_id(self, superdocs_job_id: str) -> List[Claim]:
        """Get all claims linked to a SuperDocs job."""
        result = await self.session.execute(
            select(Claim)
            .where(Claim.superdocs_job_id == superdocs_job_id)
            .order_by(Claim.created_at)
        )
        return list(result.scalars().all())

    async def bulk_approve_for_run(self, workflow_run_id: UUID) -> int:
        """Approve all pending claims for a workflow run"""
        result = await self.session.execute(
            update(Claim)
            .where(
                Claim.workflow_run_id == workflow_run_id,
                Claim.status == "pending"
            )
            .values(status="approved")
        )
        await self.session.flush()
        return result.rowcount or 0

    async def bulk_approve_for_review(self, review_id: UUID) -> int:
        """Approve all pending claims for a review"""
        result = await self.session.execute(
            update(Claim)
            .where(
                Claim.review_id == review_id,
                Claim.status == "pending"
            )
            .values(status="approved")
        )
        await self.session.flush()
        return result.rowcount or 0

    async def bulk_update_status(self, claim_ids: List[UUID], status: str) -> int:
        """Bulk update status for a list of claim IDs."""
        if not claim_ids:
            return 0
        result = await self.session.execute(
            update(Claim)
            .where(Claim.id.in_(claim_ids))
            .values(status=status)
        )
        await self.session.flush()
        return result.rowcount or 0
