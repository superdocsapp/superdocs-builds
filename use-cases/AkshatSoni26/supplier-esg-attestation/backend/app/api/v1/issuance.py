from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import AttestationCycleModel
from app.schemas.questionnaire import (
    QuestionnaireIssuanceRequest,
    QuestionnaireIssuanceResponse,
    AttestationCycleResponse,
)
from app.services.issuance_service import IssuanceService

from sqlalchemy.exc import SQLAlchemyError
import httpx

router = APIRouter(prefix="/issuance", tags=["Questionnaire Issuance"])


@router.post("/issue", response_model=QuestionnaireIssuanceResponse)
async def issue_questionnaire(
    payload: QuestionnaireIssuanceRequest,
    db: AsyncSession = Depends(get_db)
):
    """Generate and issue localized, tier-specific code of conduct and questionnaire."""
    service = IssuanceService(db=db)
    try:
        response = await service.issue_questionnaire(payload)
        return response
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"SuperDocs upstream communication error: {str(e)}")
    except (SQLAlchemyError, OSError) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database or storage error: {type(e).__name__}: {str(e)}")


@router.get("/cycles", response_model=list[AttestationCycleResponse])
async def list_attestation_cycles(
    cycle_year: int = 2026,
    db: AsyncSession = Depends(get_db)
):
    """List all active attestation cycles for the year."""
    stmt = (
        select(AttestationCycleModel)
        .where(AttestationCycleModel.cycle_year == cycle_year)
        .order_by(AttestationCycleModel.updated_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/cycles/{attestation_id}", response_model=AttestationCycleResponse)
async def get_attestation_cycle(
    attestation_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get single attestation cycle details."""
    stmt = select(AttestationCycleModel).where(AttestationCycleModel.id == attestation_id)
    res = await db.execute(stmt)
    cycle = res.scalar_one_or_none()
    if not cycle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attestation cycle not found")
    return cycle
