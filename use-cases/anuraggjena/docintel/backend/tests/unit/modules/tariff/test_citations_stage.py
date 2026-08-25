import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim


@pytest.mark.asyncio
async def test_citations_stage_importable():
    from backend.modules.tariff.stages.citations import CitationBuilderStage
    assert CitationBuilderStage is not None


@pytest.mark.asyncio
async def test_citations_stage_executes():
    from backend.modules.tariff.stages.citations import CitationBuilderStage
    from backend.core.retrieval.citations import CitationBuilder

    mock_builder = AsyncMock(spec=CitationBuilder)
    mock_builder.build = AsyncMock(return_value=[str(uuid4()), str(uuid4())])

    stage = CitationBuilderStage(citation_builder=mock_builder)

    state = TariffWorkflowState(
        document_id=str(uuid4()),
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_content="test",
        extracted_claims=[
            TariffClaim(hs_code="8471.30", description="Laptop", duty_rate="0%"),
        ],
        claim_ids=[str(uuid4())],
        evidence_ids=[str(uuid4())],
        retrieved_chunks=[{"chunk_id": "c1", "text": "relevant", "score": 0.9}],
    )

    result = await stage.execute(state)
    assert result["citations_completed"] is True
    assert len(result["citation_ids"]) == 2
    mock_builder.build.assert_called_once()
