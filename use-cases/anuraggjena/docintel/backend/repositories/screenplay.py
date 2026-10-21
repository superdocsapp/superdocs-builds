"""Repository for screenplay formatting items"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from uuid import UUID

from backend.repositories.base import BaseRepository
from backend.models.screenplay import ScreenplayFormattingItem


class FormattingItemRepository(BaseRepository[ScreenplayFormattingItem]):
    """Repository for ScreenplayFormattingItem entity"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ScreenplayFormattingItem)

    async def list_by_run(self, run_id: UUID) -> List[ScreenplayFormattingItem]:
        """
        List all formatting items for a workflow run, ordered by element_index.

        Args:
            run_id: Workflow run UUID

        Returns:
            List of formatting items in element order
        """
        result = await self.session.execute(
            select(self.model)
            .where(self.model.workflow_run_id == run_id)
            .order_by(self.model.element_index)
        )
        return list(result.scalars().all())

    async def list_by_review(self, review_id: UUID) -> List[ScreenplayFormattingItem]:
        """
        List all formatting items for a review.

        Args:
            review_id: Review UUID

        Returns:
            List of formatting items for the review
        """
        result = await self.session.execute(
            select(self.model)
            .where(self.model.review_id == review_id)
            .order_by(self.model.element_index)
        )
        return list(result.scalars().all())

    async def approve(self, item_id: UUID) -> Optional[ScreenplayFormattingItem]:
        """
        Approve a single formatting item.

        Args:
            item_id: Formatting item UUID

        Returns:
            Updated formatting item or None if not found
        """
        result = await self.session.execute(
            select(self.model).where(self.model.id == item_id)
        )
        item = result.scalar_one_or_none()

        if item is None:
            return None

        item.status = "approved"
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def reject(
        self,
        item_id: UUID,
        reviewer_comment: str
    ) -> Optional[ScreenplayFormattingItem]:
        """
        Reject a formatting item with a reviewer comment.

        Args:
            item_id: Formatting item UUID
            reviewer_comment: Comment explaining rejection

        Returns:
            Updated formatting item or None if not found
        """
        result = await self.session.execute(
            select(self.model).where(self.model.id == item_id)
        )
        item = result.scalar_one_or_none()

        if item is None:
            return None

        item.status = "rejected"
        item.reviewer_comment = reviewer_comment
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def approve_all_for_run(self, run_id: UUID) -> int:
        """
        Approve all pending formatting items for a run.

        Args:
            run_id: Workflow run UUID

        Returns:
            Count of items approved
        """
        result = await self.session.execute(
            update(ScreenplayFormattingItem)
            .where(
                ScreenplayFormattingItem.workflow_run_id == run_id,
                ScreenplayFormattingItem.status == "pending",
            )
            .values(status="approved")
        )
        await self.session.commit()
        return result.rowcount

    async def list_rejected(self, run_id: UUID) -> List[ScreenplayFormattingItem]:
        """
        List only rejected formatting items for a run.

        Args:
            run_id: Workflow run UUID

        Returns:
            List of rejected formatting items
        """
        result = await self.session.execute(
            select(self.model)
            .where(
                self.model.workflow_run_id == run_id,
                self.model.status == "rejected"
            )
            .order_by(self.model.element_index)
        )
        return list(result.scalars().all())

    async def attach_review(self, run_id: UUID, review_id: UUID) -> None:
        """
        Attach a review_id to all formatting items for a run.

        Uses bulk UPDATE for performance.

        Args:
            run_id: Workflow run UUID
            review_id: Review UUID to attach
        """
        await self.session.execute(
            update(ScreenplayFormattingItem)
            .where(ScreenplayFormattingItem.workflow_run_id == run_id)
            .values(review_id=review_id)
        )
        await self.session.commit()
