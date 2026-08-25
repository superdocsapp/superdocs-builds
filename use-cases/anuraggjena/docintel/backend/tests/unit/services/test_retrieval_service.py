import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def test_retrieval_service_importable():
    from backend.services.retrieval import RetrievalService
    assert RetrievalService is not None


@pytest.mark.asyncio
async def test_ingest_document_calls_chunker_and_embedder():
    from backend.services.retrieval import RetrievalService
    from backend.core.retrieval.chunker import Chunk

    mock_chunker = MagicMock()
    mock_chunker.chunk = MagicMock(return_value=[
        Chunk(document_id="doc-1", chunk_index=0, text="Hello world"),
    ])
    mock_embedder = AsyncMock()
    mock_embedder.embed_and_store = AsyncMock(return_value=1)
    mock_search = AsyncMock()

    svc = RetrievalService(
        chunker=mock_chunker,
        embedder=mock_embedder,
        search=mock_search,
    )

    count = await svc.ingest_document(text="Hello world", document_id="doc-1")
    assert count == 1
    mock_chunker.chunk.assert_called_once_with("Hello world", document_id="doc-1", page_number=None)
    mock_embedder.embed_and_store.assert_called_once()


@pytest.mark.asyncio
async def test_search_returns_results():
    from backend.services.retrieval import RetrievalService
    from backend.core.retrieval.search import SearchResult

    mock_provider = AsyncMock()
    mock_provider.embed_one = AsyncMock(return_value=[0.1] * 384)

    mock_chunker = MagicMock()
    mock_embedder = AsyncMock()
    mock_embedder._provider = mock_provider
    mock_search = AsyncMock()
    mock_search.search = AsyncMock(return_value=[
        SearchResult(chunk_id="c1", document_id="d1", text="relevant text", score=0.9)
    ])

    svc = RetrievalService(
        chunker=mock_chunker,
        embedder=mock_embedder,
        search=mock_search,
    )

    results = await svc.search(
        query="tariff HS code",
        document_ids=["d1"],
        top_k=5,
    )
    assert len(results) == 1
    assert results[0].score == 0.9
