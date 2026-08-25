from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.document import Document, DocumentChunk


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Document)

    async def list_by_workspace(self, workspace_id: UUID, limit: int = 100) -> List[Document]:
        """List documents for a specific workspace"""
        result = await self.session.execute(
            select(Document)
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_workspace_and_role(
        self,
        workspace_id: UUID,
        document_role: str,
        limit: int = 100,
    ) -> List[Document]:
        """List documents for a workspace filtered by role."""
        result = await self.session.execute(
            select(Document)
            .where(
                Document.workspace_id == workspace_id,
                Document.document_role == document_role,
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_checksum(self, workspace_id: UUID, checksum: str) -> Optional[Document]:
        """Get document by content checksum within a workspace"""
        result = await self.session.execute(
            select(Document)
            .where(Document.checksum == checksum)
            .where(Document.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    """Repository for DocumentChunk operations"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, DocumentChunk)

    async def list_by_document(self, document_id: UUID) -> List[DocumentChunk]:
        """List chunks for a document"""
        result = await self.session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result.scalars().all())

    async def get_by_document_id(self, document_id: UUID) -> List[DocumentChunk]:
        """Alias for list_by_document for compatibility"""
        return await self.list_by_document(document_id)
