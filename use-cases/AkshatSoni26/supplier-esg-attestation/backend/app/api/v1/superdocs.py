import httpx
from fastapi import APIRouter, HTTPException, status, responses, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.superdocs import (
    SuperDocsChatRequest,
    SuperDocsChatResponse,
    SuperDocsApproveRequest,
    SuperDocsExportResponse,
)
from app.services.superdocs_service import SuperDocsClientService
from app.services.document_export_service import DocumentExportService

router = APIRouter(prefix="/superdocs", tags=["SuperDocs Integration"])


@router.post("/chat", response_model=SuperDocsChatResponse)
async def send_chat(payload: SuperDocsChatRequest):
    """Send targeted edit instruction to SuperDocs (returns diff cards with 2-step JSON parse)."""
    client = SuperDocsClientService()
    try:
        res = await client.send_chat_instruction(payload)
        return res
    except httpx.HTTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"SuperDocs communication error: {str(e)}")
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid payload format: {str(e)}")


@router.post("/approve")
async def approve_diffs(payload: SuperDocsApproveRequest):
    """Approve or reject proposed SuperDocs diffs."""
    client = SuperDocsClientService()
    try:
        ok = await client.approve_changes(payload)
        return {"status": "success", "approved": ok}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"SuperDocs approval communication error: {str(e)}")


@router.get("/export/{document_id}", response_model=SuperDocsExportResponse)
async def export_doc(document_id: str, format: str = "pdf"):
    """Export finalized document from SuperDocs."""
    client = SuperDocsClientService()
    try:
        res = await client.export_document(document_id, format_type=format)
        return res
    except httpx.HTTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"SuperDocs export communication error: {str(e)}")


@router.get("/download/{document_name}")
async def download_mock_file(document_name: str, db: AsyncSession = Depends(get_db)):
    """Generalized export endpoint serving dynamic documents (PDF, MD) via DocumentExportService."""
    service = DocumentExportService(db=db)
    format_type = "pdf" if document_name.endswith(".pdf") else "md"
    content_bytes, media_type, filename = await service.export_document(document_name, format_type=format_type)

    disposition = "inline" if format_type == "pdf" else "attachment"
    return responses.Response(
        content=content_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
    )
