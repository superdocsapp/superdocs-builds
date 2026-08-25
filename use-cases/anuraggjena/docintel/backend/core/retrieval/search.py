from dataclasses import dataclass
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    text: str
    score: float
    page_number: Optional[int] = None


class VectorSearchService:
    """
    Semantic similarity search over DocumentChunk embeddings using pgvector.

    Fails clearly if pgvector extension is missing — does NOT fall back
    to keyword search.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def search(
        self,
        query_vector: List[float],
        document_ids: List[str],
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        Find the top_k most similar chunks to query_vector from the given documents.

        Uses cosine distance operator (<=>). Requires pgvector extension in PostgreSQL.
        Raises RuntimeError with setup instructions if pgvector is unavailable.
        """
        if not document_ids:
            return []

        vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"
        placeholders = ", ".join(f"'{did}'::uuid" for did in document_ids)

        sql = text(f"""
            SELECT
                id::text AS chunk_id,
                document_id::text AS document_id,
                text,
                page_number,
                1 - (embedding <=> '{vector_literal}'::vector) AS score
            FROM document_chunks
            WHERE document_id IN ({placeholders})
              AND embedding IS NOT NULL
            ORDER BY embedding <=> '{vector_literal}'::vector
            LIMIT {top_k}
        """)

        try:
            result = await self._session.execute(sql)
            rows = result.fetchall()
        except Exception as exc:
            err = str(exc)
            if "operator does not exist" in err or "vector" in err.lower():
                raise RuntimeError(
                    "pgvector extension is not installed or not enabled in PostgreSQL. "
                    "Run: CREATE EXTENSION IF NOT EXISTS vector; "
                    "then re-run migrations."
                ) from exc
            raise

        return [
            SearchResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                text=row.text,
                score=float(row.score),
                page_number=row.page_number,
            )
            for row in rows
        ]
