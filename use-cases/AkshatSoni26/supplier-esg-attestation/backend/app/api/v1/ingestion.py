from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from app.db.session import get_db
from app.db.models import AttestationCycleModel
from app.schemas.enums import AttestationStatus
from app.services.ingestion_service import IngestionService
from app.services.normalization_service import NormalizationService

router = APIRouter(prefix="/ingestion", tags=["Response Ingestion"])


@router.post("/upload")
async def upload_supplier_response(
    attestation_id: str = Form(...),
    file: UploadFile = File(...),
    auto_normalize: bool = Form(True),
    db: AsyncSession = Depends(get_db)
):
    """
    Ingest supplier responses in any format (PDF, DOCX, TXT, MD, JSON).
    Automatically saves, uploads to SuperDocs, and normalizes into assessment schema.
    """
    # Verify attestation exists
    stmt = select(AttestationCycleModel).where(AttestationCycleModel.id == attestation_id)
    res = await db.execute(stmt)
    attestation = res.scalar_one_or_none()
    if not attestation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attestation cycle not found")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    ingestion_service = IngestionService()
    try:
        local_path, extracted_text, sd_doc_id = await ingestion_service.process_incoming_response(
            attestation_id=attestation_id,
            filename=file.filename or "response.txt",
            file_bytes=file_bytes
        )

        attestation.status = AttestationStatus.SUBMITTED.value
        attestation.response_document_id = sd_doc_id
        attestation.response_document_name = file.filename
        attestation.response_format = (file.filename.split(".")[-1] if file.filename else "txt").upper()
        attestation.submitted_at = datetime.now(timezone.utc)
        await db.commit()

        assessment_id = None
        if auto_normalize:
            norm_service = NormalizationService(db=db)
            assessment = await norm_service.normalize_attestation(attestation_id, extracted_text)
            assessment_id = assessment.id

        return {
            "status": "success",
            "attestation_id": attestation_id,
            "filename": file.filename,
            "superdocs_document_id": sd_doc_id,
            "characters_extracted": len(extracted_text),
            "auto_normalized": auto_normalize,
            "assessment_id": assessment_id,
            "message": "Supplier response ingested and normalized successfully."
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (OSError, IOError) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"File storage error: {str(e)}")
    except Exception as e:
        # Catch unexpected schema errors while strictly surfacing the error class name
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ingestion processing error ({type(e).__name__}): {str(e)}")
