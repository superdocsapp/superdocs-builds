from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Negotiation
from app.services import tracker_service
from app.superdocs_client import SuperDocsClient

router = APIRouter(tags=["tracker"])

# per docs/superdocs-api-reference.md, export defaults to docx; these are
# the formats worth a real Content-Type instead of a generic fallback
EXPORT_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "txt": "text/plain",
}


def get_client() -> SuperDocsClient:
    return SuperDocsClient()


@router.get("/negotiations/{negotiation_id}/open-items")
async def open_items(
    negotiation_id: str, db: Session = Depends(get_db), client: SuperDocsClient = Depends(get_client)
):
    try:
        return tracker_service.reconcile(db, client, negotiation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="negotiation not found")


@router.get("/negotiations/{negotiation_id}/export")
async def export(
    negotiation_id: str,
    format: str = "docx",
    db: Session = Depends(get_db),
    client: SuperDocsClient = Depends(get_client),
):
    negotiation = db.get(Negotiation, negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")

    content = client.export(negotiation.superdocs_session_id, format)
    media_type = EXPORT_CONTENT_TYPES.get(format, "application/octet-stream")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="agreement.{format}"'},
    )
