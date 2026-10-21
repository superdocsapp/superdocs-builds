from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, require_workspace_access, verify_export_workspace_access, verify_run_workspace_access
from backend.models.workspace import Workspace
from backend.models.workflow import WorkflowRun
from backend.models.export import Export
from backend.services.export import ExportService
from backend.repositories.export import ExportRepository
from backend.repositories.review import ReviewRepository, ClaimRepository
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.document import DocumentRepository
from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
from backend.repositories.memo_section import MemoSectionRepository
from backend.storage.local import LocalStorageBackend
from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])


# Schemas
class ExportCreate(BaseModel):
    review_id: UUID
    exported_by: Optional[str] = None
    format: Optional[str] = "docx"


class ExportResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    workflow_run_id: Optional[UUID] = None
    review_id: Optional[UUID] = None
    filename: str
    format: str
    file_size: int
    exported_by: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('id', 'workspace_id', 'workflow_run_id', 'review_id')
    def serialize_uuid(self, val: Optional[UUID], _info) -> Optional[str]:
        return str(val) if val is not None else None

    @field_serializer('created_at')
    def serialize_datetime(self, val: datetime, _info) -> str:
        return val.isoformat() if val is not None else ""


async def get_export_service(db: AsyncSession = Depends(get_db)) -> ExportService:
    """Dependency for export service"""
    storage = LocalStorageBackend(settings.storage_path)
    return ExportService(
        export_repository=ExportRepository(db),
        review_repository=ReviewRepository(db),
        claim_repository=ClaimRepository(db),
        workspace_repository=WorkspaceRepository(db),
        document_repository=DocumentRepository(db),
        run_repository=WorkflowRunRepository(db),
        stage_repository=WorkflowStageRepository(db),
        storage=storage,
        memo_section_repository=MemoSectionRepository(db),
    )


@router.post("", response_model=ExportResponse, status_code=status.HTTP_201_CREATED)
async def create_export(
    export_data: ExportCreate,
    service: ExportService = Depends(get_export_service)
):
    """
    Create a new export from a review.

    Note: Workspace access is verified via review_id during export creation.

    Raises:
        403: If user doesn't own the workspace
        404: If review not found
    """
    logger.info("api_create_export", review_id=export_data.review_id, format=export_data.format)

    try:
        if export_data.format and export_data.format.lower() == "pdf":
            export = await service.export_review_as_pdf(
                review_id=export_data.review_id,
                exported_by=export_data.exported_by,
            )
        else:
            export = await service.export_review_as_docx(
                review_id=export_data.review_id,
                exported_by=export_data.exported_by,
            )
        return export
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/{export_id}", response_model=ExportResponse)
async def get_export(
    export_id: UUID,
    export: Export = Depends(verify_export_workspace_access),
    service: ExportService = Depends(get_export_service)
):
    """
    Get export metadata.

    Raises:
        403: If user doesn't own the workspace
        404: If export not found
    """
    # Export already verified by dependency
    return export


@router.get("/{export_id}/download")
async def download_export(
    export_id: UUID,
    export: Export = Depends(verify_export_workspace_access),
    service: ExportService = Depends(get_export_service)
):
    """
    Download export file.

    Raises:
        403: If user doesn't own the workspace
        404: If export not found
        500: If export content retrieval fails
    """
    # Export already verified by dependency

    content = await service.get_export_content(export_id)

    if content is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve export content"
        )

    media_type = (
        "application/pdf"
        if export.filename.lower().endswith(".pdf") or export.format in ("pdf", "screenplay_pdf")
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"'
        }
    )


@router.get("/workspace/{workspace_id}", response_model=List[ExportResponse])
async def list_workspace_exports(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    service: ExportService = Depends(get_export_service)
):
    """
    List exports for a workspace.

    Raises:
        403: If user doesn't own the workspace
        404: If workspace not found
    """
    exports = await service.list_workspace_exports(workspace_id)
    return exports


@router.post("/tariff/{run_id}", status_code=status.HTTP_201_CREATED)
async def export_tariff_run(
    run_id: UUID,
    workspace_id: UUID,
    format: str = Query("docx", enum=["docx", "pdf"]),
    run: WorkflowRun = Depends(verify_run_workspace_access),
    workspace: Workspace = Depends(require_workspace_access),
    service: ExportService = Depends(get_export_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Export a completed Tariff run as canonical DOCX or PDF memo.

    Requires:
    - Completed workflow run
    - MemoSection records exist
    - At least one active section with content

    Returns:
        Export record with ID and filename

    Raises:
        403: If user doesn't own the workspace
        404: If run or workspace not found
        400: If run not completed or no MemoSections exist
    """
    from backend.repositories.document import DocumentRepository

    # Get all workspace documents for metadata resolution and image loading
    doc_repo = DocumentRepository(db)
    workspace_docs = await doc_repo.list_by_workspace(workspace_id)
    document_ids = [str(doc.id) for doc in workspace_docs]

    try:
        if format.lower() == "pdf":
            export = await service.export_run_as_pdf(
                run_id=run_id,
                workspace_id=workspace_id,
                document_ids=document_ids,
            )
        else:
            export = await service.export_run_as_docx(
                run_id=run_id,
                workspace_id=workspace_id,
                document_ids=document_ids,
            )
        return {"export_id": str(export.id), "filename": export.filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/screenplay/{run_id}", status_code=status.HTTP_201_CREATED)
async def export_screenplay(
    run_id: UUID,
    workspace_id: UUID,
    format: str = Query("docx", enum=["docx", "pdf"]),
    run: WorkflowRun = Depends(verify_run_workspace_access),
    workspace: Workspace = Depends(require_workspace_access),
    service: ExportService = Depends(get_export_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Export a screenplay run as DOCX or PDF.

    Raises:
        403: If user doesn't own the workspace
        404: If run or workspace not found
        400: If export creation fails
    """
    from backend.repositories.screenplay import FormattingItemRepository

    item_repo = FormattingItemRepository(db)
    db_items = await item_repo.list_by_run(run_id)
    formatting_items = [
        {
            "element_index": i.element_index,
            "element_type": i.element_type,
            "original_text": i.original_text,
            "formatted_text": i.formatted_text,
            "status": i.status,
        }
        for i in db_items
    ]

    try:
        if format.lower() == "pdf":
            export = await service.export_screenplay_as_pdf(
                run_id=run_id,
                workspace_id=workspace_id,
                formatting_items=formatting_items or None,
            )
        else:
            export = await service.export_screenplay_as_docx(
                run_id=run_id,
                workspace_id=workspace_id,
                formatting_items=formatting_items or None,
            )
        return {"export_id": str(export.id), "filename": export.filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

