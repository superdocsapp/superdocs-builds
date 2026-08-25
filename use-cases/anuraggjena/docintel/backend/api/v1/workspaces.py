from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_serializer

from backend.api.deps import get_workspace_service, get_current_user, require_workspace_access
from backend.services.workspace import WorkspaceService
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# Request/Response Schemas
class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    # owner_id removed - derived from authenticated user
    workflow_type: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    workflow_type: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    owner_user_id: UUID
    workflow_type: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info) -> str:
        """Serialize datetime to ISO format string"""
        return dt.isoformat()


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service)
):
    """Create a new workspace (requires authentication)"""
    logger.info("api_create_workspace", name=workspace.name, user_id=str(current_user.id))

    result = await service.create_workspace(
        name=workspace.name,
        owner_user_id=current_user.id,  # Owner is authenticated user
        workflow_type=workspace.workflow_type
    )

    return result


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service)
):
    """List workspaces for authenticated user"""
    logger.info("api_list_workspaces", user_id=str(current_user.id))

    workspaces = await service.list_user_workspaces(current_user.id)
    return workspaces


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access)
):
    """Get a specific workspace (requires ownership)"""
    # Workspace access already verified by dependency
    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    updates: WorkspaceUpdate,
    workspace: Workspace = Depends(require_workspace_access),
    service: WorkspaceService = Depends(get_workspace_service)
):
    """Update a workspace (requires ownership)"""
    logger.info("api_update_workspace", workspace_id=str(workspace_id))

    result = await service.update_workspace(
        workspace_id,
        name=updates.name,
        workflow_type=updates.workflow_type
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace {workspace_id} not found"
        )

    return result


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    service: WorkspaceService = Depends(get_workspace_service)
):
    """Delete a workspace (soft delete, requires ownership)"""
    logger.info("api_delete_workspace", workspace_id=str(workspace_id))

    success = await service.delete_workspace(workspace_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace {workspace_id} not found"
        )
