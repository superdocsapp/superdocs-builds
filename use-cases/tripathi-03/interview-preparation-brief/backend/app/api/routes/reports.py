"""Interview Preparation Report API — generate JSON and export DOCX/PDF/MD/HTML."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import get_interview_report_service
from app.core.exceptions import BriefNotFoundError
from app.core.logging import get_logger
from app.schemas.report import (
    ExportFormat,
    InterviewPreparationReportDocument,
    ReportGenerateRequest,
    ReportGenerateResponse,
)
from app.services.report.service import InterviewReportService

router = APIRouter()
logger = get_logger(__name__)


@router.post("/generate", response_model=ReportGenerateResponse)
async def generate_report(
    payload: ReportGenerateRequest,
    service: InterviewReportService = Depends(get_interview_report_service),
) -> ReportGenerateResponse:
    """Assemble a professional Interview Preparation Report as structured JSON."""
    report = service.generate(payload)
    logger.info("Generated report for company=%s score=%s", report.cover_page.company_name, report.resume_match_score.score)
    return ReportGenerateResponse(report=report)


@router.post("/from-brief/{brief_id}", response_model=ReportGenerateResponse)
async def generate_report_from_brief(
    brief_id: UUID,
    service: InterviewReportService = Depends(get_interview_report_service),
) -> ReportGenerateResponse:
    """Build a professional report from a completed brief."""
    try:
        report = await service.generate_from_brief(brief_id)
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return ReportGenerateResponse(report=report)


@router.post("/export")
async def export_report(
    report: InterviewPreparationReportDocument,
    format: ExportFormat = Query(default=ExportFormat.PDF, alias="format"),
    service: InterviewReportService = Depends(get_interview_report_service),
) -> Response:
    """Export a report document to Markdown, HTML, DOCX, PDF, or JSON."""
    payload, content_type, filename = service.export(report, format)
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{brief_id}/export")
async def export_brief_report(
    brief_id: UUID,
    format: ExportFormat = Query(default=ExportFormat.PDF, alias="format"),
    service: InterviewReportService = Depends(get_interview_report_service),
) -> Response:
    """Export a completed brief as a professionally formatted report file."""
    try:
        report = await service.generate_from_brief(brief_id)
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    payload, content_type, filename = service.export(report, format)
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
