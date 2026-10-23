"""Resume Analyzer API endpoints."""

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_resume_analyzer_service
from app.core.exceptions import AppError, http_bad_request
from app.core.logging import get_logger
from app.schemas.resume import ResumeAnalyzeTextRequest, ResumeAnalyzerResponse
from app.services.resume.analyzer import ResumeAnalyzerService

router = APIRouter()
logger = get_logger(__name__)


@router.post("/analyze", response_model=ResumeAnalyzerResponse)
async def analyze_resume_upload(
    resume: UploadFile = File(..., description="Resume PDF or DOCX"),
    candidate_name: str | None = Form(default=None),
    service: ResumeAnalyzerService = Depends(get_resume_analyzer_service),
) -> ResumeAnalyzerResponse:
    """
    Analyze an uploaded resume.

    Extracts education, experience, projects, skills, achievements, technologies,
    and years of experience (only when supported). Creates pgvector embeddings.
    """
    try:
        result = await service.analyze_upload(
            resume=resume,
            candidate_name=candidate_name,
        )
        logger.info(
            "Resume upload analyzed document_id=%s chunks=%s",
            result.embeddings.document_id,
            result.embeddings.chunk_count,
        )
        return result
    except AppError as exc:
        raise http_bad_request(exc.message) from exc


@router.post("/analyze-text", response_model=ResumeAnalyzerResponse)
async def analyze_resume_text(
    payload: ResumeAnalyzeTextRequest,
    service: ResumeAnalyzerService = Depends(get_resume_analyzer_service),
) -> ResumeAnalyzerResponse:
    """Analyze raw resume text and create embeddings."""
    try:
        result = await service.analyze_text(
            resume_text=payload.resume_text,
            candidate_name=payload.candidate_name,
        )
        logger.info(
            "Resume text analyzed document_id=%s chunks=%s",
            result.embeddings.document_id,
            result.embeddings.chunk_count,
        )
        return result
    except AppError as exc:
        raise http_bad_request(exc.message) from exc
