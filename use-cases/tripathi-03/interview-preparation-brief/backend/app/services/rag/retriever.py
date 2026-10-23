"""Evidence-aware retriever used by LangGraph nodes."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vector_store import VectorStore

logger = get_logger(__name__)


class Retriever:
    """Retrieve grounded context for a query with optional source filter."""

    def __init__(
        self,
        db: AsyncSession,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.embeddings = embedding_service or EmbeddingService()
        self.store = VectorStore(db)

    async def retrieve(
        self,
        *,
        session_id: UUID,
        query: str,
        source: str | None = None,
        top_k: int | None = None,
    ) -> list[str]:
        embedding = await self.embeddings.embed_query(query)
        hits = await self.store.similarity_search(
            session_id=session_id,
            query_embedding=embedding,
            source=source,
            top_k=top_k or self.settings.retrieval_top_k,
        )
        return [h["content"] for h in hits]

    async def retrieve_resume_evidence(
        self,
        *,
        session_id: UUID,
        query: str,
        top_k: int | None = None,
    ) -> list[str]:
        """Always constrain to resume source for anti-hallucination."""
        evidence = await self.retrieve(
            session_id=session_id,
            query=query,
            source="resume",
            top_k=top_k,
        )
        logger.info(
            "Resume evidence for query len=%s → %s spans",
            len(query),
            len(evidence),
        )
        return evidence
