from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, get_current_user, verify_run_workspace_access, verify_formatting_item_workspace_access
from backend.models.workflow import WorkflowRun
from backend.models.screenplay import ScreenplayFormattingItem
from backend.models.workspace import Workspace
from backend.models.document import Document
from backend.models.user import User
from backend.repositories.screenplay import FormattingItemRepository
from backend.models.review import Review
from backend.logging_config import get_logger
from sqlalchemy import select, and_, update

logger = get_logger(__name__)
router = APIRouter(prefix="/screenplay", tags=["screenplay"])


async def _sync_screenplay_review_status(db: AsyncSession, run_id: UUID) -> None:
    """
    Synchronize the Review table row status based on ScreenplayFormattingItems.
    If all proposed changes are decided (0 pending):
        - status = 'rejected' if any rejected
        - status = 'approved' if all approved
    If pending > 0:
        - status = 'in_review'
    """
    try:
        stmt = select(ScreenplayFormattingItem.status, ScreenplayFormattingItem.change_type).where(
            ScreenplayFormattingItem.workflow_run_id == run_id
        )
        res = await db.execute(stmt)
        items = res.all()
        if not items:
            return

        pending = sum(
            1 for status, chg in items
            if status == "pending" and (chg != "no_change" or status in ("pending", "rejected"))
        )
        rejected = sum(1 for status, _ in items if status == "rejected")

        new_status = "in_review"
        if pending == 0:
            new_status = "rejected" if rejected > 0 else "approved"

        await db.execute(
            update(Review)
            .where(Review.workflow_run_id == run_id)
            .values(status=new_status)
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to sync review status for run {run_id}: {e}")


class ScreenplayLibraryItem(BaseModel):
    id: UUID
    workspace_id: UUID
    workspace_name: str
    filename: str
    mime_type: str
    processing_status: str
    created_at: datetime
    run_id: Optional[UUID] = None
    run_status: Optional[str] = None
    scenes_count: Optional[int] = None
    items_count: Optional[int] = None
    pending_items_count: Optional[int] = None

    class Config:
        from_attributes = True

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime, _info) -> str:
        return dt.isoformat()


class FormattingItemResponse(BaseModel):
    id: UUID
    element_index: int
    element_type: str
    scene_number: Optional[int]
    character_name: Optional[str]
    original_text: str
    formatted_text: str
    change_type: str
    reason: Optional[str]
    diff_tokens: Optional[list]
    content_drift: bool
    status: str
    reviewer_comment: Optional[str]
    confidence_score: Optional[float]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, dt: datetime, _info) -> str:
        return dt.isoformat()


class RejectBody(BaseModel):
    reviewer_comment: Optional[str] = None


async def get_repo(db: AsyncSession = Depends(get_db)) -> FormattingItemRepository:
    return FormattingItemRepository(db)


@router.get("/library", response_model=List[ScreenplayLibraryItem])
async def list_screenplay_library(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    repo: FormattingItemRepository = Depends(get_repo),
):
    """
    List all screenplay documents and associated runs for workspaces owned by current user.
    """
    # 1. Query workspaces owned by user where workflow_type == 'screenplay'
    stmt = (
        select(Workspace)
        .where(
            and_(
                Workspace.owner_user_id == current_user.id,
                Workspace.workflow_type == "screenplay",
                Workspace.status == "active",
            )
        )
        .order_by(Workspace.created_at.desc())
    )
    res = await db.execute(stmt)
    screenplay_workspaces = list(res.scalars().all())

    if not screenplay_workspaces:
        return []

    workspace_map = {w.id: w.name for w in screenplay_workspaces}
    workspace_ids = list(workspace_map.keys())

    # 2. Query all documents in these workspaces
    doc_stmt = (
        select(Document)
        .where(Document.workspace_id.in_(workspace_ids))
        .order_by(Document.created_at.desc())
    )
    doc_res = await db.execute(doc_stmt)
    documents = list(doc_res.scalars().all())

    # 3. Query workflow runs for these workspaces
    run_stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.workspace_id.in_(workspace_ids))
        .order_by(WorkflowRun.created_at.desc())
    )
    run_res = await db.execute(run_stmt)
    runs = list(run_res.scalars().all())

    latest_run_by_workspace: dict[UUID, WorkflowRun] = {}
    for r in runs:
        if r.workspace_id not in latest_run_by_workspace:
            latest_run_by_workspace[r.workspace_id] = r

    # 4. Build library items from documents
    library_items: list[ScreenplayLibraryItem] = []
    seen_workspace_ids_with_docs = set()

    for doc in documents:
        seen_workspace_ids_with_docs.add(doc.workspace_id)
        run = latest_run_by_workspace.get(doc.workspace_id)
        scenes_count = None
        items_count = None
        pending_items_count = None

        if run:
            formatting_items = await repo.list_by_run(run.id)
            if formatting_items:
                items_count = len(formatting_items)
                pending_items_count = sum(1 for item in formatting_items if item.status == "pending")
                scenes_count = len({item.scene_number for item in formatting_items if item.scene_number is not None})
                if scenes_count == 0 and any(item.element_type == "scene_heading" for item in formatting_items):
                    scenes_count = sum(1 for item in formatting_items if item.element_type == "scene_heading")

        library_items.append(
            ScreenplayLibraryItem(
                id=doc.id,
                workspace_id=doc.workspace_id,
                workspace_name=workspace_map.get(doc.workspace_id, "Screenplay Workspace"),
                filename=doc.filename,
                mime_type=doc.mime_type,
                processing_status=doc.processing_status,
                created_at=doc.created_at,
                run_id=run.id if run else None,
                run_status=run.status if run else None,
                scenes_count=scenes_count,
                items_count=items_count,
                pending_items_count=pending_items_count,
            )
        )

    return library_items


