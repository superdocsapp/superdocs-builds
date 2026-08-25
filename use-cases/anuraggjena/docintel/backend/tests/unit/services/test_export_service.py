"""Tests for export service"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from backend.services.export import ExportService
from backend.models.export import Export
from backend.models.review import Review
from backend.models.workspace import Workspace
from backend.models.claim import Claim


@pytest.fixture
def mock_repositories():
    """Create mock repositories"""
    export_repo = AsyncMock()
    review_repo = AsyncMock()
    claim_repo = AsyncMock()
    workspace_repo = AsyncMock()
    document_repo = AsyncMock()
    run_repo = AsyncMock()
    stage_repo = AsyncMock()

    # Default: no stages (so _get_generated_report returns "")
    stage_repo.list_by_run = AsyncMock(return_value=[])
    run_repo.get_by_id = AsyncMock(return_value=None)

    return {
        "export": export_repo,
        "review": review_repo,
        "claim": claim_repo,
        "workspace": workspace_repo,
        "document": document_repo,
        "run": run_repo,
        "stage": stage_repo,
    }


@pytest.fixture
def mock_storage():
    """Create mock storage backend"""
    storage = MagicMock()
    storage.save.return_value = "workspace_id/export_file.docx"
    storage.read.return_value = b"mock file content"
    return storage


@pytest.fixture
def export_service(mock_repositories, mock_storage):
    """Create export service with mocked dependencies"""
    return ExportService(
        export_repository=mock_repositories["export"],
        review_repository=mock_repositories["review"],
        claim_repository=mock_repositories["claim"],
        workspace_repository=mock_repositories["workspace"],
        document_repository=mock_repositories["document"],
        run_repository=mock_repositories["run"],
        stage_repository=mock_repositories["stage"],
        storage=mock_storage
    )


@pytest.fixture
def sample_review():
    """Create sample review"""
    review = MagicMock(spec=Review)
    review.id = uuid4()
    review.workspace_id = str(uuid4())
    review.workflow_run_id = str(uuid4())
    review.status = "approved"
    return review


@pytest.fixture
def sample_workspace():
    """Create sample workspace"""
    workspace = MagicMock(spec=Workspace)
    workspace.id = uuid4()
    workspace.name = "Test Workspace"
    workspace.owner_id = "user-123"
    return workspace


@pytest.fixture
def sample_claims():
    """Create sample claims"""
    claim1 = MagicMock(spec=Claim)
    claim1.id = uuid4()
    claim1.content = '{"hs_code": "8471.30", "description": "Laptops", "duty_rate": "0%"}'
    claim1.status = "approved"

    claim2 = MagicMock(spec=Claim)
    claim2.id = uuid4()
    claim2.content = '{"hs_code": "8471.41", "description": "Computers", "duty_rate": "0%"}'
    claim2.status = "pending"

    return [claim1, claim2]


@pytest.mark.asyncio
async def test_export_review_as_docx_success(
    export_service,
    mock_repositories,
    mock_storage,
    sample_review,
    sample_workspace,
    sample_claims
):
    """Test successful export of review as DOCX"""
    # Setup mocks
    mock_repositories["review"].get_by_id.return_value = sample_review
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace
    mock_repositories["claim"].list_by_review.return_value = sample_claims

    export_id = uuid4()
    mock_export = MagicMock(spec=Export)
    mock_export.id = export_id
    mock_export.workspace_id = sample_review.workspace_id
    mock_export.filename = f"tariff_report_{sample_review.id}.docx"
    mock_repositories["export"].create.return_value = mock_export

    # Execute
    with patch("backend.services.export.DOCXGenerator") as mock_generator_class:
        mock_generator = MagicMock()
        mock_generator.generate_tariff_report.return_value = b"mock docx content"
        mock_generator_class.return_value = mock_generator

        result = await export_service.export_review_as_docx(
            review_id=sample_review.id,
            exported_by="user-123"
        )

    # Verify
    assert result == mock_export
    mock_repositories["review"].get_by_id.assert_called_once_with(sample_review.id)
    mock_repositories["claim"].list_by_review.assert_called_once_with(sample_review.id)
    mock_storage.save.assert_called_once()
    mock_repositories["export"].create.assert_called_once()

    # Verify create was called with correct parameters
    create_call = mock_repositories["export"].create.call_args
    assert create_call.kwargs["workspace_id"] == sample_review.workspace_id
    assert create_call.kwargs["review_id"] == str(sample_review.id)
    assert create_call.kwargs["format"] == "docx"
    assert create_call.kwargs["exported_by"] == "user-123"


@pytest.mark.asyncio
async def test_export_review_as_docx_review_not_found(
    export_service,
    mock_repositories
):
    """Test export fails when review not found"""
    mock_repositories["review"].get_by_id.return_value = None

    with pytest.raises(ValueError, match="Review .* not found"):
        await export_service.export_review_as_docx(uuid4())


@pytest.mark.asyncio
async def test_export_review_as_docx_workspace_not_found(
    export_service,
    mock_repositories,
    sample_review
):
    """Test export fails when workspace not found"""
    mock_repositories["review"].get_by_id.return_value = sample_review
    mock_repositories["workspace"].get_by_id.return_value = None

    with pytest.raises(ValueError, match="Workspace .* not found"):
        await export_service.export_review_as_docx(sample_review.id)


@pytest.mark.asyncio
async def test_export_review_as_docx_with_empty_claims(
    export_service,
    mock_repositories,
    mock_storage,
    sample_review,
    sample_workspace
):
    """Test export with no claims"""
    mock_repositories["review"].get_by_id.return_value = sample_review
    mock_repositories["workspace"].get_by_id.return_value = sample_workspace
    mock_repositories["claim"].list_by_review.return_value = []

    mock_export = MagicMock(spec=Export)
    mock_export.id = uuid4()
    mock_repositories["export"].create.return_value = mock_export

    with patch("backend.services.export.DOCXGenerator") as mock_generator_class:
        mock_generator = MagicMock()
        mock_generator.generate_tariff_report.return_value = b"mock docx content"
        mock_generator_class.return_value = mock_generator

        result = await export_service.export_review_as_docx(sample_review.id)

    assert result == mock_export
    # Verify generate_tariff_report was called with empty claims list
    call_args = mock_generator.generate_tariff_report.call_args
    assert call_args.kwargs["claims"] == []


@pytest.mark.asyncio
async def test_get_export(export_service, mock_repositories):
    """Test getting export by ID"""
    export_id = uuid4()
    mock_export = MagicMock(spec=Export)
    mock_export.id = export_id
    mock_repositories["export"].get_by_id.return_value = mock_export

    result = await export_service.get_export(export_id)

    assert result == mock_export
    mock_repositories["export"].get_by_id.assert_called_once_with(export_id)


@pytest.mark.asyncio
async def test_get_export_not_found(export_service, mock_repositories):
    """Test getting non-existent export"""
    mock_repositories["export"].get_by_id.return_value = None

    result = await export_service.get_export(uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_get_export_content_success(
    export_service,
    mock_repositories,
    mock_storage
):
    """Test getting export file content"""
    export_id = uuid4()
    mock_export = MagicMock(spec=Export)
    mock_export.id = export_id
    mock_export.storage_path = "workspace/file.docx"
    mock_repositories["export"].get_by_id.return_value = mock_export

    mock_storage.read.return_value = b"file content"

    result = await export_service.get_export_content(export_id)

    assert result == b"file content"
    mock_storage.read.assert_called_once_with("workspace/file.docx")


@pytest.mark.asyncio
async def test_get_export_content_not_found(
    export_service,
    mock_repositories
):
    """Test getting content for non-existent export"""
    mock_repositories["export"].get_by_id.return_value = None

    result = await export_service.get_export_content(uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_get_export_content_storage_error(
    export_service,
    mock_repositories,
    mock_storage
):
    """Test handling storage error when getting content"""
    export_id = uuid4()
    mock_export = MagicMock(spec=Export)
    mock_export.id = export_id
    mock_export.storage_path = "workspace/file.docx"
    mock_repositories["export"].get_by_id.return_value = mock_export

    mock_storage.read.side_effect = Exception("Storage error")

    result = await export_service.get_export_content(export_id)

    assert result is None


@pytest.mark.asyncio
async def test_list_workspace_exports(export_service, mock_repositories):
    """Test listing exports for a workspace"""
    workspace_id = uuid4()
    mock_exports = [
        MagicMock(spec=Export, id=uuid4()),
        MagicMock(spec=Export, id=uuid4()),
    ]
    mock_repositories["export"].list_by_workspace.return_value = mock_exports

    result = await export_service.list_workspace_exports(workspace_id)

    assert result == mock_exports
    mock_repositories["export"].list_by_workspace.assert_called_once_with(workspace_id)
