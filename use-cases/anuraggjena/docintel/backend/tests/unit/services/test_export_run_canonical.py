"""Tests for canonical run-based export (MemoSection → DOCX)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.services.export import ExportService
from backend.models.export import Export
from backend.models.workflow import WorkflowRun
from backend.models.workspace import Workspace
from backend.models.memo_section import MemoSection


@pytest.fixture
def mock_repositories():
    """Create mock repositories for canonical export."""
    export_repo = AsyncMock()
    review_repo = AsyncMock()
    claim_repo = AsyncMock()
    workspace_repo = AsyncMock()
    document_repo = AsyncMock()
    run_repo = AsyncMock()
    stage_repo = AsyncMock()
    memo_section_repo = AsyncMock()

    # Default: no stages
    stage_repo.list_by_run = AsyncMock(return_value=[])

    return {
        "export": export_repo,
        "review": review_repo,
        "claim": claim_repo,
        "workspace": workspace_repo,
        "document": document_repo,
        "run": run_repo,
        "stage": stage_repo,
        "memo_section": memo_section_repo,
    }


@pytest.fixture
def mock_storage():
    """Create mock storage backend."""
    storage = MagicMock()
    storage.save.return_value = "workspace_id/export_file.docx"
    storage.read.return_value = b"mock file content"
    return storage


@pytest.fixture
def export_service_with_memo_repo(mock_repositories, mock_storage):
    """Create export service WITH memo section repository."""
    return ExportService(
        export_repository=mock_repositories["export"],
        review_repository=mock_repositories["review"],
        claim_repository=mock_repositories["claim"],
        workspace_repository=mock_repositories["workspace"],
        document_repository=mock_repositories["document"],
        run_repository=mock_repositories["run"],
        stage_repository=mock_repositories["stage"],
        storage=mock_storage,
        memo_section_repository=mock_repositories["memo_section"],
    )


@pytest.fixture
def export_service_without_memo_repo(mock_repositories, mock_storage):
    """Create export service WITHOUT memo section repository."""
    return ExportService(
        export_repository=mock_repositories["export"],
        review_repository=mock_repositories["review"],
        claim_repository=mock_repositories["claim"],
        workspace_repository=mock_repositories["workspace"],
        document_repository=mock_repositories["document"],
        run_repository=mock_repositories["run"],
        stage_repository=mock_repositories["stage"],
        storage=mock_storage,
        memo_section_repository=None,  # No memo repo
    )


@pytest.fixture
def sample_run():
    """Create sample completed workflow run."""
    run = MagicMock(spec=WorkflowRun)
    run.id = uuid4()
    run.status = "completed"
    run.workflow_type = "tariff_classification"
    return run


@pytest.fixture
def sample_workspace():
    """Create sample workspace."""
    workspace = MagicMock(spec=Workspace)
    workspace.id = uuid4()
    workspace.name = "Test Workspace"
    return workspace


@pytest.fixture
def sample_memo_sections():
    """Create sample memo sections."""
    section1 = MagicMock(spec=MemoSection)
    section1.id = uuid4()
    section1.title = "Product Description"
    section1.section_order = 1
    section1.section_type = "product_description"
    section1.content = "This product is made of aluminum and measures 10x10x10 cm."
    section1.analyst_reasoning = "Based on specification document."
    section1.source_attribution = [
        {
            "document_id": "doc-123",
            "page": 5,
            "excerpt": "Material: aluminum"
        }
    ]
    section1.structured_data = None
    section1.status = "completed"

    section2 = MagicMock(spec=MemoSection)
    section2.id = uuid4()
    section2.title = "Recommended Classification"
    section2.section_order = 2
    section2.section_type = "recommended_classification"
    section2.content = "Classification recommendation follows."
    section2.analyst_reasoning = "Based on material and use."
    section2.source_attribution = []
    section2.structured_data = {
        "recommendation": {
            "hs_code": "7326.90.8588",
            "description": "Other articles of iron or steel",
            "reasoning": "Aluminum construction matches this category",
        }
    }
    section2.status = "completed"

    return [section1, section2]


@pytest.mark.asyncio
async def test_export_run_as_docx_with_memo_sections(
    export_service_with_memo_repo,
    mock_repositories,
    mock_storage,
    sample_run,
    sample_workspace,
    sample_memo_sections,
):
    """Test successful canonical export with MemoSections."""
    from unittest.mock import patch

    # Setup mocks
    mock_repositories["run"].get_by_id.return_value = sample_run
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace
    mock_repositories["memo_section"].list_by_run.return_value = sample_memo_sections

    export_id = uuid4()
    mock_export = MagicMock(spec=Export)
    mock_export.id = export_id
    mock_repositories["export"].create.return_value = mock_export

    # Execute
    with patch("backend.services.export.DOCXGenerator") as mock_generator_class:
        mock_generator = MagicMock()
        mock_generator.generate_tariff_memo.return_value = b"canonical memo docx"
        mock_generator_class.return_value = mock_generator

        result = await export_service_with_memo_repo.export_run_as_docx(
            run_id=sample_run.id,
            workspace_id=sample_workspace.id,
        )

    # Verify
    assert result == mock_export
    mock_repositories["memo_section"].list_by_run.assert_called_once_with(sample_run.id)

    # Verify generate_tariff_memo was called (canonical path)
    mock_generator.generate_tariff_memo.assert_called_once()
    call_args = mock_generator.generate_tariff_memo.call_args
    assert call_args.kwargs["workspace_name"] == "Test Workspace"
    assert len(call_args.kwargs["sections"]) == 2

    # Verify generate_tariff_report was NOT called
    assert not mock_generator.generate_tariff_report.called


@pytest.mark.asyncio
async def test_export_run_as_docx_without_memo_sections_fails(
    export_service_with_memo_repo,
    mock_repositories,
    sample_run,
    sample_workspace,
):
    """Test export fails when no MemoSections exist."""
    mock_repositories["run"].get_by_id.return_value = sample_run
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace
    mock_repositories["memo_section"].list_by_run.return_value = []  # No sections

    with pytest.raises(ValueError, match="no MemoSections exist"):
        await export_service_with_memo_repo.export_run_as_docx(
            run_id=sample_run.id,
            workspace_id=sample_workspace.id,
        )


@pytest.mark.asyncio
async def test_export_run_as_docx_without_memo_repo_fails(
    export_service_without_memo_repo,
    mock_repositories,
    sample_run,
    sample_workspace,
):
    """Test export fails when MemoSection repository not available."""
    mock_repositories["run"].get_by_id.return_value = sample_run
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace

    with pytest.raises(ValueError, match="MemoSection repository not available"):
        await export_service_without_memo_repo.export_run_as_docx(
            run_id=sample_run.id,
            workspace_id=sample_workspace.id,
        )


@pytest.mark.asyncio
async def test_export_run_as_docx_with_only_skipped_sections_fails(
    export_service_with_memo_repo,
    mock_repositories,
    sample_run,
    sample_workspace,
):
    """Test export fails when all sections are skipped."""
    skipped_section = MagicMock(spec=MemoSection)
    skipped_section.status = "skipped"
    skipped_section.content = "Some content"

    mock_repositories["run"].get_by_id.return_value = sample_run
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace
    mock_repositories["memo_section"].list_by_run.return_value = [skipped_section]

    with pytest.raises(ValueError, match="all .* MemoSection.*are marked as skipped"):
        await export_service_with_memo_repo.export_run_as_docx(
            run_id=sample_run.id,
            workspace_id=sample_workspace.id,
        )


@pytest.mark.asyncio
async def test_export_run_as_docx_with_empty_content_fails(
    export_service_with_memo_repo,
    mock_repositories,
    sample_run,
    sample_workspace,
):
    """Test export fails when all sections have empty content."""
    empty_section = MagicMock(spec=MemoSection)
    empty_section.status = "completed"
    empty_section.content = ""  # Empty

    mock_repositories["run"].get_by_id.return_value = sample_run
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace
    mock_repositories["memo_section"].list_by_run.return_value = [empty_section]

    with pytest.raises(ValueError, match="all have empty content"):
        await export_service_with_memo_repo.export_run_as_docx(
            run_id=sample_run.id,
            workspace_id=sample_workspace.id,
        )


@pytest.mark.asyncio
async def test_export_run_as_docx_run_not_completed_fails(
    export_service_with_memo_repo,
    mock_repositories,
    sample_run,
    sample_workspace,
):
    """Test export fails when run is not completed."""
    sample_run.status = "running"

    mock_repositories["run"].get_by_id.return_value = sample_run
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace

    with pytest.raises(ValueError, match="is not completed"):
        await export_service_with_memo_repo.export_run_as_docx(
            run_id=sample_run.id,
            workspace_id=sample_workspace.id,
        )


@pytest.mark.asyncio
async def test_export_run_as_docx_enhances_source_attribution(
    export_service_with_memo_repo,
    mock_repositories,
    mock_storage,
    sample_run,
    sample_workspace,
    sample_memo_sections,
):
    """Test that document metadata is resolved and added to source attribution."""
    from unittest.mock import patch

    # Use valid UUID for document ID
    doc_uuid = uuid4()
    doc_uuid_str = str(doc_uuid)

    # Update sample sections to use valid UUID
    sample_memo_sections[0].source_attribution = [
        {
            "document_id": doc_uuid_str,
            "page": 5,
            "excerpt": "Material: aluminum"
        }
    ]

    mock_repositories["run"].get_by_id.return_value = sample_run
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace
    mock_repositories["memo_section"].list_by_run.return_value = sample_memo_sections

    # Mock document lookup
    mock_doc = MagicMock()
    mock_doc.id = doc_uuid
    mock_doc.filename = "product_spec.pdf"
    mock_doc.document_role = "product_spec"
    mock_repositories["document"].get_by_id.return_value = mock_doc

    mock_export = MagicMock(spec=Export)
    mock_export.id = uuid4()
    mock_repositories["export"].create.return_value = mock_export

    with patch("backend.services.export.DOCXGenerator") as mock_generator_class:
        mock_generator = MagicMock()
        mock_generator.generate_tariff_memo.return_value = b"memo with enhanced citations"
        mock_generator_class.return_value = mock_generator

        await export_service_with_memo_repo.export_run_as_docx(
            run_id=sample_run.id,
            workspace_id=sample_workspace.id,
            document_ids=[doc_uuid_str],
        )

    # Verify enhanced attribution was passed
    call_args = mock_generator.generate_tariff_memo.call_args
    sections = call_args.kwargs["sections"]

    # First section should have enhanced attribution
    first_section = sections[0]
    attribution = first_section["source_attribution"][0]
    assert "document_name" in attribution
    assert attribution["document_name"] == "product_spec.pdf"
