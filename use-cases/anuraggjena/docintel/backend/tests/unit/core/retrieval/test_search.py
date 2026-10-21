import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def test_vector_search_service_importable():
    from backend.core.retrieval.search import VectorSearchService
    assert VectorSearchService is not None


def test_vector_search_service_requires_session():
    from backend.core.retrieval.search import VectorSearchService
    session = MagicMock()
    svc = VectorSearchService(session)
    assert svc is not None


@pytest.mark.asyncio
async def test_search_returns_list():
    """search() always returns a list (may be empty with mocked session)."""
    from backend.core.retrieval.search import VectorSearchService, SearchResult
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    svc = VectorSearchService(session)
    query_vector = [0.1] * 384
    results = await svc.search(
        query_vector=query_vector,
        document_ids=[str(uuid4())],
        top_k=5,
    )
    assert isinstance(results, list)


def test_search_result_dataclass():
    from backend.core.retrieval.search import SearchResult
    r = SearchResult(
        chunk_id="chunk-1",
        document_id="doc-1",
        text="tariff HS 8471",
        score=0.92,
        page_number=None,
    )
    assert r.chunk_id == "chunk-1"
    assert r.score == 0.92
