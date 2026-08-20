from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.superdocs import superdocs_client
from app.services.freight_claim import freight_claim_service


router = APIRouter(
    prefix="/api/approval",
    tags=["approval"],
)


class ApprovalRequest(BaseModel):
    session_id: str
    job_id: str
    change_id: str
    approved: bool
    feedback: str | None = None


class ApprovalAllRequest(BaseModel):
    session_id: str
    job_id: str
    changes: list


@router.post("")
async def approval(request: ApprovalRequest):
    try:
        result = await superdocs_client.approve_change(
            session_id=request.session_id,
            job_id=request.job_id,
            change_id=request.change_id,
            approved=request.approved,
            feedback=request.feedback,
        )

        claim = await freight_claim_service.get_by_session(
            request.session_id
        )

        if claim:
            if request.approved:
                claim.status = "approved"
            else:
                claim.status = "rejected"

            claim.pending_changes = [
                change
                for change in claim.pending_changes
                if change.get("change_id") != request.change_id
            ]

        return result

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )


@router.post("/all")
async def approve_all(request: ApprovalAllRequest):
    try:
        result = await superdocs_client.approve_all(
            session_id=request.session_id,
            job_id=request.job_id,
            changes=request.changes,
        )

        claim = await freight_claim_service.get_by_session(
            request.session_id
        )

        if claim:
            claim.status = "approved"
            claim.pending_changes = []

        return result

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )