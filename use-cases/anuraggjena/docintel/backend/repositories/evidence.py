from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, nullslast
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.evidence import Evidence, Citation


class EvidenceRepository(BaseRepository[Evidence]):
    """Repository for Evidence entity"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Evidence)

    async def list_by_run(self, workflow_run_id: UUID) -> List[Evidence]:
        """List evidence for a workflow run, ordered by relevance score"""
        result = await self.session.execute(
            select(Evidence)
            .where(Evidence.workflow_run_id == workflow_run_id)
            .order_by(Evidence.relevance_score.desc().nullslast())
        )
        return list(result.scalars().all())

    async def list_by_document(self, document_id: UUID) -> List[Evidence]:
        """List evidence for a document, ordered by creation time"""
        result = await self.session.execute(
            select(Evidence)
            .where(Evidence.document_id == document_id)
            .order_by(Evidence.created_at.desc())
        )
        return list(result.scalars().all())


class CitationRepository(BaseRepository[Citation]):
    """Repository for Citation entity"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Citation)

    async def list_by_claim(self, claim_id: UUID) -> List[Citation]:
        """List citations for a claim, ordered by relevance score"""
        result = await self.session.execute(
            select(Citation)
            .where(Citation.claim_id == claim_id)
            .order_by(Citation.relevance_score.desc().nullslast())
        )
        return list(result.scalars().all())

    async def list_by_evidence(self, evidence_id: UUID) -> List[Citation]:
        """List citations for a piece of evidence"""
        result = await self.session.execute(
            select(Citation)
            .where(Citation.evidence_id == evidence_id)
        )
        return list(result.scalars().all())

    async def get_claim_chunk_references(self, claim_id: UUID) -> List[str]:
        """Get list of document chunk IDs referenced by a claim's citations"""
        from backend.models.evidence import Evidence

        # Get citations for claim
        citations = await self.list_by_claim(claim_id)

        # Get unique chunk IDs from evidence
        chunk_ids = []
        for citation in citations:
            if citation.evidence_id:
                evidence_result = await self.session.execute(
                    select(Evidence)
                    .where(Evidence.id == citation.evidence_id)
                )
                evidence = evidence_result.scalar_one_or_none()
                if evidence and evidence.chunk_id:
                    chunk_ids.append(str(evidence.chunk_id))

        return list(set(chunk_ids))  # Deduplicate
