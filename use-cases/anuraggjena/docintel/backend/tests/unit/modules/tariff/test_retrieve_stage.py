import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from backend.modules.tariff.schemas import TariffWorkflowState


@pytest.mark.asyncio
async def test_retrieve_stage_importable():
    from backend.modules.tariff.stages.retrieve import RetrieveStage
    assert RetrieveStage is not None


@pytest.mark.asyncio
async def test_retrieve_stage_execute_with_mock_services():
    from backend.modules.tariff.stages.retrieve import RetrieveStage
    from backend.core.retrieval.search import SearchResult

    mock_retrieval_svc = AsyncMock()
    mock_retrieval_svc.ingest_document = AsyncMock(return_value=3)
    mock_retrieval_svc.search = AsyncMock(return_value=[
        SearchResult(
            chunk_id=str(uuid4()),
            document_id=str(uuid4()),
            text="HS code 8471.30 for computers",
            score=0.91,
        )
    ])

    mock_evidence_repo = AsyncMock()
    created_evidence = MagicMock()
    created_evidence.id = uuid4()
    mock_evidence_repo.create = AsyncMock(return_value=created_evidence)

    stage = RetrieveStage(
        retrieval_service=mock_retrieval_svc,
        evidence_repository=mock_evidence_repo,
    )

    doc_id = str(uuid4())
    state = TariffWorkflowState(
        document_id=doc_id,
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_content="Product: laptop computer, HS 8471.30",
        product_spec_content="Product: laptop computer, HS 8471.30",
        product_spec_document_ids=[doc_id],
        ruling_content_map={},
    )

    result = await stage.execute(state)

    assert result["retrieve_completed"] is True
    assert len(result["retrieved_chunks"]) == 1
    assert len(result["evidence_ids"]) == 1
    # Should be called at least once (for product spec)
    assert mock_retrieval_svc.ingest_document.call_count >= 1
    mock_retrieval_svc.search.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_stage_skips_when_no_document_content():
    from backend.modules.tariff.stages.retrieve import RetrieveStage

    mock_retrieval_svc = AsyncMock()
    mock_evidence_repo = AsyncMock()

    stage = RetrieveStage(
        retrieval_service=mock_retrieval_svc,
        evidence_repository=mock_evidence_repo,
    )

    state = TariffWorkflowState(
        document_id=str(uuid4()),
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_content=None,
    )

    result = await stage.execute(state)
    assert result["retrieve_completed"] is True
    assert result["retrieved_chunks"] == []
    mock_retrieval_svc.ingest_document.assert_not_called()
