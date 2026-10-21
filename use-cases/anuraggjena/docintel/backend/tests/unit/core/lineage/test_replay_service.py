"""
Unit tests for ReplayService.

Tests the timeline reconstruction logic that reads checkpoint_data from
WorkflowStage records and builds ReplayTimeline objects.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from backend.core.lineage.replay import ReplayService


@pytest.fixture
def mock_repositories():
    """Create mock repositories for ReplayService"""
    return {
        'stage_repo': AsyncMock(),
        'lineage_service': AsyncMock(),
        'run_repo': AsyncMock(),
    }


@pytest.mark.asyncio
async def test_replay_run_execution(mock_repositories):
    """Test replaying a workflow run execution"""
    service = ReplayService(**mock_repositories)

    run_id = uuid4()

    # Mock workflow run
    mock_run = MagicMock()
    mock_run.id = run_id
    mock_repositories['run_repo'].get_by_id.return_value = mock_run

    # Mock stage with checkpoint data
    mock_stage1 = MagicMock()
    mock_stage1.stage_name = "extract"
    mock_stage1.status = "completed"
    mock_stage1.started_at = MagicMock()
    mock_stage1.started_at.isoformat.return_value = "2026-01-01T00:00:00"
    mock_stage1.completed_at = MagicMock()
    mock_stage1.completed_at.isoformat.return_value = "2026-01-01T00:01:00"
    mock_stage1.execution_time_ms = 60000
    mock_stage1.checkpoint_data = '{"inputs": {}, "outputs": {}}'

    mock_repositories['stage_repo'].list_by_run.return_value = [mock_stage1]

    timeline = await service.replay_run_execution(run_id)

    assert timeline is not None
    assert len(timeline.stages) == 1
    assert timeline.stages[0].stage_name == "extract"
    assert timeline.stages[0].status == "completed"
    assert timeline.run_id == run_id


@pytest.mark.asyncio
async def test_replay_with_checkpoint_data(mock_repositories):
    """Test replay parses checkpoint_data correctly"""
    service = ReplayService(**mock_repositories)

    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_repositories['run_repo'].get_by_id.return_value = mock_run

    mock_stage = MagicMock()
    mock_stage.stage_name = "generate"
    mock_stage.status = "completed"
    mock_stage.started_at = MagicMock()
    mock_stage.started_at.isoformat.return_value = "2026-01-01T00:00:00"
    mock_stage.completed_at = MagicMock()
    mock_stage.completed_at.isoformat.return_value = "2026-01-01T00:01:00"
    mock_stage.execution_time_ms = 60000
    mock_stage.checkpoint_data = '{"generated_report": "Test report", "claim_ids": ["123"]}'

    mock_repositories['stage_repo'].list_by_run.return_value = [mock_stage]

    timeline = await service.replay_run_execution(run_id)

    assert timeline.stages[0].outputs["generated_report"] == "Test report"
    assert timeline.stages[0].outputs["claim_ids"] == ["123"]


@pytest.mark.asyncio
async def test_replay_with_dict_checkpoint(mock_repositories):
    """Test replay handles checkpoint_data that is already a dict"""
    service = ReplayService(**mock_repositories)

    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_repositories['run_repo'].get_by_id.return_value = mock_run

    mock_stage = MagicMock()
    mock_stage.stage_name = "retrieve"
    mock_stage.status = "completed"
    mock_stage.started_at = MagicMock()
    mock_stage.started_at.isoformat.return_value = "2026-01-01T00:00:00"
    mock_stage.completed_at = MagicMock()
    mock_stage.completed_at.isoformat.return_value = "2026-01-01T00:01:00"
    mock_stage.execution_time_ms = 30000
    # checkpoint_data is already a dict (from JSON column)
    mock_stage.checkpoint_data = {"retrieved_chunks": [{"text": "chunk1"}]}

    mock_repositories['stage_repo'].list_by_run.return_value = [mock_stage]

    timeline = await service.replay_run_execution(run_id)

    assert timeline.stages[0].outputs["retrieved_chunks"][0]["text"] == "chunk1"


@pytest.mark.asyncio
async def test_replay_with_null_checkpoint(mock_repositories):
    """Test replay handles stages with no checkpoint_data"""
    service = ReplayService(**mock_repositories)

    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_repositories['run_repo'].get_by_id.return_value = mock_run

    mock_stage = MagicMock()
    mock_stage.stage_name = "quality_gate"
    mock_stage.status = "completed"
    mock_stage.started_at = MagicMock()
    mock_stage.started_at.isoformat.return_value = "2026-01-01T00:00:00"
    mock_stage.completed_at = MagicMock()
    mock_stage.completed_at.isoformat.return_value = "2026-01-01T00:00:30"
    mock_stage.execution_time_ms = 500
    mock_stage.checkpoint_data = None

    mock_repositories['stage_repo'].list_by_run.return_value = [mock_stage]

    timeline = await service.replay_run_execution(run_id)

    assert timeline.stages[0].inputs == {}
    assert timeline.stages[0].outputs == {}


@pytest.mark.asyncio
async def test_replay_with_malformed_checkpoint(mock_repositories):
    """Test replay gracefully handles malformed JSON in checkpoint_data"""
    service = ReplayService(**mock_repositories)

    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_repositories['run_repo'].get_by_id.return_value = mock_run

    mock_stage = MagicMock()
    mock_stage.stage_name = "extract"
    mock_stage.status = "completed"
    mock_stage.started_at = MagicMock()
    mock_stage.started_at.isoformat.return_value = "2026-01-01T00:00:00"
    mock_stage.completed_at = MagicMock()
    mock_stage.completed_at.isoformat.return_value = "2026-01-01T00:01:00"
    mock_stage.execution_time_ms = 60000
    mock_stage.checkpoint_data = '{invalid json'

    mock_repositories['stage_repo'].list_by_run.return_value = [mock_stage]

    # Should not raise, should log warning and continue
    timeline = await service.replay_run_execution(run_id)

    assert len(timeline.stages) == 1
    assert timeline.stages[0].outputs == {}


@pytest.mark.asyncio
async def test_replay_run_not_found(mock_repositories):
    """Test replay raises error when run not found"""
    service = ReplayService(**mock_repositories)

    run_id = uuid4()
    mock_repositories['run_repo'].get_by_id.return_value = None

    with pytest.raises(ValueError, match=f"WorkflowRun {run_id} not found"):
        await service.replay_run_execution(run_id)


@pytest.mark.asyncio
async def test_replay_multiple_stages(mock_repositories):
    """Test replay with multiple stages in execution order"""
    service = ReplayService(**mock_repositories)

    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_repositories['run_repo'].get_by_id.return_value = mock_run

    # Create three stages in order
    stages = []
    for idx, stage_name in enumerate(["extract", "retrieve", "generate"]):
        mock_stage = MagicMock()
        mock_stage.stage_name = stage_name
        mock_stage.status = "completed"
        mock_stage.started_at = MagicMock()
        mock_stage.started_at.isoformat.return_value = f"2026-01-01T00:0{idx}:00"
        mock_stage.completed_at = MagicMock()
        mock_stage.completed_at.isoformat.return_value = f"2026-01-01T00:0{idx}:30"
        mock_stage.execution_time_ms = 30000
        mock_stage.checkpoint_data = f'{{"stage": "{stage_name}"}}'
        stages.append(mock_stage)

    mock_repositories['stage_repo'].list_by_run.return_value = stages

    timeline = await service.replay_run_execution(run_id)

    assert len(timeline.stages) == 3
    assert timeline.stages[0].stage_name == "extract"
    assert timeline.stages[1].stage_name == "retrieve"
    assert timeline.stages[2].stage_name == "generate"
    assert timeline.stages[0].outputs["stage"] == "extract"


# Removed: test_replay_claim_execution_not_implemented
# This test is no longer valid as replay_claim_execution is now implemented


@pytest.mark.asyncio
async def test_replay_claim_execution(mock_repositories):
    """Test replaying execution for specific claim"""
    service = ReplayService(**mock_repositories)

    claim_id = uuid4()
    run_id = uuid4()

    # Mock claim
    mock_claim = MagicMock()
    mock_claim.id = claim_id
    mock_claim.workflow_run_id = run_id
    mock_claim.content = "Test claim"

    # Mock stages
    mock_stage1 = MagicMock()
    mock_stage1.stage_name = "extract"
    mock_stage1.status = "completed"
    mock_stage1.started_at = MagicMock()
    mock_stage1.started_at.isoformat.return_value = "2026-01-01T00:00:00"
    mock_stage1.completed_at = MagicMock()
    mock_stage1.completed_at.isoformat.return_value = "2026-01-01T00:01:00"
    mock_stage1.execution_time_ms = 60000
    mock_stage1.checkpoint_data = '{"outputs": {}}'

    mock_stage2 = MagicMock()
    mock_stage2.stage_name = "generate"
    mock_stage2.status = "completed"
    mock_stage2.started_at = MagicMock()
    mock_stage2.started_at.isoformat.return_value = "2026-01-01T00:01:00"
    mock_stage2.completed_at = MagicMock()
    mock_stage2.completed_at.isoformat.return_value = "2026-01-01T00:02:00"
    mock_stage2.execution_time_ms = 60000
    mock_stage2.checkpoint_data = f'{{"claim_ids": ["{str(claim_id)}"]}}'

    mock_repositories['lineage_service'].claim_repo.get_by_id.return_value = mock_claim
    mock_repositories['run_repo'].get_by_id.return_value = MagicMock()
    mock_repositories['stage_repo'].list_by_run.return_value = [mock_stage1, mock_stage2]
    mock_repositories['lineage_service'].lineage_link_repo.get_links_by_run.return_value = []
    mock_repositories['lineage_service'].claim_repo.list_by_run.return_value = [mock_claim]

    timeline = await service.replay_claim_execution(claim_id)

    assert timeline is not None
    assert len(timeline.stages) == 2
    assert timeline.stages[0].contributed_to_claim is False  # extract didn't contribute
    assert timeline.stages[1].contributed_to_claim is True  # generate contributed


@pytest.mark.asyncio
async def test_replay_claim_execution_claim_not_found(mock_repositories):
    """Test replay when claim doesn't exist"""
    service = ReplayService(**mock_repositories)

    claim_id = uuid4()
    mock_repositories['lineage_service'].claim_repo.get_by_id.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.replay_claim_execution(claim_id)
