from typing import List
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.lineage import LineageLink


class LineageLinkRepository(BaseRepository[LineageLink]):
    """Repository for lineage link operations"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, LineageLink)

    async def create_link(
        self,
        source_type: str,
        source_id: UUID,
        target_type: str,
        target_id: UUID,
        link_type: str,
        workflow_run_id: UUID,
        stage_name: str = None,
        metadata: dict = None,
    ) -> LineageLink:
        """Create a lineage link"""
        link = LineageLink(
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            link_type=link_type,
            workflow_run_id=workflow_run_id,
            stage_name=stage_name,
            link_metadata=metadata or {}
        )
        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)
        return link

    async def create_links_bulk(
        self,
        links_data: List[dict],
    ) -> List[LineageLink]:
        """Create multiple lineage links in a single database commit."""
        if not links_data:
            return []
        links = []
        for data in links_data:
            link = LineageLink(
                source_type=data["source_type"],
                source_id=data["source_id"],
                target_type=data["target_type"],
                target_id=data["target_id"],
                link_type=data["link_type"],
                workflow_run_id=data["workflow_run_id"],
                stage_name=data.get("stage_name"),
                link_metadata=data.get("metadata") or {},
            )
            self.session.add(link)
            links.append(link)
        await self.session.commit()
        return links

    async def get_links_by_source(
        self,
        source_type: str,
        source_id: UUID
    ) -> List[LineageLink]:
        """Get all links from a source entity"""
        stmt = select(LineageLink).where(
            LineageLink.source_type == source_type,
            LineageLink.source_id == source_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_links_by_target(
        self,
        target_type: str,
        target_id: UUID
    ) -> List[LineageLink]:
        """Get all links to a target entity"""
        stmt = select(LineageLink).where(
            LineageLink.target_type == target_type,
            LineageLink.target_id == target_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_links_by_run(self, run_id: UUID) -> List[LineageLink]:
        """Get all links for a workflow run"""
        stmt = select(LineageLink).where(LineageLink.workflow_run_id == run_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_knowledge_links_for_claim(self, claim_id: UUID) -> List[LineageLink]:
        """Get all knowledge derivation links for a claim"""
        stmt = select(LineageLink).where(
            LineageLink.source_type == "claim",
            LineageLink.source_id == claim_id,
            LineageLink.link_type == "derived_from_knowledge"
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
