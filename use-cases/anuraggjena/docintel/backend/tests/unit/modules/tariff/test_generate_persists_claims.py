import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim


@pytest.mark.asyncio
async def test_generate_stage_persists_claims():
    from backend.modules.tariff.stages.generate import GenerateStage

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=MagicMock(content="Generated tariff memo text"))
    mock_claim_repo = AsyncMock()
    created_claim = MagicMock()
    created_claim.id = uuid4()
    mock_claim_repo.create = AsyncMock(return_value=created_claim)

    stage = GenerateStage(claim_repository=mock_claim_repo)
    stage.llm = mock_llm

    state = TariffWorkflowState(
        document_id=str(uuid4()),
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_content="test",
        extracted_claims=[
            TariffClaim(hs_code="8471.30", description="Laptop", duty_rate="0%"),
        ],
    )

    result = await stage.execute(state)

    assert result["generate_completed"] is True
    assert "generated_report" in result
    assert len(result["claim_ids"]) == 1
    mock_claim_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_generate_stage_works_without_claim_repo():
    """Backward compatibility: GenerateStage still works when no claim_repo provided."""
    from backend.modules.tariff.stages.generate import GenerateStage

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=MagicMock(content="Generated memo"))

    stage = GenerateStage(claim_repository=None)
    stage.llm = mock_llm

    state = TariffWorkflowState(
        document_id=str(uuid4()),
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_content="test",
        extracted_claims=[
            TariffClaim(hs_code="8471.30", description="Laptop", duty_rate="0%"),
        ],
    )

    result = await stage.execute(state)
    assert result["generate_completed"] is True
    assert result["claim_ids"] == []
