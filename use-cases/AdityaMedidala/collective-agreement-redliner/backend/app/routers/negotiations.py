from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import negotiation_service
from app.superdocs_client import SuperDocsClient

router = APIRouter(prefix="/negotiations", tags=["negotiations"])


def get_client() -> SuperDocsClient:
    return SuperDocsClient()


@router.post("")
async def start_negotiation(
    name: str = Form(...),
    cba: UploadFile = File(...),
    union_position: UploadFile = File(...),
    employer_position: UploadFile = File(...),
    db: Session = Depends(get_db),
    client: SuperDocsClient = Depends(get_client),
):
    negotiation = negotiation_service.start_negotiation(
        db, client, name, await cba.read(), await union_position.read(), await employer_position.read()
    )
    return {"id": negotiation.id, "name": negotiation.name, "session_id": negotiation.superdocs_session_id}
