"""SuperDocs integration routes — additive; does not replace local export APIs.

Minimum SuperDocs contract (Task 2):
  1. upload  2. chat (edit)  3. approve  4. export
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, BriefNotFoundError, LLMConfigurationError
from app.core.logging import get_logger
from app.database.session import get_db_session
from app.schemas.superdocs import (
    SuperDocsApproveRequest,
    SuperDocsApproveResponse,
    SuperDocsHealthResponse,
    SuperDocsJobStatusResponse,
    SuperDocsStartRequest,
    SuperDocsStartResponse,
)
from app.services.superdocs.service import SuperDocsBriefService

router = APIRouter()
logger = get_logger(__name__)


async def _db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


def _settings() -> Settings:
    return get_settings()


def get_superdocs_brief_service(
    db: AsyncSession = Depends(_db),
    settings: Settings = Depends(_settings),
) -> SuperDocsBriefService:
    return SuperDocsBriefService(db=db, settings=settings)


@router.get("/health", response_model=SuperDocsHealthResponse)
async def superdocs_health(
    settings: Settings = Depends(_settings),
) -> SuperDocsHealthResponse:
    ready = settings.superdocs_ready
    return SuperDocsHealthResponse(
        enabled=settings.superdocs_enabled,
        configured=ready,
        base_url=settings.superdocs_base_url,
        message=(
            "SuperDocs ready for upload -> chat -> approve -> export"
            if ready
            else "Set SUPERDOCS_ENABLED=true and SUPERDOCS_API_KEY to enable"
        ),
    )


@router.post(
    "/briefs/{brief_id}/start",
    response_model=SuperDocsStartResponse,
)
async def start_superdocs_polish(
    brief_id: UUID,
    payload: SuperDocsStartRequest | None = None,
    service: SuperDocsBriefService = Depends(get_superdocs_brief_service),
) -> SuperDocsStartResponse:
    """Upload brief HTML to SuperDocs and start an async polish job (HITL)."""
    body = payload or SuperDocsStartRequest()
    try:
        result = await service.start_polish(
            brief_id,
            instruction=body.instruction,
            approval_mode=body.approval_mode,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except AppError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return SuperDocsStartResponse(**result)


@router.get("/jobs/{job_id}", response_model=SuperDocsJobStatusResponse)
async def get_superdocs_job(
    job_id: str,
    service: SuperDocsBriefService = Depends(get_superdocs_brief_service),
) -> SuperDocsJobStatusResponse:
    try:
        result = await service.job_status(job_id)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except AppError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return SuperDocsJobStatusResponse(**result)


@router.post(
    "/sessions/{session_id}/approve",
    response_model=SuperDocsApproveResponse,
)
async def approve_superdocs_changes(
    session_id: str,
    payload: SuperDocsApproveRequest,
    service: SuperDocsBriefService = Depends(get_superdocs_brief_service),
) -> SuperDocsApproveResponse:
    decisions = None
    if payload.changes is not None:
        decisions = [c.model_dump(exclude_none=True) for c in payload.changes]
    try:
        result = await service.approve_changes(
            session_id=session_id,
            job_id=payload.job_id,
            approved=payload.approved,
            change_decisions=decisions,
            feedback=payload.feedback,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except AppError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return SuperDocsApproveResponse(**result)


@router.post("/sessions/{session_id}/export")
async def export_superdocs_document(
    session_id: str,
    format: str = Query(default="docx", pattern="^(docx|pdf|html|markdown|txt)$"),
    filename: str | None = Query(default="interview-preparation-brief"),
    service: SuperDocsBriefService = Depends(get_superdocs_brief_service),
) -> Response:
    try:
        content, content_type, out_name = await service.export(
            session_id=session_id,
            format=format,
            filename=filename,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except AppError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )
