import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.core.knowledge.engine import KnowledgeEngine


def make_entry(content="test content", entry_type="claim", tags=None):
    e = MagicMock()
    e.id = uuid4()
    e.content = content
    e.entry_type = entry_type
    e.tags = tags or []
    return e


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    return repo


@pytest.mark.asyncio
async def test_store_creates_entry(mock_repo):
    entry = make_entry()
    mock_repo.create = AsyncMock(return_value=entry)

    engine = KnowledgeEngine(mock_repo)
    result = await engine.store(
        workspace_id=uuid4(),
        workflow_type="tariff",
        entry_type="claim",
        content="HS code 8471.30"
    )

    assert result == entry
    assert mock_repo.create.called


@pytest.mark.asyncio
async def test_retrieve_no_tags_uses_list(mock_repo):
    entries = [make_entry(), make_entry()]
    mock_repo.list_by_workspace_and_type = AsyncMock(return_value=entries)

    engine = KnowledgeEngine(mock_repo)
    result = await engine.retrieve(uuid4(), "tariff")

    assert len(result) == 2
    assert mock_repo.list_by_workspace_and_type.called
    assert not mock_repo.search_by_tags.called


@pytest.mark.asyncio
async def test_retrieve_with_tags_uses_search(mock_repo):
    entries = [make_entry(tags=["electronics"])]
    mock_repo.search_by_tags = AsyncMock(return_value=entries)

    engine = KnowledgeEngine(mock_repo)
    result = await engine.retrieve(uuid4(), "tariff", tags=["electronics"])

    assert len(result) == 1
    assert mock_repo.search_by_tags.called


@pytest.mark.asyncio
async def test_retrieve_as_context_empty(mock_repo):
    mock_repo.list_by_workspace_and_type = AsyncMock(return_value=[])

    engine = KnowledgeEngine(mock_repo)
    ctx = await engine.retrieve_as_context(uuid4(), "tariff")
    assert ctx == ""


@pytest.mark.asyncio
async def test_retrieve_as_context_with_entries(mock_repo):
    entries = [
        make_entry("Widget A is HS 8471.30", "claim"),
        make_entry("Duty rate is 0%", "claim"),
    ]
    mock_repo.list_by_workspace_and_type = AsyncMock(return_value=entries)

    engine = KnowledgeEngine(mock_repo)
    ctx = await engine.retrieve_as_context(uuid4(), "tariff", limit=5)
    assert "Prior relevant knowledge:" in ctx
    assert "Widget A is HS 8471.30" in ctx
    assert "Duty rate is 0%" in ctx


@pytest.mark.asyncio
async def test_store_with_all_optional_fields(mock_repo):
    entry = make_entry()
    mock_repo.create = AsyncMock(return_value=entry)

    engine = KnowledgeEngine(mock_repo)
    result = await engine.store(
        workspace_id=uuid4(),
        workflow_type="tariff",
        entry_type="summary",
        content="full summary text",
        source_run_id="run-123",
        source_document_id="doc-456",
        metadata={"page": 1},
        confidence_score=0.95,
        tags=["electronics", "hardware"]
    )
    assert result == entry
    call_kwargs = mock_repo.create.call_args.kwargs
    assert call_kwargs["tags"] == ["electronics", "hardware"]
    assert call_kwargs["confidence_score"] == 0.95
    assert call_kwargs["extra_metadata"] == {"page": 1}
