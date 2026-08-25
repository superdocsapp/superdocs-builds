from typing import List, Optional

from backend.core.retrieval.chunker import DocumentChunker
from backend.core.retrieval.embedder import Embedder
from backend.core.retrieval.search import VectorSearchService, SearchResult
from backend.logging_config import get_logger

logger = get_logger(__name__)


class RetrievalService:
    """
    Orchestrates document ingestion (chunk → embed → store) and
    semantic search for the workflow.
    """

    def __init__(
        self,
        chunker: DocumentChunker,
        embedder: Embedder,
        search: VectorSearchService,
    ):
        self._chunker = chunker
        self._embedder = embedder
        self._search = search

    async def ingest_document(
        self,
        text: str,
        document_id: str,
        page_number: Optional[int] = None,
    ) -> int:
        """
        Chunk, embed, and store a document's text.
        Returns the number of chunks stored.
        """
        chunks = self._chunker.chunk(text, document_id=document_id, page_number=page_number)
        if not chunks:
            logger.warning("ingest_document_no_chunks", document_id=document_id)
            return 0
        count = await self._embedder.embed_and_store(chunks, document_id=document_id)
        logger.info("document_ingested", document_id=document_id, chunks=count)
        return count

    async def search(
        self,
        query: str,
        document_ids: List[str],
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        Embed the query and return the top_k most similar chunks.
        """
        query_vector = await self._embedder._provider.embed_one(query)
        results = await self._search.search(
            query_vector=query_vector,
            document_ids=document_ids,
            top_k=top_k,
        )
        logger.info("retrieval_search_complete", query_len=len(query), results=len(results))
        return results
