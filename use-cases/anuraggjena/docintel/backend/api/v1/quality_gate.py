from typing import List, Optional, Any
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, require_workspace_access, verify_run_workspace_access, require_reviewer_or_admin
from backend.models.workspace import Workspace
from backend.models.workflow import WorkflowRun
from backend.models.user import User
from backend.repositories.quality_gate import QualityGateConfigRepository, QualityGateResultRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/quality-gate", tags=["quality-gate"])


class QualityGateConfigUpdate(BaseModel):
    enabled: bool = True
    block_on_failure: bool = False
    checks_config: dict = {}


class QualityGateConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    enabled: bool
    block_on_failure: bool
    checks_config: dict
    created_at: datetime


class QualityGateResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_run_id: UUID
    status: str
    checks_run: int
    checks_passed: int
    checks_failed: int
    blocking: bool
    details: list
    created_at: datetime


async def get_config_repo(db: AsyncSession = Depends(get_db)) -> QualityGateConfigRepository:
    return QualityGateConfigRepository(db)


async def get_result_repo(db: AsyncSession = Depends(get_db)) -> QualityGateResultRepository:
    return QualityGateResultRepository(db)


@router.get("/workspace/{workspace_id}/config", response_model=Optional[QualityGateConfigResponse])
async def get_workspace_config(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    repo: QualityGateConfigRepository = Depends(get_config_repo)
):
    """
    Get quality gate configuration for a workspace.

    Raises:
        403: If user doesn't own the workspace
        404: If workspace not found
    """
    config = await repo.get_by_workspace(workspace_id)
    return config


@router.put("/workspace/{workspace_id}/config", response_model=QualityGateConfigResponse)
async def upsert_workspace_config(
    workspace_id: UUID,
    data: QualityGateConfigUpdate,
    workspace: Workspace = Depends(require_workspace_access),
    reviewer: User = Depends(require_reviewer_or_admin),
    repo: QualityGateConfigRepository = Depends(get_config_repo)
):
    """
    Create or update quality gate configuration for a workspace (reviewer/admin only).

    Raises:
        403: If user doesn't own the workspace or lacks reviewer/admin role
        404: If workspace not found
    """
    existing = await repo.get_by_workspace(workspace_id)
    if existing:
        updated = await repo.update(
            existing.id,
            enabled=data.enabled,
            block_on_failure=data.block_on_failure,
            checks_config=data.checks_config
        )
        return updated
    created = await repo.create(
        workspace_id=str(workspace_id),
        enabled=data.enabled,
        block_on_failure=data.block_on_failure,
        checks_config=data.checks_config
    )
    return created


@router.get("/run/{run_id}/result", response_model=Optional[QualityGateResultResponse])
async def get_run_result(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    repo: QualityGateResultRepository = Depends(get_result_repo)
):
    """
    Get quality gate result for a workflow run.

    Raises:
        403: If user doesn't own the workspace
        404: If workflow run not found
    """
    result = await repo.get_by_run(run_id)
    return result
