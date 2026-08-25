from typing import List
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel

from backend.api.deps import get_db, get_current_user, require_workspace_access, verify_document_workspace_access
from backend.services.document import DocumentService
from backend.repositories.document import DocumentRepository
from backend.storage.local import LocalStorageBackend
from backend.models.workspace import Workspace
from backend.models.user import User
from backend.config import settings
from backend.logging_config import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = {
    # Documents
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    # Images (for product_image role)
    'image/png',
    'image/jpeg',
    'image/jpg',
    'image/webp',
    'image/gif',
}


# Document roles for tariff classification bundles
VALID_DOCUMENT_ROLES = frozenset({"product_spec", "ruling", "product_image", "other"})


# Schemas
class DocumentResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    filename: str
    mime_type: str
    processing_status: str
    document_role: str = "product_spec"
    created_at: datetime

    class Config:
        from_attributes = True


async def get_document_service(db: AsyncSession = Depends(get_db)) -> DocumentService:
    """Dependency for document service"""
    repository = DocumentRepository(db)
    storage = LocalStorageBackend(settings.storage_path)
    return DocumentService(repository, storage)


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    workspace_id: UUID = Form(...),
    file: UploadFile = File(...),
    role: str = Form(default="product_spec"),
    service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Upload a document to a workspace (requires ownership)"""
    # Verify workspace access (can't use require_workspace_access dependency with Form fields)
    workspace = await require_workspace_access(workspace_id=workspace_id, current_user=current_user, db=db)

    logger.info("api_upload_document", workspace_id=str(workspace_id), filename=file.filename, role=role)

    if role not in VALID_DOCUMENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document role '{role}'. Allowed: {', '.join(sorted(VALID_DOCUMENT_ROLES))}",
        )

    # Validate mime type
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {mime_type} not supported. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / 1024 / 1024}MB"
        )

    # Upload
    document = await service.upload_document(
        workspace_id=workspace_id,
        filename=file.filename or "unnamed",
        content=content,
        mime_type=mime_type,
        document_role=role,
    )

    return document


@router.get("/workspace/{workspace_id}", response_model=List[DocumentResponse])
async def list_documents(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    service: DocumentService = Depends(get_document_service)
):
    """List all documents in a workspace (requires ownership)"""
    documents = await service.list_workspace_documents(workspace_id)
    return documents


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    document = Depends(verify_document_workspace_access)
):
    """Get document metadata (requires workspace ownership)"""
    return document


@router.get("/{document_id}/content")
async def download_document(
    document_id: UUID,
    document = Depends(verify_document_workspace_access),
    service: DocumentService = Depends(get_document_service)
):
    """Download document content (requires workspace ownership)"""

    content = await service.get_document_content(document_id)

    if content is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve document content"
        )

    return Response(
        content=content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.filename}"'
        }
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    service: DocumentService = Depends(get_document_service)
):
    """Delete a document"""
    logger.info("api_delete_document", document_id=str(document_id))

    success = await service.delete_document(document_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )
