"""Tests for FormattingItemRepository"""
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from backend.repositories.screenplay import FormattingItemRepository
from backend.models.screenplay import ScreenplayFormattingItem


@pytest.fixture
def mock_session():
    """Mock async database session"""
    return AsyncMock()


@pytest.fixture
def repository(mock_session):
    """Create repository with mocked session"""
    return FormattingItemRepository(mock_session)


@pytest.mark.asyncio
async def test_list_by_run(repository, mock_session):
    """Test listing all formatting items for a run ordered by element_index"""
    run_id = uuid4()

    # Mock items in database
    item1 = MagicMock(spec=ScreenplayFormattingItem)
    item1.id = uuid4()
    item1.element_index = 0
    item1.element_type = "scene_heading"

    item2 = MagicMock(spec=ScreenplayFormattingItem)
    item2.id = uuid4()
    item2.element_index = 1
    item2.element_type = "action"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [item1, item2]
    mock_session.execute.return_value = mock_result

    # Call repository method
    items = await repository.list_by_run(run_id)

    # Assertions
    assert len(items) == 2
    assert items[0].element_index == 0
    assert items[1].element_index == 1
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_by_review(repository, mock_session):
    """Test listing all formatting items for a review"""
    review_id = uuid4()

    # Mock items
    item1 = MagicMock(spec=ScreenplayFormattingItem)
    item1.id = uuid4()
    item1.review_id = review_id
    item1.status = "pending"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [item1]
    mock_session.execute.return_value = mock_result

    # Call repository method
    items = await repository.list_by_review(review_id)

    # Assertions
    assert len(items) == 1
    assert items[0].review_id == review_id
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_approve(repository, mock_session):
    """Test approving a single formatting item"""
    item_id = uuid4()

    # Mock existing item
    mock_item = MagicMock(spec=ScreenplayFormattingItem)
    mock_item.id = item_id
    mock_item.status = "pending"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_item
    mock_session.execute.return_value = mock_result

    # Call repository method
    result = await repository.approve(item_id)

    # Assertions
    assert result is not None
    assert result.status == "approved"
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(mock_item)


@pytest.mark.asyncio
async def test_approve_nonexistent_item(repository, mock_session):
    """Test approving a non-existent item returns None"""
    item_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Call repository method
    result = await repository.approve(item_id)

    # Assertions
    assert result is None
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reject(repository, mock_session):
    """Test rejecting a formatting item with reviewer comment"""
    item_id = uuid4()
    reviewer_comment = "This formatting looks incorrect"

    # Mock existing item
    mock_item = MagicMock(spec=ScreenplayFormattingItem)
    mock_item.id = item_id
    mock_item.status = "pending"
    mock_item.reviewer_comment = None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_item
    mock_session.execute.return_value = mock_result

    # Call repository method
    result = await repository.reject(item_id, reviewer_comment)

    # Assertions
    assert result is not None
    assert result.status == "rejected"
    assert result.reviewer_comment == reviewer_comment
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(mock_item)


@pytest.mark.asyncio
async def test_reject_nonexistent_item(repository, mock_session):
    """Test rejecting a non-existent item returns None"""
    item_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Call repository method
    result = await repository.reject(item_id, "comment")

    # Assertions
    assert result is None
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_approve_all_for_run(repository, mock_session):
    """Test bulk approving all pending items for a run using UPDATE"""
    run_id = uuid4()

    # Mock UPDATE result with rowcount
    mock_result = MagicMock()
    mock_result.rowcount = 2  # 2 pending items were updated
    mock_session.execute.return_value = mock_result

    # Call repository method
    count = await repository.approve_all_for_run(run_id)

    # Assertions
    assert count == 2
    mock_session.commit.assert_called_once()
    mock_session.execute.assert_called_once()  # Single bulk UPDATE call


@pytest.mark.asyncio
async def test_approve_all_for_run_no_pending(repository, mock_session):
    """Test approve_all when no pending items exist"""
    run_id = uuid4()

    # Mock UPDATE result with zero rowcount
    mock_result = MagicMock()
    mock_result.rowcount = 0  # No pending items to update
    mock_session.execute.return_value = mock_result

    # Call repository method
    count = await repository.approve_all_for_run(run_id)

    # Assertions
    assert count == 0
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_list_rejected(repository, mock_session):
    """Test listing only rejected items for a run"""
    run_id = uuid4()

    # Mock rejected items
    rejected_item = MagicMock(spec=ScreenplayFormattingItem)
    rejected_item.id = uuid4()
    rejected_item.status = "rejected"
    rejected_item.reviewer_comment = "Fix this"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rejected_item]
    mock_session.execute.return_value = mock_result

    # Call repository method
    items = await repository.list_rejected(run_id)

    # Assertions
    assert len(items) == 1
    assert items[0].status == "rejected"
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_attach_review(repository, mock_session):
    """Test attaching a review_id to all items for a run using bulk UPDATE"""
    run_id = uuid4()
    review_id = uuid4()

    # Mock UPDATE result
    mock_result = MagicMock()
    mock_session.execute.return_value = mock_result

    # Call repository method
    await repository.attach_review(run_id, review_id)

    # Assertions
    mock_session.commit.assert_called_once()
    mock_session.execute.assert_called_once()  # Single bulk UPDATE call


@pytest.mark.asyncio
async def test_attach_review_empty_run(repository, mock_session):
    """Test attach_review when run has no items"""
    run_id = uuid4()
    review_id = uuid4()

    # Mock UPDATE result
    mock_result = MagicMock()
    mock_session.execute.return_value = mock_result

    # Call repository method (should not fail)
    await repository.attach_review(run_id, review_id)

    # Assertions
    mock_session.commit.assert_called_once()
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_create_formatting_item(repository, mock_session):
    """Test creating a formatting item via base repository create method"""
    run_id = uuid4()

    # Mock the created item
    mock_item = MagicMock(spec=ScreenplayFormattingItem)
    mock_item.id = uuid4()
    mock_item.workflow_run_id = run_id
    mock_item.element_index = 0
    mock_item.element_type = "scene_heading"
    mock_item.original_text = "INT. ROOM - DAY"
    mock_item.formatted_text = "INT. ROOM - DAY"
    mock_item.change_type = "no_change"
    mock_item.status = "pending"

    # Mock session behavior
    mock_session.add = MagicMock()
    mock_session.refresh = AsyncMock(side_effect=lambda x: None)

    # Call repository create method
    result = await repository.create(
        workflow_run_id=run_id,
        element_index=0,
        element_type="scene_heading",
        original_text="INT. ROOM - DAY",
        formatted_text="INT. ROOM - DAY",
        change_type="no_change",
        status="pending"
    )

    # Assertions
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once()
