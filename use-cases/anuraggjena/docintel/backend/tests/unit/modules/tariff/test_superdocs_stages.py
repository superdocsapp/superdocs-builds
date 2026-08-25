import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.modules.tariff.stages.superdocs_instruction import SuperDocsInstructionStage
from backend.modules.tariff.stages.superdocs_export import SuperDocsExportStage
from backend.modules.tariff.schemas import TariffWorkflowState


def _base_state(**kwargs):
    defaults = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "superdocs_session_id": "sess-123",
    }
    defaults.update(kwargs)
    return TariffWorkflowState(**defaults)


@pytest.mark.asyncio
async def test_instruction_stage_submits_structured_memo():
    mock_client = AsyncMock()
    mock_job = MagicMock(job_id="job-456")
    mock_client.chat_async.return_value = mock_job

    mock_builder = MagicMock()
    mock_builder.build_structured_memo_instruction.return_value = "memo instruction"

    mock_section = MagicMock(
        title="Product Overview",
        section_order=2,
        section_type="product_overview",
        content="Overview text",
        analyst_reasoning="Analysis",
        source_attribution=[],
        structured_data=None,
        status="pending",
    )
    mock_section_repo = AsyncMock()
    mock_section_repo.list_by_run.return_value = [mock_section]

    stage = SuperDocsInstructionStage(
        superdocs_client=mock_client,
        instruction_builder=mock_builder,
        memo_section_repository=mock_section_repo,
        document_repository=AsyncMock(),
    )
    result = await stage.execute(_base_state())
    assert result["superdocs_job_id"] == "job-456"
    mock_client.chat_async.assert_called_once()


@pytest.mark.asyncio
async def test_export_stage_calls_canonical_export_service():
    mock_export_service = MagicMock()
    mock_export_service.export_run_as_docx = AsyncMock()
    mock_export = MagicMock(id=uuid4(), filename="Test_Tariff_Classification.docx")
    mock_export_service.export_run_as_docx.return_value = mock_export

    stage = SuperDocsExportStage(export_service=mock_export_service)
    state = _base_state(superdocs_approval_completed=True)
    result = await stage.execute(state)
    mock_export_service.export_run_as_docx.assert_called_once()
    assert result["export_completed"] is True
    assert result["export_id"] == str(mock_export.id)


@pytest.mark.asyncio
async def test_export_stage_calls_fallback_export_run():
    class LegacyExportService:
        def __init__(self):
            self.export_run = AsyncMock()

    mock_export_service = LegacyExportService()
    mock_export = MagicMock(id=uuid4(), filename="Legacy.docx")
    mock_export_service.export_run.return_value = mock_export

    stage = SuperDocsExportStage(export_service=mock_export_service)
    state = _base_state(superdocs_approval_completed=True)
    result = await stage.execute(state)
    mock_export_service.export_run.assert_called_once()
    assert result["export_completed"] is True
    assert result["export_id"] == str(mock_export.id)
