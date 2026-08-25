"""Tests for exports API endpoints"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4, UUID
from datetime import datetime, timezone

from fastapi import HTTPException
from backend.api.v1.exports import (
    create_export,
    get_export,
    download_export,
    list_workspace_exports,
    ExportCreate,
    ExportResponse,
)
from backend.models.export import Export
from backend.models.workspace import Workspace


@pytest.fixture
def mock_export_service():
    """Create mock export service"""
    return AsyncMock()


@pytest.fixture
def sample_export():
    """Create sample export"""
    export = MagicMock(spec=Export)
    export.id = uuid4()
    export.workspace_id = uuid4()
    export.workflow_run_id = uuid4()
    export.review_id = uuid4()
    export.filename = "tariff_report.docx"
    export.format = "docx"
    export.file_size = 12345
    export.exported_by = "user-123"
    export.storage_path = "workspace/file.docx"
    export.created_at = datetime.now(timezone.utc)
    return export


@pytest.fixture
def mock_workspace():
    ws = MagicMock(spec=Workspace)
    ws.id = uuid4()
    return ws


@pytest.mark.asyncio
async def test_create_export_success(mock_export_service, sample_export):
    """Test successful export creation"""
    export_data = ExportCreate(
        review_id=sample_export.review_id,
        exported_by="user-123"
    )

    mock_export_service.export_review_as_docx.return_value = sample_export

    result = await create_export(export_data, mock_export_service)

    assert result == sample_export
    mock_export_service.export_review_as_docx.assert_called_once()
    call_args = mock_export_service.export_review_as_docx.call_args
    assert call_args.kwargs["review_id"] == sample_export.review_id
    assert call_args.kwargs["exported_by"] == "user-123"


@pytest.mark.asyncio
async def test_create_export_review_not_found(mock_export_service):
    """Test export creation fails when review not found"""
    export_data = ExportCreate(review_id=uuid4())

    mock_export_service.export_review_as_docx.side_effect = ValueError("Review not found")

    with pytest.raises(HTTPException) as exc_info:
        await create_export(export_data, mock_export_service)

    assert exc_info.value.status_code == 404
    assert "Review not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_export_workspace_not_found(mock_export_service):
    """Test export creation fails when workspace not found"""
    export_data = ExportCreate(review_id=uuid4())

    mock_export_service.export_review_as_docx.side_effect = ValueError("Workspace not found")

    with pytest.raises(HTTPException) as exc_info:
        await create_export(export_data, mock_export_service)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_create_export_without_exported_by(mock_export_service, sample_export):
    """Test export creation without exported_by field"""
    export_data = ExportCreate(review_id=sample_export.review_id)

    mock_export_service.export_review_as_docx.return_value = sample_export

    result = await create_export(export_data, mock_export_service)

    assert result == sample_export
    call_args = mock_export_service.export_review_as_docx.call_args
    assert call_args.kwargs["exported_by"] is None


@pytest.mark.asyncio
async def test_get_export_success(mock_export_service, sample_export):
    """Test successful retrieval of export metadata"""
    export_id = sample_export.id
    result = await get_export(export_id, export=sample_export, service=mock_export_service)
    assert result == sample_export


@pytest.mark.asyncio
async def test_download_export_success(mock_export_service, sample_export):
    """Test successful export download"""
    export_id = sample_export.id
    file_content = b"mock docx file content"

    mock_export_service.get_export_content.return_value = file_content

    result = await download_export(export_id, export=sample_export, service=mock_export_service)

    # Verify response
    assert result.body == file_content
    assert result.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert f'attachment; filename="{sample_export.filename}"' in result.headers["Content-Disposition"]

    mock_export_service.get_export_content.assert_called_once_with(export_id)


@pytest.mark.asyncio
async def test_download_export_content_unavailable(mock_export_service, sample_export):
    """Test downloading export when content is unavailable"""
    export_id = sample_export.id
    mock_export_service.get_export_content.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await download_export(export_id, export=sample_export, service=mock_export_service)

    assert exc_info.value.status_code == 500
    assert "Failed to retrieve export content" in exc_info.value.detail


@pytest.mark.asyncio
async def test_list_workspace_exports_success(mock_export_service, mock_workspace):
    """Test listing exports for a workspace"""
    workspace_id = mock_workspace.id
    mock_exports = [
        MagicMock(
            spec=Export,
            id=uuid4(),
            workspace_id=workspace_id,
            filename="report1.docx",
            format="docx",
            file_size=1000,
            created_at=datetime.now(timezone.utc)
        ),
        MagicMock(
            spec=Export,
            id=uuid4(),
            workspace_id=workspace_id,
            filename="report2.docx",
            format="docx",
            file_size=2000,
            created_at=datetime.now(timezone.utc)
        ),
    ]

    mock_export_service.list_workspace_exports.return_value = mock_exports

    result = await list_workspace_exports(workspace_id, workspace=mock_workspace, service=mock_export_service)

    assert result == mock_exports
    assert len(result) == 2
    mock_export_service.list_workspace_exports.assert_called_once_with(workspace_id)


@pytest.mark.asyncio
async def test_list_workspace_exports_empty(mock_export_service, mock_workspace):
    """Test listing exports for workspace with no exports"""
    workspace_id = mock_workspace.id
    mock_export_service.list_workspace_exports.return_value = []

    result = await list_workspace_exports(workspace_id, workspace=mock_workspace, service=mock_export_service)

    assert result == []
    mock_export_service.list_workspace_exports.assert_called_once_with(workspace_id)


@pytest.mark.asyncio
async def test_export_response_model():
    """Test ExportResponse model serialization"""
    raw_id = uuid4()
    raw_ws_id = uuid4()
    raw_run_id = uuid4()
    raw_rev_id = uuid4()
    now = datetime.now(timezone.utc)

    export_obj = MagicMock(spec=Export)
    export_obj.id = raw_id
    export_obj.workspace_id = raw_ws_id
    export_obj.workflow_run_id = raw_run_id
    export_obj.review_id = raw_rev_id
    export_obj.filename = "report.docx"
    export_obj.format = "docx"
    export_obj.file_size = 5000
    export_obj.exported_by = "user-123"
    export_obj.created_at = now

    response = ExportResponse.model_validate(export_obj)

    assert response.id == raw_id
    assert response.workspace_id == raw_ws_id
    assert response.workflow_run_id == raw_run_id
    assert response.filename == "report.docx"
    assert response.format == "docx"
    assert response.file_size == 5000

    json_dict = response.model_dump(mode="json")
    assert json_dict["id"] == str(raw_id)
    assert json_dict["workspace_id"] == str(raw_ws_id)
    assert json_dict["created_at"] == now.isoformat()


@pytest.mark.asyncio
async def test_download_export_pdf_success(mock_export_service):
    """Test successful PDF export download with application/pdf media_type"""
    export = MagicMock(spec=Export)
    export.id = uuid4()
    export.filename = "screenplay.pdf"
    export.format = "screenplay_pdf"

    file_content = b"%PDF-1.4 mock pdf content"
    mock_export_service.get_export_content.return_value = file_content

    result = await download_export(export.id, export=export, service=mock_export_service)
    assert result.body == file_content
    assert result.media_type == "application/pdf"
    assert f'attachment; filename="{export.filename}"' in result.headers["Content-Disposition"]


@pytest.mark.asyncio
async def test_create_export_pdf_success(mock_export_service, sample_export):
    """Test export creation with format='pdf'"""
    export_data = ExportCreate(
        review_id=sample_export.review_id,
        exported_by="user-123",
        format="pdf",
    )

    sample_pdf_export = MagicMock(spec=Export)
    sample_pdf_export.filename = "tariff_report.pdf"
    sample_pdf_export.format = "pdf"
    mock_export_service.export_review_as_pdf.return_value = sample_pdf_export

    result = await create_export(export_data, mock_export_service)
    assert result == sample_pdf_export
    mock_export_service.export_review_as_pdf.assert_called_once()

