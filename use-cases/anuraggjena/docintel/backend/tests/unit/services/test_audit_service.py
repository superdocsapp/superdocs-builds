import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from backend.services.audit import AuditService


def make_log_entry(event_type="workflow.started"):
    e = MagicMock()
    e.id = str(uuid4())
    e.event_type = event_type
    return e


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.create = AsyncMock(return_value=make_log_entry())
    return repo


@pytest.mark.asyncio
async def test_log_creates_entry(mock_repo):
    service = AuditService(mock_repo)
    result = await service.log("test.event", resource_type="workflow_run", resource_id="run-1")
    assert mock_repo.create.called


@pytest.mark.asyncio
async def test_log_workflow_started(mock_repo):
    service = AuditService(mock_repo)
    await service.log_workflow_started("run-1", "ws-1", "tariff")
    call_kwargs = mock_repo.create.call_args.kwargs
    assert call_kwargs["event_type"] == "workflow.started"
    assert call_kwargs["details"]["workflow_type"] == "tariff"


@pytest.mark.asyncio
async def test_log_workflow_completed(mock_repo):
    service = AuditService(mock_repo)
    await service.log_workflow_completed("run-1", "ws-1", "completed")
    call_kwargs = mock_repo.create.call_args.kwargs
    assert call_kwargs["event_type"] == "workflow.completed"
    assert call_kwargs["details"]["status"] == "completed"


@pytest.mark.asyncio
async def test_log_review_created(mock_repo):
    service = AuditService(mock_repo)
    await service.log_review_created("rev-1", "ws-1", actor_id="user-42")
    call_kwargs = mock_repo.create.call_args.kwargs
    assert call_kwargs["event_type"] == "review.created"
    assert call_kwargs["actor_id"] == "user-42"


@pytest.mark.asyncio
async def test_log_export_created(mock_repo):
    service = AuditService(mock_repo)
    await service.log_export_created("exp-1", "ws-1", format="docx")
    call_kwargs = mock_repo.create.call_args.kwargs
    assert call_kwargs["event_type"] == "export.created"
    assert call_kwargs["details"]["format"] == "docx"


@pytest.mark.asyncio
async def test_get_workspace_audit_log(mock_repo):
    mock_repo.list_by_workspace = AsyncMock(return_value=[make_log_entry()])
    service = AuditService(mock_repo)
    result = await service.get_workspace_audit_log(uuid4())
    assert len(result) == 1