@router.get("/{run_id}/formatting-items", response_model=List[FormattingItemResponse])
async def list_formatting_items(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    repo: FormattingItemRepository = Depends(get_repo)
):
    """
    List formatting items for a screenplay run.

    Raises:
        403: If user doesn't own the workspace
        404: If run not found
    """
    return await repo.list_by_run(run_id)


@router.post("/{run_id}/formatting-items/approve-all")
async def approve_all(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    repo: FormattingItemRepository = Depends(get_repo),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve all formatting items for a run (requires workspace ownership).

    Raises:
        403: If user doesn't own workspace
        404: If run not found
    """
    count = await repo.approve_all_for_run(run_id)
    await _sync_screenplay_review_status(db, run_id)
    return {"approved_count": count}


@router.get("/{run_id}/formatting-items/{item_id}", response_model=FormattingItemResponse)
async def get_formatting_item(
    run_id: UUID,
    item_id: UUID,
    item: ScreenplayFormattingItem = Depends(verify_formatting_item_workspace_access),
    repo: FormattingItemRepository = Depends(get_repo)
):
    """
    Get a specific formatting item.

    Raises:
        403: If user doesn't own the workspace
        404: If item not found or doesn't match run
    """
    if item.workflow_run_id != run_id:
        raise HTTPException(status_code=404, detail="Formatting item not found")
    return item


@router.post("/{run_id}/formatting-items/{item_id}/approve", response_model=FormattingItemResponse)
async def approve_item(
    run_id: UUID,
    item_id: UUID,
    item: ScreenplayFormattingItem = Depends(verify_formatting_item_workspace_access),
    repo: FormattingItemRepository = Depends(get_repo),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a formatting item (requires workspace ownership).

    Raises:
        403: If user doesn't own workspace
        404: If item not found or doesn't match run
    """
    if item.workflow_run_id != run_id:
        raise HTTPException(status_code=404, detail="Formatting item not found")
    updated = await repo.approve(item_id)
    await _sync_screenplay_review_status(db, run_id)
    return updated


@router.post("/{run_id}/formatting-items/{item_id}/reject", response_model=FormattingItemResponse)
async def reject_item(
    run_id: UUID,
    item_id: UUID,
    body: RejectBody,
    item: ScreenplayFormattingItem = Depends(verify_formatting_item_workspace_access),
    repo: FormattingItemRepository = Depends(get_repo),
    db: AsyncSession = Depends(get_db),
):
    """
    Reject a formatting item (requires workspace ownership).

    Raises:
        403: If user doesn't own workspace
        404: If item not found or doesn't match run
    """
    if item.workflow_run_id != run_id:
        raise HTTPException(status_code=404, detail="Formatting item not found")
    updated = await repo.reject(item_id, reviewer_comment=body.reviewer_comment)
    await _sync_screenplay_review_status(db, run_id)
    return updated


@router.post("/{run_id}/regenerate")
async def regenerate(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    db: AsyncSession = Depends(get_db)
):
    """
    Regenerate rejected formatting items (requires workspace ownership).

    Raises:
        403: If user doesn't own workspace
        404: If run not found
    """
    # Run already verified by dependency

    from backend.modules.screenplay.stages.regenerate import RegenerateStage
    from backend.modules.screenplay.llm_config import get_screenplay_llm_provider

    llm = get_screenplay_llm_provider()
    item_repo = FormattingItemRepository(db)
    stage = RegenerateStage(llm_provider=llm, formatting_item_repo=item_repo)

    all_items = await item_repo.list_by_run(run_id)

    state = {
        "workflow_run_id": str(run_id),
        "workspace_id": str(run.workspace_id),
        "document_id": str(run.id),  # placeholder; regenerate stage only needs items
        "formatting_items": [
            {
                "id": str(i.id),
                "element_index": i.element_index,
                "element_type": i.element_type,
                "scene_number": i.scene_number,
                "character_name": i.character_name,
                "original_text": i.original_text,
                "formatted_text": i.formatted_text,
                "change_type": i.change_type,
                "reason": i.reason or "",
                "diff_tokens": i.diff_tokens or [],
                "content_drift": i.content_drift,
                "status": i.status,
                "reviewer_comment": i.reviewer_comment,
                "confidence_score": i.confidence_score,
            }
            for i in all_items
        ],
    }

    background_tasks.add_task(stage.execute, state)
    return {"run_id": str(run_id), "queued": True}


@router.get("/{run_id}/preview")
async def preview(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    repo: FormattingItemRepository = Depends(get_repo)
):
    """
    Preview formatted screenplay with status summary.

    Raises:
        403: If user doesn't own the workspace
        404: If run not found
    """
    items = await repo.list_by_run(run_id)
    original_lines = [i.original_text for i in items]
    formatted_lines = [
        i.original_text if i.status == "rejected" else i.formatted_text
        for i in items
    ]
    return {
        "original_text": "\n".join(original_lines),
        "formatted_text": "\n".join(formatted_lines),
        "item_count": len(items),
        "pending_count": sum(1 for i in items if i.status == "pending"),
        "approved_count": sum(1 for i in items if i.status == "approved"),
        "rejected_count": sum(1 for i in items if i.status == "rejected"),
    }
