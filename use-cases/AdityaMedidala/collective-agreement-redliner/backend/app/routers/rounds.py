from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import round_service
from app.superdocs_client import SuperDocsClient

router = APIRouter(tags=["rounds"])


def get_client() -> SuperDocsClient:
    return SuperDocsClient()


class StartRoundRequest(BaseModel):
    prompt: str | None = None


@router.post("/negotiations/{negotiation_id}/rounds")
async def start_round(
    negotiation_id: str,
    req: StartRoundRequest,
    db: Session = Depends(get_db),
    client: SuperDocsClient = Depends(get_client),
):
    round_ = round_service.start_round(db, client, negotiation_id, req.prompt)
    return {"round_id": round_.id, "superdocs_job_id": round_.superdocs_job_id, "status": round_.status}


class DecisionRequest(BaseModel):
    chunk_id: str
    approved: bool
    feedback: str | None = None


@router.get("/rounds/{round_id}/pending-changes")
async def pending_changes(
    round_id: str, db: Session = Depends(get_db), client: SuperDocsClient = Depends(get_client)
):
    try:
        changes = round_service.list_pending_changes(db, client, round_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="round not found")
    return {"round_id": round_id, "pending_changes": changes}


@router.post("/rounds/{round_id}/decisions")
async def decide(
    round_id: str,
    decisions: list[DecisionRequest],
    db: Session = Depends(get_db),
    client: SuperDocsClient = Depends(get_client),
):
    try:
        round_ = round_service.decide(db, client, round_id, [d.model_dump() for d in decisions])
    except ValueError:
        raise HTTPException(status_code=404, detail="round not found")
    return {"round_id": round_.id, "status": round_.status}
