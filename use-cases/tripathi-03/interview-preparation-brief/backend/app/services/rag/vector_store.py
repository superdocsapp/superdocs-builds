"""pgvector persistence and similarity search."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.embedding import DocumentChunk

logger = get_logger(__name__)


class VectorStore:
    """Store and retrieve document chunk embeddings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    async def replace_document_chunks(
        self,
        *,
        session_id: UUID,
        document_id: UUID,
        source: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")

        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )

        rows = [
            DocumentChunk(
                id=uuid4(),
                document_id=document_id,
                session_id=session_id,
                source=source,
                chunk_index=idx,
                content=content,
                embedding=embedding,
            )
            for idx, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ]
        self.db.add_all(rows)
        await self.db.flush()
        logger.info(
            "Stored %s chunks for document=%s source=%s",
            len(rows),
            document_id,
            source,
        )
        return len(rows)

    async def similarity_search(
        self,
        *,
        session_id: UUID,
        query_embedding: list[float],
        source: str | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        k = top_k or self.settings.retrieval_top_k
        # pgvector cosine distance operator <=>
        embedding_literal = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

        sql = """
            SELECT id::text, content, source, chunk_index,
                   (embedding <=> CAST(:embedding AS vector)) AS distance
            FROM document_chunks
            WHERE session_id = CAST(:session_id AS uuid)
        """
        params: dict[str, object] = {
            "embedding": embedding_literal,
            "session_id": str(session_id),
            "top_k": k,
        }
        if source:
            sql += " AND source = :source"
            params["source"] = source
        sql += " ORDER BY embedding <=> CAST(:embedding AS vector) ASC LIMIT :top_k"

        result = await self.db.execute(text(sql), params)
        rows = result.mappings().all()
        hits = [
            {
                "id": row["id"],
                "content": row["content"],
                "source": row["source"],
                "chunk_index": row["chunk_index"],
                "distance": float(row["distance"]) if row["distance"] is not None else None,
            }
            for row in rows
        ]
        logger.debug(
            "similarity_search session=%s source=%s hits=%s",
            session_id,
            source,
            len(hits),
        )
        return hits

    async def get_document_text(self, document_id: UUID) -> str | None:
        from app.models.document import Document

        result = await self.db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        return doc.content_text if doc else None
