import json
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, require_workspace_access, verify_run_workspace_access
from backend.models.workspace import Workspace
from backend.models.workflow import WorkflowRun
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.workflow import WorkflowRepository, WorkflowRunRepository, WorkflowStageRepository
from backend.repositories.document import DocumentRepository
from backend.services.workflow import WorkflowService
from backend.storage.local import LocalStorageBackend
from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["runs"])


# ------------------------------------------------------------------
# Request / Response schemas
# ------------------------------------------------------------------

class RunCreate(BaseModel):
    workflow_slug: str = Field(..., description="Registered workflow slug, e.g. tariff_classification")
    document_id: UUID = Field(..., description="Document to process")
    created_by: str = Field(default="system")


class StageResponse(BaseModel):
    id: UUID
    stage_name: str
    status: str
    retry_count: int
    execution_time_ms: Optional[int]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]

    class Config:
        from_attributes = True

    @field_serializer('started_at', 'completed_at')
    def serialize_dt(self, dt: Optional[datetime], _info) -> Optional[str]:
        return dt.isoformat() if dt else None


class RunResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    workflow_id: UUID
    workflow_slug: Optional[str] = None
    status: str
    resumable: bool = False
    current_stage: Optional[str]
    workflow_version: str
    created_by: str
    version_number: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_serializer('started_at', 'completed_at', 'created_at', 'updated_at')
    def serialize_dt(self, dt: Optional[datetime], _info) -> Optional[str]:
        return dt.isoformat() if dt else None


# ------------------------------------------------------------------
# Dependency
# ------------------------------------------------------------------

def _get_storage():
    return LocalStorageBackend(settings.storage_path)


async def _attach_slugs(runs, db: AsyncSession) -> list:
    """Build RunResponse payloads with the workflow slug and resumable status resolved for each run."""
    workflow_repo = WorkflowRepository(db)
    stage_repo = WorkflowStageRepository(db)
    slug_cache: dict = {}
    responses = []
    for run in runs:
        wf_id = run.workflow_id
        if wf_id not in slug_cache:
            workflow = await workflow_repo.get_by_id(wf_id)
            slug_cache[wf_id] = workflow.slug if workflow else None

        is_resumable = False
        if run.status not in ("completed", "queued", "running"):
            stages = await stage_repo.list_by_run(run.id)
            for s in stages:
                if s.status in ("completed", "skipped") and s.checkpoint_data:
                    try:
                        data = json.loads(s.checkpoint_data)
                        if isinstance(data, dict) and len(data) > 0:
                            is_resumable = True
                            break
                    except Exception:
                        continue

        payload = RunResponse.model_validate(run).model_dump()
        payload["workflow_slug"] = slug_cache[wf_id]
        payload["resumable"] = is_resumable
        responses.append(payload)
    return responses


