from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from backend.api.deps import get_db, require_workspace_access, verify_knowledge_workspace_access
from backend.models.workspace import Workspace
from backend.models.knowledge import KnowledgeEntry
from backend.repositories.knowledge import KnowledgeRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeEntryResponse(BaseModel):
    id: UUID | str
    workspace_id: UUID | str
    workflow_type: str
    entry_type: str
    content: str
    confidence_score: Optional[float] = None
    tags: list
    source_run_id: Optional[UUID | str] = None
    source_document_id: Optional[UUID | str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeEntryCreate(BaseModel):
    workflow_type: str
    entry_type: str
    content: str
    confidence_score: Optional[float] = None
    tags: list = []
    source_run_id: Optional[str] = None
    source_document_id: Optional[str] = None


async def get_knowledge_repo(db: AsyncSession = Depends(get_db)) -> KnowledgeRepository:
    return KnowledgeRepository(db)


@router.get("/workspace/{workspace_id}", response_model=List[KnowledgeEntryResponse])
async def list_workspace_knowledge(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    workflow_type: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    limit: int = Query(50, le=200),
    repo: KnowledgeRepository = Depends(get_knowledge_repo)
):
    """
    List knowledge entries for a workspace.

    Raises:
        403: If user doesn't own the workspace
        404: If workspace not found
    """
    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    if tag_list:
        entries = await repo.search_by_tags(
            workspace_id=workspace_id,
            tags=tag_list,
            workflow_type=workflow_type,
            limit=limit
        )
    elif workflow_type:
        entries = await repo.list_by_workspace_and_type(
            workspace_id=workspace_id,
            workflow_type=workflow_type,
            limit=limit
        )
        if not entries:
            entries = await repo.list_by_workspace(
                workspace_id=workspace_id,
                limit=limit
            )
    else:
        # No filter — list all by workspace
        from sqlalchemy import select
        result = await repo.session.execute(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.workspace_id == workspace_id)
            .order_by(KnowledgeEntry.created_at.desc())
            .limit(limit)
        )
        entries = list(result.scalars().all())

    return entries


@router.post("/workspace/{workspace_id}", response_model=KnowledgeEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_entry(
    workspace_id: UUID,
    data: KnowledgeEntryCreate,
    workspace: Workspace = Depends(require_workspace_access),
    repo: KnowledgeRepository = Depends(get_knowledge_repo)
):
    """
    Create a knowledge entry in a workspace.

    Raises:
        403: If user doesn't own the workspace
        404: If workspace not found
    """
    entry = await repo.create(
        workspace_id=workspace_id,
        workflow_type=data.workflow_type,
        entry_type=data.entry_type,
        content=data.content,
        confidence_score=data.confidence_score,
        tags=data.tags,
        source_run_id=data.source_run_id,
        source_document_id=data.source_document_id,
        extra_metadata={}
    )
    return entry


@router.delete("/workspace/{workspace_id}/entry/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_entry(
    workspace_id: UUID,
    entry_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    entry: KnowledgeEntry = Depends(verify_knowledge_workspace_access),
    repo: KnowledgeRepository = Depends(get_knowledge_repo)
):
    """
    Delete a knowledge entry.

    Raises:
        403: If user doesn't own the workspace
        404: If workspace or entry not found
    """
    # Verify entry belongs to specified workspace
    if entry.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    await repo.delete(entry_id)
