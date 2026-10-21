import asyncio
import inspect
import json
from uuid import UUID
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError

from backend.api.deps import get_db, get_current_user
from backend.models.workflow import WorkflowRun
from backend.models.user import User
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
from backend.core.auth.security import decode_token
from backend.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/stream", tags=["stream"])


async def workflow_event_generator(
    run_id: UUID,
    poll_interval: float = 1.0,
    timeout: float = 300.0
) -> AsyncGenerator[str, None]:
    """Yield SSE events for workflow run progress."""
    from backend.database import async_session_maker

    # Create a dedicated session for this generator with proper cleanup
    async with async_session_maker() as db:
        run_repo = WorkflowRunRepository(db)
        stage_repo = WorkflowStageRepository(db)

        elapsed = 0.0
        seen_stage_states = set()

        while elapsed < timeout:
            if hasattr(db, "expire_all"):
                expire_res = db.expire_all()
                if inspect.iscoroutine(expire_res):
                    await expire_res
            run = await run_repo.get_by_id(run_id)
            if not run:
                yield f"event: error\ndata: {json.dumps({'message': 'Workflow run not found'})}\n\n"
                return

            stages = await stage_repo.list_by_run(run_id)
            for idx, stage in enumerate(stages):
                stage_state_key = (
                    stage.id,
                    stage.status,
                    stage.completed_at.isoformat() if stage.completed_at else None,
                    stage.error_message,
                )
                if stage_state_key not in seen_stage_states:
                    seen_stage_states.add(stage_state_key)
                    payload = {
                        "stage_name": stage.stage_name,
                        "status": stage.status,
                        "stage_index": idx,  # Derive from enumeration order
                        "started_at": stage.started_at.isoformat() if stage.started_at else None,
                        "completed_at": stage.completed_at.isoformat() if stage.completed_at else None,
                        "execution_time_ms": stage.execution_time_ms,
                        "error_message": stage.error_message
                    }
                    yield f"event: stage_update\ndata: {json.dumps(payload)}\n\n"

            run_payload = {
                "status": run.status,
                "current_stage": run.current_stage
            }
            yield f"event: run_status\ndata: {json.dumps(run_payload)}\n\n"

            if run.status in ("completed", "failed", "cancelled"):
                yield f"event: done\ndata: {json.dumps({'status': run.status})}\n\n"
                return

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        yield f"event: timeout\ndata: {json.dumps({'message': 'Stream timeout'})}\n\n"


async def verify_sse_access(
    run_id: UUID,
    token: Optional[str] = Query(None, description="Stream token for authentication"),
    db: AsyncSession = Depends(get_db)
) -> WorkflowRun:
    """
    Verify user has access to workflow run for SSE streaming using stream token.

    EventSource cannot send Authorization headers, so we accept token as query parameter.

    Stream tokens are:
    - Short-lived (60 seconds)
    - Scoped to specific workflow run
    - Cannot be used for any other API endpoints
    - Type=stream, audience=docintel-workflow-stream

    This prevents full-privilege access tokens from appearing in server logs.
    """
    from backend.core.auth.security import (
        TOKEN_TYPE_STREAM,
        TOKEN_AUD_STREAM
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Stream token required"
        )

    # Decode and validate stream token with strict type/audience checking
    try:
        payload = decode_token(
            token,
            expected_type=TOKEN_TYPE_STREAM,
            expected_audience=TOKEN_AUD_STREAM
        )

        user_id_str = payload.get("sub")
        token_run_id_str = payload.get("run_id")

        if not user_id_str or not token_run_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid stream token: missing claims"
            )

        user_id = UUID(user_id_str)
        token_run_id = UUID(token_run_id_str)

        # Verify token is for the requested run
        if token_run_id != run_id:
            logger.warning(
                "sse_stream_token_run_mismatch",
                token_run_id=str(token_run_id),
                requested_run_id=str(run_id)
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Stream token not valid for this run"
            )

    except (JWTError, ValueError) as e:
        logger.warning("sse_stream_token_invalid", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired stream token"
        )

    # Get user from database
    from backend.repositories.user import UserRepository
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    # Get and verify run access
    run_repo = WorkflowRunRepository(db)
    run = await run_repo.get_by_id(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run {run_id} not found"
        )

    # Verify workspace access (defense in depth)
    workspace_repo = WorkspaceRepository(db)
    workspace = await workspace_repo.get_by_id(run.workspace_id)

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )

    if workspace.owner_user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this workspace"
        )

    return run


@router.get("/workflow-run/{run_id}")
async def stream_workflow_run(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_sse_access)
):
    """
    Stream SSE events for a workflow run's progress (requires workspace ownership).

    EventSource cannot send Authorization headers, so accepts token as query parameter.

    Note: The generator creates its own database session with proper cleanup
    to avoid session leaks when clients disconnect.
    """
    logger.info("sse_stream_started", run_id=str(run_id))

    return StreamingResponse(
        workflow_event_generator(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
