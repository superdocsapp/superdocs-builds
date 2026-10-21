import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from backend.repositories.lineage import LineageLinkRepository
from backend.models.lineage import LineageLink


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_link(mock_session):
    """Test creating a lineage link"""
    repo = LineageLinkRepository(mock_session)

    link = await repo.create_link(
        source_type="claim",
        source_id=uuid4(),
        target_type="knowledge_entry",
        target_id=uuid4(),
        link_type="derived_from_knowledge",
        workflow_run_id=uuid4(),
        stage_name="generate",
        metadata={"relevance": "high"}
    )

    assert link is not None
    assert link.link_type == "derived_from_knowledge"
    # Verify session methods were called
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()
    mock_session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_links_by_source(mock_session):
    """Test getting links by source"""
    repo = LineageLinkRepository(mock_session)
    claim_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    links = await repo.get_links_by_source("claim", claim_id)

    assert isinstance(links, list)
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_links_by_target(mock_session):
    """Test getting links by target"""
    repo = LineageLinkRepository(mock_session)
    knowledge_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    links = await repo.get_links_by_target("knowledge_entry", knowledge_id)

    assert isinstance(links, list)
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_links_by_run(mock_session):
    """Test getting links by workflow run"""
    repo = LineageLinkRepository(mock_session)
    run_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    links = await repo.get_links_by_run(run_id)

    assert isinstance(links, list)
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_knowledge_links_for_claim(mock_session):
    """Test getting knowledge links for a claim"""
    repo = LineageLinkRepository(mock_session)
    claim_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    links = await repo.get_knowledge_links_for_claim(claim_id)

    assert isinstance(links, list)
    mock_session.execute.assert_awaited_once()
