"""Interview brief generation and retrieval endpoints."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.agents.runner import run_brief_pipeline
from app.api.deps import get_brief_service
from app.core.exceptions import BriefNotFoundError, SessionNotFoundError
from app.core.logging import get_logger
from app.schemas.brief import BriefCreateRequest, BriefResponse, BriefStatusResponse
from app.services.brief.brief_service import BriefService

router = APIRouter()
logger = get_logger(__name__)


@router.post("", response_model=BriefStatusResponse)
async def create_brief(
    payload: BriefCreateRequest,
    background_tasks: BackgroundTasks,
    service: BriefService = Depends(get_brief_service),
) -> BriefStatusResponse:
    """Kick off LangGraph brief generation for an ingested session."""
    try:
        status = await service.start_generation(payload.session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    background_tasks.add_task(run_brief_pipeline, status.brief_id, status.session_id)
    logger.info(
        "Queued brief generation brief_id=%s session_id=%s",
        status.brief_id,
        status.session_id,
    )
    return status


@router.get("/{brief_id}", response_model=BriefResponse)
async def get_brief(
    brief_id: UUID,
    service: BriefService = Depends(get_brief_service),
) -> BriefResponse:
    try:
        return await service.get_brief(brief_id)
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get("/{brief_id}/status", response_model=BriefStatusResponse)
async def get_brief_status(
    brief_id: UUID,
    service: BriefService = Depends(get_brief_service),
) -> BriefStatusResponse:
    try:
        return await service.get_status(brief_id)
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
