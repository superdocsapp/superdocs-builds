from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.db.models import AssessmentModel, FindingModel
from app.schemas.assessment import AssessmentResponse

router = APIRouter(prefix="/assessments", tags=["Assessments"])


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(assessment_id: str, db: AsyncSession = Depends(get_db)):
    """Get single assessment with its full findings."""
    stmt = (
        select(AssessmentModel)
        .options(selectinload(AssessmentModel.findings))
        .where(AssessmentModel.id == assessment_id)
    )
    res = await db.execute(stmt)
    assessment = res.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


@router.get("/by-attestation/{attestation_id}", response_model=AssessmentResponse | None)
async def get_assessment_by_attestation(attestation_id: str, db: AsyncSession = Depends(get_db)):
    """Get assessment for a specific attestation cycle (returns null if not yet submitted/evaluated)."""
    stmt = (
        select(AssessmentModel)
        .options(selectinload(AssessmentModel.findings))
        .where(AssessmentModel.attestation_id == attestation_id)
    )
    res = await db.execute(stmt)
    assessment = res.scalar_one_or_none()
    return assessment