async def get_workflow_service(db: AsyncSession = Depends(get_db)) -> WorkflowService:
    return WorkflowService(
        workflow_repository=WorkflowRepository(db),
        run_repository=WorkflowRunRepository(db),
        stage_repository=WorkflowStageRepository(db),
        document_repository=DocumentRepository(db),
        storage=_get_storage(),
    )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/{workspace_id}/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    workspace_id: UUID,
    body: RunCreate,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(require_workspace_access),
    service: WorkflowService = Depends(get_workflow_service),
    db: AsyncSession = Depends(get_db),
):
    """Create a workflow run and start it in the background (requires workspace ownership)."""
    # Workspace access already verified by dependency

    try:
        run = await service.create_run(
            workspace_id=workspace_id,
            workflow_slug=body.workflow_slug,
            document_id=body.document_id,
            created_by=body.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # If run is already active, return it
    if run.status in ("running", "completed", "failed", "cancelled"):
        return run

    # Build initial state and enqueue
    try:
        initial_state = await service.build_initial_state(run.id, body.document_id)
    except Exception as e:
        logger.error("initial_state_build_failed", run_id=str(run.id), error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to prepare workflow: {e}")

    async def _start_workflow():
        from backend.core.workflow.task_manager import get_task_manager
        try:
            tm = get_task_manager()
            # TaskManager creates its own sessions and builds stages internally
            await tm.start_workflow(
                workflow_run_id=run.id,
                workflow_name=body.workflow_slug,
                initial_state=initial_state,
            )
        except Exception as exc:
            logger.error("workflow_start_failed", run_id=str(run.id), error=str(exc))

    background_tasks.add_task(_start_workflow)

    logger.info("run_created_and_queued", run_id=str(run.id), workflow=body.workflow_slug)
    runs = await _attach_slugs([run], db)
    return runs[0]


@router.get("/{workspace_id}/runs", response_model=List[RunResponse])
async def list_runs(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    service: WorkflowService = Depends(get_workflow_service),
    db: AsyncSession = Depends(get_db),
):
    """List all runs for a workspace (requires ownership)."""
    runs = await service.list_workspace_runs(workspace_id)
    return await _attach_slugs(runs, db)


@router.get("/{workspace_id}/runs/{run_id}", response_model=RunResponse)
async def get_run(
    workspace_id: UUID,
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific run (requires workspace ownership)."""
    # Verify run belongs to the workspace (defense in depth)
    if run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in workspace")
    runs = await _attach_slugs([run], db)
    return runs[0]


@router.get("/{workspace_id}/runs/{run_id}/stages", response_model=List[StageResponse])
async def get_run_stages(
    workspace_id: UUID,
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    service: WorkflowService = Depends(get_workflow_service),
):
    """Get all stages for a run (requires workspace ownership)."""
    if run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in workspace")

    stages = await service.get_run_stages(run_id)
    return stages


@router.post("/{workspace_id}/runs/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    workspace_id: UUID,
    run_id: UUID,
    background_tasks: BackgroundTasks,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    service: WorkflowService = Depends(get_workflow_service),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused, blocked, interrupted, or cancelled workflow run if a valid checkpoint exists."""
    if run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in workspace")

    is_resumable = await service.is_run_resumable(run)
    if not is_resumable:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in status '{run.status}' and cannot be resumed"
        )

    workflow_repo = WorkflowRepository(db)
    workflow = await workflow_repo.get_by_id(run.workflow_id)
    workflow_name = workflow.slug if workflow else "tariff_classification"

    async def _resume():
        from backend.core.workflow.task_manager import get_task_manager
        try:
            tm = get_task_manager()
            await tm.resume_workflow(run_id, workflow_name)
        except Exception as exc:
            logger.error("workflow_resume_failed", run_id=str(run_id), error=str(exc))

    background_tasks.add_task(_resume)
    logger.info("run_resume_queued", run_id=str(run_id))
    runs = await _attach_slugs([run], db)
    return runs[0]


@router.post("/{workspace_id}/runs/{run_id}/replay", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def replay_run(
    workspace_id: UUID,
    run_id: UUID,
    background_tasks: BackgroundTasks,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    service: WorkflowService = Depends(get_workflow_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Replay an existing workflow run.

    Creates a brand-new workflow run with the same workflow and source document,
    leaving the original run unchanged.
    """
    if run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in workspace")

    try:
        new_run, document_id = await service.replay_run(
            workspace_id=workspace_id,
            original_run_id=run_id,
            created_by=run.created_by or "system",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    workflow_repo = WorkflowRepository(db)
    workflow = await workflow_repo.get_by_id(new_run.workflow_id)
    workflow_slug = workflow.slug if workflow else "tariff_classification"

    # Build initial state
    try:
        initial_state = await service.build_initial_state(new_run.id, document_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Hand off to TaskManager in background
    async def _start():
        from backend.core.workflow.task_manager import get_task_manager
        try:
            tm = get_task_manager()
            await tm.start_workflow(new_run.id, workflow_slug, initial_state)
        except Exception as exc:
            logger.error("background_workflow_failed_to_start", run_id=str(new_run.id), error=str(exc))

    background_tasks.add_task(_start)
    logger.info("workflow_replay_queued", original_run_id=str(run_id), new_run_id=str(new_run.id))

    runs = await _attach_slugs([new_run], db)
    return runs[0]


@router.get("/{workspace_id}/runs/{run_id}/claims")
async def get_run_claims(
    workspace_id: UUID,
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Get all claims for a workflow run (for approval UI)."""
    if run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in workspace")

    from backend.repositories.review import ClaimRepository
    from backend.repositories.memo_section import MemoSectionRepository
    claim_repo = ClaimRepository(db)
    memo_repo = MemoSectionRepository(db)

    claims = await claim_repo.list_by_run(run_id)
    memo_sections = await memo_repo.list_by_run(run_id)
    memo_by_id = {str(ms.id): ms for ms in memo_sections}
    memo_by_type = {ms.section_type: ms for ms in memo_sections}

    result = []
    for c in claims:
        content_str = c.content
        try:
            parsed = json.loads(c.content) if isinstance(c.content, str) else c.content
            if isinstance(parsed, dict) and c.claim_type == "memo_section":
                ms_id = parsed.get("memo_section_id")
                ms = memo_by_id.get(ms_id) or memo_by_type.get(parsed.get("section_type"))
                if ms:
                    if not parsed.get("content") and ms.content:
                        parsed["content"] = ms.content
                    if not parsed.get("new_html") and ms.content:
                        parsed["new_html"] = ms.content
                    if not parsed.get("analyst_reasoning") and ms.analyst_reasoning:
                        parsed["analyst_reasoning"] = ms.analyst_reasoning
                    if not parsed.get("ai_explanation") and ms.analyst_reasoning:
                        parsed["ai_explanation"] = ms.analyst_reasoning
                    if not parsed.get("section_order") and ms.section_order:
                        parsed["section_order"] = ms.section_order
                    if not parsed.get("title") and ms.title:
                        parsed["title"] = ms.title
                    if not parsed.get("confidence") and ms.confidence:
                        parsed["confidence"] = ms.confidence
                    if ms.baseline_section_id and not parsed.get("old_html"):
                        baseline_ms = await memo_repo.get_by_id(ms.baseline_section_id)
                        if baseline_ms and baseline_ms.content:
                            parsed["old_html"] = baseline_ms.content
                            parsed["old_content"] = baseline_ms.content
                content_str = json.dumps(parsed)
        except Exception:
            pass

        result.append({
            "id": str(c.id),
            "claim_type": c.claim_type,
            "content": content_str,
            "status": c.status,
            "source_stage": c.source_stage,
            "confidence_score": c.confidence_score,
            "original_content": c.original_content,
            "review_id": str(c.review_id) if c.review_id else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return result


@router.post("/{workspace_id}/runs/{run_id}/claims/approve-all")
async def approve_all_run_claims(
    workspace_id: UUID,
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    service: WorkflowService = Depends(get_workflow_service),
    db: AsyncSession = Depends(get_db),
):
    """Bulk approve all pending claims for a workflow run and resume the run if waiting."""
    if run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in workspace")

    from backend.repositories.review import ClaimRepository, ReviewRepository
    from backend.repositories.memo_section import MemoSectionRepository

    claim_repo = ClaimRepository(db)
    memo_repo = MemoSectionRepository(db)
    review_repo = ReviewRepository(db)

    # 1. Fetch claims for run
    claims = await claim_repo.list_by_run(run_id)

    # 2. Bulk approve in ClaimRepository
    approved_count = await claim_repo.bulk_approve_for_run(run_id)

    # 3. Update memo sections to approved
    memo_sections = await memo_repo.list_by_run(run_id)
    for ms in memo_sections:
        if ms.status == "pending":
            await memo_repo.update(ms.id, status="approved")

    # 4. Update parent review(s) to approved
    reviews = await review_repo.list_by_workspace(workspace_id)
    run_reviews = [r for r in reviews if r.workflow_run_id == run_id]
    for r in run_reviews:
        await review_repo.update(r.id, status="approved")

    # Commit database changes so background task sees approved status immediately
    await db.commit()

    # 5. If run is in waiting status, resume workflow
    resumed = False
    fresh_run = await service.get_run(run_id)
    if fresh_run and fresh_run.status == "waiting":
        try:
            await service.resume_run(run_id)
            resumed = True
            logger.info("resumed_workflow_run_after_bulk_approve", run_id=str(run_id))
        except Exception as e:
            logger.warning("failed_to_resume_run_on_bulk_approve", run_id=str(run_id), error=str(e))

    return {
        "approved_count": approved_count,
        "total_claims": len(claims),
        "resumed": resumed,
        "run_id": str(run_id),
    }


@router.post("/{workspace_id}/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    workspace_id: UUID,
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    service: WorkflowService = Depends(get_workflow_service),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running workflow."""
    run = await service.get_run(run_id)
    if not run or run.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status not in ("queued", "running", "waiting", "blocked"):
        raise HTTPException(
            status_code=409,
            detail=f"Run is in status '{run.status}' and cannot be cancelled"
        )

    await service.cancel_run(run_id)

    # Refresh
    run = await service.get_run(run_id)
    runs = await _attach_slugs([run], db)
    return runs[0]
