import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.modules.tariff.stages.extract import ExtractStage, TariffClaimsResponse
from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim


@pytest.mark.asyncio
async def test_extract_stage_success():
    """Test successful extraction of tariff claims"""
    stage = ExtractStage()

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        document_content="Product: Widget\nHS Code: 8471.30\nDuty Rate: 0%"
    )

    # Mock LLM response with proper Pydantic model
    mock_result = TariffClaimsResponse(
        claims=[
            TariffClaim(
                hs_code="8471.30",
                description="Widget",
                duty_rate="0%",
                notes="Electronic component"
            )
        ]
    )

    with patch.object(stage.llm, 'generate_structured', new=AsyncMock(return_value=mock_result)):
        updates = await stage.execute(state)

    assert updates["extract_completed"] is True
    assert len(updates["extracted_claims"]) == 1
    assert updates["extracted_claims"][0].hs_code == "8471.30"


@pytest.mark.asyncio
async def test_extract_stage_multiple_claims():
    """Test extraction of multiple tariff claims"""
    stage = ExtractStage()

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        document_content="Multiple products document"
    )

    mock_result = TariffClaimsResponse(
        claims=[
            TariffClaim(
                hs_code="8471.30",
                description="Widget",
                duty_rate="0%"
            ),
            TariffClaim(
                hs_code="8471.41",
                description="Gadget",
                duty_rate="2.5%"
            )
        ]
    )

    with patch.object(stage.llm, 'generate_structured', new=AsyncMock(return_value=mock_result)):
        updates = await stage.execute(state)

    assert updates["extract_completed"] is True
    assert len(updates["extracted_claims"]) == 2
    assert updates["extracted_claims"][0].hs_code == "8471.30"
    assert updates["extracted_claims"][1].hs_code == "8471.41"


@pytest.mark.asyncio
async def test_extract_stage_no_content():
    """Test extraction fails with no document content"""
    stage = ExtractStage()

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1"
    )

    with pytest.raises(ValueError, match="No document content"):
        await stage.execute(state)


@pytest.mark.asyncio
async def test_extract_stage_empty_claims():
    """Test extraction with no claims found"""
    stage = ExtractStage()

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        document_content="No tariff information here"
    )

    mock_result = TariffClaimsResponse(claims=[])

    with patch.object(stage.llm, 'generate_structured', new=AsyncMock(return_value=mock_result)):
        updates = await stage.execute(state)

    assert updates["extract_completed"] is True
    assert len(updates["extracted_claims"]) == 0
