import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def test_citation_builder_importable():
    from backend.core.retrieval.citations import CitationBuilder
    assert CitationBuilder is not None


@pytest.mark.asyncio
async def test_citation_builder_creates_citations_for_claims():
    from backend.core.retrieval.citations import CitationBuilder

    mock_citation_repo = AsyncMock()
    created_citation = MagicMock()
    created_citation.id = uuid4()
    mock_citation_repo.create = AsyncMock(return_value=created_citation)

    builder = CitationBuilder(citation_repository=mock_citation_repo)

    claim_ids = [str(uuid4()), str(uuid4())]
    evidence_ids = [str(uuid4()), str(uuid4())]
    retrieved_chunks = [
        {"chunk_id": "c1", "text": "relevant text 1", "score": 0.9},
        {"chunk_id": "c2", "text": "relevant text 2", "score": 0.8},
    ]

    citation_ids = await builder.build(
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        retrieved_chunks=retrieved_chunks,
    )

    assert len(citation_ids) > 0
    assert mock_citation_repo.create.called


@pytest.mark.asyncio
async def test_citation_builder_returns_empty_for_no_claims():
    from backend.core.retrieval.citations import CitationBuilder

    mock_citation_repo = AsyncMock()
    builder = CitationBuilder(citation_repository=mock_citation_repo)

    result = await builder.build(
        claim_ids=[],
        evidence_ids=["e1"],
        retrieved_chunks=[{"chunk_id": "c1", "text": "text", "score": 0.9}],
    )
    assert result == []
    mock_citation_repo.create.assert_not_called()
