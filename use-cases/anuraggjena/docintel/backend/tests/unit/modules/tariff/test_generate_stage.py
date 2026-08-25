import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from backend.modules.tariff.stages.generate import GenerateStage
from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim
from backend.core.llm.provider import LLMResponse


@pytest.mark.asyncio
async def test_generate_stage_success():
    """Test successful report generation"""
    stage = GenerateStage()

    claims = [
        TariffClaim(
            hs_code="8471.30",
            description="Widget",
            duty_rate="0%",
            notes="Electronic"
        )
    ]

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        extracted_claims=claims
    )

    mock_report = "# Tariff Classification Report\n\nProduct: Widget\nHS Code: 8471.30"
    mock_response = LLMResponse(
        content=mock_report,
        model="llama-3.1-70b-versatile",
        tokens_used=100
    )

    with patch.object(stage.llm, 'generate', new=AsyncMock(return_value=mock_response)):
        updates = await stage.execute(state)

    assert updates["generate_completed"] is True
    assert updates["generated_report"] == mock_report


@pytest.mark.asyncio
async def test_generate_stage_multiple_claims():
    """Test report generation with multiple claims"""
    stage = GenerateStage()

    claims = [
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

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        extracted_claims=claims
    )

    mock_report = "# Tariff Classification Report\n\nMultiple products..."
    mock_response = LLMResponse(
        content=mock_report,
        model="llama-3.1-70b-versatile",
        tokens_used=200
    )

    with patch.object(stage.llm, 'generate', new=AsyncMock(return_value=mock_response)):
        updates = await stage.execute(state)

    assert updates["generate_completed"] is True
    assert updates["generated_report"] == mock_report


@pytest.mark.asyncio
async def test_generate_stage_no_claims():
    """Test generation fails with no claims"""
    stage = GenerateStage()

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1"
    )

    with pytest.raises(ValueError, match="No extracted claims"):
        await stage.execute(state)


@pytest.mark.asyncio
async def test_generate_stage_with_optional_notes():
    """Test generation handles optional notes field"""
    stage = GenerateStage()

    claims = [
        TariffClaim(
            hs_code="8471.30",
            description="Widget",
            duty_rate="0%"
            # notes is None by default
        )
    ]

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        extracted_claims=claims
    )

    mock_report = "# Tariff Classification Report\n\nProduct: Widget"
    mock_response = LLMResponse(
        content=mock_report,
        model="llama-3.1-70b-versatile",
        tokens_used=150
    )

    with patch.object(stage.llm, 'generate', new=AsyncMock(return_value=mock_response)):
        updates = await stage.execute(state)

    assert updates["generate_completed"] is True
    assert updates["generated_report"] is not None


@pytest.mark.asyncio
async def test_generate_stage_without_lineage_repo():
    """Test that stage works without lineage_link_repository (backward compatible)"""
    stage = GenerateStage(claim_repository=None, lineage_link_repository=None)

    claims = [
        TariffClaim(
            hs_code="8471.30",
            description="Widget",
            duty_rate="0%",
            notes="Electronic"
        )
    ]

    state = TariffWorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        extracted_claims=claims,
        prior_knowledge_entries=["entry-1", "entry-2"]
    )

    mock_report = "# Tariff Classification Report\n\nProduct: Widget\nHS Code: 8471.30"
    mock_response = LLMResponse(
        content=mock_report,
        model="llama-3.1-70b-versatile",
        tokens_used=100
    )

    with patch.object(stage.llm, 'generate', new=AsyncMock(return_value=mock_response)):
        updates = await stage.execute(state)

    assert updates["generate_completed"] is True
    assert updates["generated_report"] == mock_report
    assert "adopted_knowledge_entry_ids" in updates
    # Knowledge entries are identified but no links created since repo is None
    assert updates["adopted_knowledge_entry_ids"] == ["entry-1", "entry-2"]


