import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def test_embedder_importable():
    from backend.core.retrieval.embedder import Embedder
    assert Embedder is not None


@pytest.mark.asyncio
async def test_embedder_embed_and_store_calls_provider():
    from backend.core.retrieval.embedder import Embedder
    from backend.core.retrieval.chunker import Chunk

    mock_provider = AsyncMock()
    mock_provider.dimension = 384
    mock_provider.embed = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no existing rows
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    embedder = Embedder(provider=mock_provider, session=mock_session)
    chunks = [
        Chunk(document_id="doc-1", chunk_index=0, text="Hello world"),
        Chunk(document_id="doc-1", chunk_index=1, text="Tariff code"),
    ]

    result = await embedder.embed_and_store(chunks, document_id=str(uuid4()))
    mock_provider.embed.assert_called_once_with(["Hello world", "Tariff code"])
    assert result == 2


@pytest.mark.asyncio
async def test_embedder_returns_zero_for_empty_chunks():
    from backend.core.retrieval.embedder import Embedder

    mock_provider = AsyncMock()
    mock_session = AsyncMock()
    embedder = Embedder(provider=mock_provider, session=mock_session)
    result = await embedder.embed_and_store([], document_id="doc-1")
    assert result == 0
    mock_provider.embed.assert_not_called()
