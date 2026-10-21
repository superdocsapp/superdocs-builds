from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, require_workspace_access, require_admin
from backend.models.workspace import Workspace
from backend.models.user import User
from backend.services.audit import AuditService
from backend.repositories.audit import AuditRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])


class AuditLogResponse(BaseModel):
    id: str
    workspace_id: Optional[str] = None
    event_type: str
    actor_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: dict
    created_at: datetime

    class Config:
        from_attributes = True


async def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


@router.get("/workspace/{workspace_id}", response_model=List[AuditLogResponse])
async def get_workspace_audit_log(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    event_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    service: AuditService = Depends(get_audit_service)
):
    """
    Get audit log for a workspace.

    Raises:
        403: If user doesn't own the workspace
        404: If workspace not found
    """
    return await service.get_workspace_audit_log(workspace_id, event_type=event_type, limit=limit)


@router.get("/resource/{resource_type}/{resource_id}", response_model=List[AuditLogResponse])
async def get_resource_audit_log(
    resource_type: str,
    resource_id: str,
    admin: User = Depends(require_admin),
    limit: int = Query(50, le=200),
    service: AuditService = Depends(get_audit_service)
):
    """
    Get audit log for a specific resource (admin only).

    Since this endpoint can access any resource type, it requires admin privileges
    for security. For workspace-specific audit logs, use /audit/workspace/{workspace_id}.

    Raises:
        403: If user is not an admin
    """
    return await service.get_resource_audit_log(resource_type, resource_id, limit=limit)
