"""Document upload and parsing endpoints."""

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_document_service
from app.core.exceptions import AppError, http_bad_request
from app.core.logging import get_logger
from app.schemas.document import DocumentUploadResponse
from app.services.brief.document_service import DocumentService

router = APIRouter()
logger = get_logger(__name__)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_documents(
    resume: UploadFile = File(..., description="Candidate resume (PDF/DOCX)"),
    job_description: UploadFile | None = File(
        default=None,
        description="Job description file (PDF/DOCX)",
    ),
    job_description_text: str | None = Form(
        default=None,
        description="Job description as plain text",
    ),
    company_name: str = Form(..., description="Target company name"),
    company_url: str | None = Form(default=None),
    service: DocumentService = Depends(get_document_service),
) -> DocumentUploadResponse:
    """
    Upload resume + JD and company metadata.

    Parses PDF/DOCX, stores text, and indexes embeddings in pgvector.
    """
    try:
        result = await service.ingest(
            resume=resume,
            job_description=job_description,
            job_description_text=job_description_text,
            company_name=company_name,
            company_url=company_url,
        )
        logger.info("Upload complete session_id=%s", result.session_id)
        return result
    except AppError as exc:
        raise http_bad_request(exc.message) from exc
