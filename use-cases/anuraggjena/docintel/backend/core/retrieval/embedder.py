from typing import List
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.retrieval.provider import EmbeddingProvider
from backend.core.retrieval.chunker import Chunk
from backend.models.document import DocumentChunk
from backend.logging_config import get_logger

logger = get_logger(__name__)


class Embedder:
    """
    Converts Chunk objects into vector embeddings and persists them into
    the document_chunks table.
    """

    def __init__(self, provider: EmbeddingProvider, session: AsyncSession):
        self._provider = provider
        self._session = session

    async def embed_and_store(
        self,
        chunks: List[Chunk],
        document_id: str,
    ) -> int:
        """
        Embed all chunks and upsert embeddings into document_chunks.

        Creates new DocumentChunk rows if they don't exist, or updates
        the embedding on existing rows matched by (document_id, chunk_index).

        Returns the number of chunks processed.
        """
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        vectors = await self._provider.embed(texts)

        for chunk, vector in zip(chunks, vectors):
            # Check if row already exists
            result = await self._session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == UUID(document_id),
                    DocumentChunk.chunk_index == chunk.chunk_index,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.embedding = vector
                existing.text = chunk.text
                if chunk.page_number is not None:
                    existing.page_number = chunk.page_number
            else:
                db_chunk = DocumentChunk(
                    document_id=UUID(document_id),
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    embedding=vector,
                    page_number=chunk.page_number,
                    chunk_metadata=chunk.metadata,
                )
                self._session.add(db_chunk)

        await self._session.commit()
        logger.info("chunks_embedded_and_stored", count=len(chunks), document_id=document_id)
        return len(chunks)
