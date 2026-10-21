import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from backend.main import app
from backend.api.v1.stream import workflow_event_generator, router


@pytest.mark.asyncio
async def test_stream_not_found():
    """SSE returns error event when run not found."""
    mock_db = AsyncMock()

    with patch('backend.api.v1.stream.WorkflowRunRepository') as MockRunRepo, \
         patch('backend.api.v1.stream.WorkflowStageRepository') as MockStageRepo:

        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=None)
        MockRunRepo.return_value = run_repo

        events = []
        async for event in workflow_event_generator(uuid4(), mock_db):
            events.append(event)

        assert any("error" in e for e in events)
        assert any("not found" in e for e in events)


@pytest.mark.asyncio
async def test_stream_completed_run():
    """SSE emits done event when run is already completed."""
    mock_db = AsyncMock()
    run_id = uuid4()

    run = MagicMock()
    run.status = "completed"
    run.current_stage = "generate"
    run.error_message = None

    stage = MagicMock()
    stage.id = uuid4()
    stage.stage_name = "extract"
    stage.status = "completed"
    stage.stage_index = 0
    stage.started_at = datetime.now(timezone.utc)
    stage.completed_at = datetime.now(timezone.utc)
    stage.execution_time_ms = 1500
    stage.error_message = None

    with patch('backend.api.v1.stream.WorkflowRunRepository') as MockRunRepo, \
         patch('backend.api.v1.stream.WorkflowStageRepository') as MockStageRepo:

        run_repo = AsyncMock()
        run_repo.get_by_id = AsyncMock(return_value=run)
        MockRunRepo.return_value = run_repo

        stage_repo = AsyncMock()
        stage_repo.list_by_run = AsyncMock(return_value=[stage])
        MockStageRepo.return_value = stage_repo

        events = []
        async for event in workflow_event_generator(run_id, mock_db):
            events.append(event)

        event_types = [e.split('\n')[0].replace('event: ', '') for e in events if e.startswith('event:')]
        assert 'stage_update' in event_types
        assert 'run_status' in event_types
        assert 'done' in event_types


@pytest.mark.asyncio
async def test_stream_endpoint_returns_200():
    """SSE endpoint returns 200 with text/event-stream content type."""
    run_id = uuid4()

    async def fake_generator(run_id, db=None, **kwargs):
        yield f"event: done\ndata: {{\"status\": \"completed\"}}\n\n"

    from backend.api.v1.stream import verify_sse_access
    mock_run = MagicMock()
    app.dependency_overrides[verify_sse_access] = lambda: mock_run

    try:
        with patch('backend.api.v1.stream.workflow_event_generator', side_effect=fake_generator):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get(f"/api/v1/stream/workflow-run/{run_id}")

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
    finally:
        app.dependency_overrides.pop(verify_sse_access, None)
