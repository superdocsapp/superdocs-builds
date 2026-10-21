import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.core.quality_gate.stage import QualityGateStage
from backend.core.quality_gate.checks import BaseCheck, CheckSeverity, CheckStatus


class PassCheck(BaseCheck):
    name = "pass_check"
    severity = CheckSeverity.INFO
    blocking = False

    async def run(self, state, config):
        return self.passed("ok")


class BlockingFailCheck(BaseCheck):
    name = "blocking_fail"
    severity = CheckSeverity.ERROR
    blocking = True

    async def run(self, state, config):
        return self.failed("bad data")


@pytest.mark.asyncio
async def test_stage_runs_checks_and_returns_status():
    stage = QualityGateStage(checks=[PassCheck()])
    result = await stage.execute({"claims": []})
    assert result["quality_gate_status"] == "passed"
    assert result["quality_gate_details"] is not None


@pytest.mark.asyncio
async def test_stage_skips_when_disabled():
    mock_config_repo = AsyncMock()
    mock_config = MagicMock()
    mock_config.enabled = False
    mock_config.block_on_failure = False
    mock_config.checks_config = {}
    mock_config_repo.get_by_workspace = AsyncMock(return_value=mock_config)

    stage = QualityGateStage(checks=[PassCheck()], config_repository=mock_config_repo)
    result = await stage.execute({"workspace_id": "00000000-0000-0000-0000-000000000001"})
    assert result["quality_gate_status"] == "skipped"


@pytest.mark.asyncio
async def test_stage_raises_on_blocking_failure_when_configured():
    mock_config_repo = AsyncMock()
    mock_config = MagicMock()
    mock_config.enabled = True
    mock_config.block_on_failure = True
    mock_config.checks_config = {}
    mock_config.id = "cfg-1"
    mock_config_repo.get_by_workspace = AsyncMock(return_value=mock_config)

    stage = QualityGateStage(
        checks=[BlockingFailCheck()],
        config_repository=mock_config_repo,
    )

    with pytest.raises(ValueError, match="Quality gate blocked"):
        await stage.execute({"workspace_id": "00000000-0000-0000-0000-000000000002", "claims": [{"content": "c1"}, {"content": "c2"}]})


@pytest.mark.asyncio
async def test_stage_does_not_raise_when_not_block_on_failure():
    """Blocking check fails but block_on_failure=False — should not raise."""
    stage = QualityGateStage(checks=[BlockingFailCheck()])
    result = await stage.execute({"claims": []})
    # No exception, status is failed or skipped
    assert "quality_gate_status" in result


@pytest.mark.asyncio
async def test_stage_persists_result():
    mock_result_repo = AsyncMock()
    mock_result_repo.create = AsyncMock(return_value=MagicMock())

    stage = QualityGateStage(
        checks=[PassCheck()],
        result_repository=mock_result_repo,
    )
    await stage.execute({"workflow_run_id": "run-1", "claims": []})
    assert mock_result_repo.create.called
