from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.knowledge import KnowledgeEntry


class KnowledgeRepository(BaseRepository[KnowledgeEntry]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeEntry)

    async def list_by_workspace(
        self,
        workspace_id: UUID,
        limit: int = 50
    ) -> List[KnowledgeEntry]:
        """List all knowledge entries for a workspace."""
        result = await self.session.execute(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.workspace_id == workspace_id)
            .order_by(KnowledgeEntry.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_workspace_and_type(
        self,
        workspace_id: UUID,
        workflow_type: str,
        limit: int = 50
    ) -> List[KnowledgeEntry]:
        result = await self.session.execute(
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.workspace_id == workspace_id,
                KnowledgeEntry.workflow_type == workflow_type
            )
            .order_by(KnowledgeEntry.created_at.desc())
            .limit(limit)
        )
        entries = list(result.scalars().all())
        if not entries:
            # Flexible prefix match (e.g. "tariff_classification" matches "tariff")
            alt_prefix = "tariff" if "tariff" in workflow_type else workflow_type
            result_alt = await self.session.execute(
                select(KnowledgeEntry)
                .where(
                    KnowledgeEntry.workspace_id == workspace_id,
                    KnowledgeEntry.workflow_type.ilike(f"{alt_prefix}%")
                )
                .order_by(KnowledgeEntry.created_at.desc())
                .limit(limit)
            )
            entries = list(result_alt.scalars().all())
        return entries

    async def search_by_tags(
        self,
        workspace_id: UUID,
        tags: List[str],
        workflow_type: Optional[str] = None,
        limit: int = 20
    ) -> List[KnowledgeEntry]:
        """Return entries whose tags overlap with the given tags (simple JSON contains check)."""
        query = select(KnowledgeEntry).where(
            KnowledgeEntry.workspace_id == workspace_id
        )
        if workflow_type:
            query = query.where(KnowledgeEntry.workflow_type == workflow_type)
        # Load all and filter in Python (simple approach without pg-specific JSON operators)
        result = await self.session.execute(query.order_by(KnowledgeEntry.created_at.desc()).limit(200))
        entries = list(result.scalars().all())
        tag_set = set(tags)
        matched = [e for e in entries if tag_set.intersection(set(e.tags or []))]
        return matched[:limit]
