"""Ingest documents into chunked embeddings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.rag.chunking import chunk_text
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vector_store import VectorStore

logger = get_logger(__name__)


class IngestionService:
    def __init__(
        self,
        db: AsyncSession,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.db = db
        self.embeddings = embedding_service or EmbeddingService()
        self.store = VectorStore(db)

    async def index_document(
        self,
        *,
        session_id: UUID,
        document_id: UUID,
        source: str,
        text: str,
    ) -> int:
        chunks = chunk_text(text)
        if not chunks:
            logger.warning("No chunks produced for document=%s", document_id)
            return 0
        embeddings = await self.embeddings.embed_texts(chunks)
        count = await self.store.replace_document_chunks(
            session_id=session_id,
            document_id=document_id,
            source=source,
            chunks=chunks,
            embeddings=embeddings,
        )
        logger.info("Indexed document=%s source=%s chunks=%s", document_id, source, count)
        return count