@pytest.mark.asyncio
async def test_generate_stage_with_lineage_repo_and_knowledge():
    """Test that lineage links are created when knowledge entries exist"""
    mock_claim_repo = AsyncMock()
    mock_lineage_repo = AsyncMock()

    # Mock claim creation to return claims with IDs
    mock_claim_1 = MagicMock()
    mock_claim_1.id = uuid4()
    mock_claim_repo.create = AsyncMock(return_value=mock_claim_1)

    stage = GenerateStage(
        claim_repository=mock_claim_repo,
        lineage_link_repository=mock_lineage_repo
    )

    claims = [
        TariffClaim(
            hs_code="8471.30",
            description="Widget",
            duty_rate="0%",
            notes="Electronic"
        )
    ]

    knowledge_entry_id_1 = str(uuid4())
    knowledge_entry_id_2 = str(uuid4())

    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id="ws-1",
        document_id="doc-1",
        extracted_claims=claims,
        prior_knowledge_entries=[knowledge_entry_id_1, knowledge_entry_id_2]
    )

    mock_report = "# Tariff Classification Report\n\nProduct: Widget\nHS Code: 8471.30"
    mock_response = LLMResponse(
        content=mock_report,
        model="llama-3.1-70b-versatile",
        tokens_used=100
    )

    with patch.object(stage.llm, 'generate', new=AsyncMock(return_value=mock_response)):
        updates = await stage.execute(state)

    assert updates["generate_completed"] is True
    assert updates["generated_report"] == mock_report
    assert "adopted_knowledge_entry_ids" in updates
    assert len(updates["adopted_knowledge_entry_ids"]) == 2

    # Verify create_link was called for each (claim, knowledge_entry) pair
    assert mock_lineage_repo.create_link.call_count == 2


@pytest.mark.asyncio
async def test_generate_stage_without_knowledge_entries():
    """Test that no lineage links are created when no knowledge entries exist"""
    mock_claim_repo = AsyncMock()
    mock_lineage_repo = AsyncMock()

    # Mock claim creation
    mock_claim_1 = MagicMock()
    mock_claim_1.id = uuid4()
    mock_claim_repo.create = AsyncMock(return_value=mock_claim_1)

    stage = GenerateStage(
        claim_repository=mock_claim_repo,
        lineage_link_repository=mock_lineage_repo
    )

    claims = [
        TariffClaim(
            hs_code="8471.30",
            description="Widget",
            duty_rate="0%",
            notes="Electronic"
        )
    ]

    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id="ws-1",
        document_id="doc-1",
        extracted_claims=claims,
        prior_knowledge_entries=[]  # Empty knowledge entries
    )

    mock_report = "# Tariff Classification Report\n\nProduct: Widget\nHS Code: 8471.30"
    mock_response = LLMResponse(
        content=mock_report,
        model="llama-3.1-70b-versatile",
        tokens_used=100
    )

    with patch.object(stage.llm, 'generate', new=AsyncMock(return_value=mock_response)):
        updates = await stage.execute(state)

    assert updates["generate_completed"] is True
    assert "adopted_knowledge_entry_ids" in updates
    assert updates["adopted_knowledge_entry_ids"] == []

    # Verify create_link was NOT called
    mock_lineage_repo.create_link.assert_not_called()


@pytest.mark.asyncio
async def test_generate_stage_lineage_link_creation_error_handling():
    """Test that lineage link creation errors are logged but don't fail the stage"""
    mock_claim_repo = AsyncMock()
    mock_lineage_repo = AsyncMock()

    # Mock claim creation
    mock_claim_1 = MagicMock()
    mock_claim_1.id = uuid4()
    mock_claim_repo.create = AsyncMock(return_value=mock_claim_1)

    # Mock lineage link creation to fail
    mock_lineage_repo.create_link = AsyncMock(side_effect=Exception("DB connection error"))

    stage = GenerateStage(
        claim_repository=mock_claim_repo,
        lineage_link_repository=mock_lineage_repo
    )

    claims = [
        TariffClaim(
            hs_code="8471.30",
            description="Widget",
            duty_rate="0%",
            notes="Electronic"
        )
    ]

    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id="ws-1",
        document_id="doc-1",
        extracted_claims=claims,
        prior_knowledge_entries=[str(uuid4())]
    )

    mock_report = "# Tariff Classification Report\n\nProduct: Widget\nHS Code: 8471.30"
    mock_response = LLMResponse(
        content=mock_report,
        model="llama-3.1-70b-versatile",
        tokens_used=100
    )

    with patch.object(stage.llm, 'generate', new=AsyncMock(return_value=mock_response)):
        # Should not raise exception even if lineage link creation fails
        updates = await stage.execute(state)

    assert updates["generate_completed"] is True
    assert updates["generated_report"] == mock_report
