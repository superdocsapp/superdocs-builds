from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import FollowUpLetterModel
from app.schemas.followup import FollowUpLetterCreate, FollowUpLetterResponse, FollowUpLetterStatusUpdate
from app.services.follow_up_service import FollowUpService

router = APIRouter(prefix="/follow-ups", tags=["Follow-up Remediation Letters"])


@router.post("/generate", response_model=FollowUpLetterResponse)
async def generate_letter(
    payload: FollowUpLetterCreate,
    db: AsyncSession = Depends(get_db)
):
    """Generate a formal deficiency follow-up letter directly quoting supplier responses."""
    service = FollowUpService(db=db)
    try:
        letter = await service.generate_follow_up_letter(payload)
        return letter
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (KeyError, AttributeError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid attestation state: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Generation failed ({type(e).__name__}): {str(e)}")


@router.get("/by-attestation/{attestation_id}", response_model=list[FollowUpLetterResponse])
async def get_letters_by_attestation(attestation_id: str, db: AsyncSession = Depends(get_db)):
    """Get all drafted/sent follow-up letters for an attestation cycle."""
    stmt = (
        select(FollowUpLetterModel)
        .where(FollowUpLetterModel.attestation_id == attestation_id)
        .order_by(FollowUpLetterModel.created_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()


@router.patch("/{letter_id}/status", response_model=FollowUpLetterResponse)
async def update_letter_status(
    letter_id: str,
    payload: FollowUpLetterStatusUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update letter status (DRAFT -> APPROVED -> SENT)."""
    stmt = select(FollowUpLetterModel).where(FollowUpLetterModel.id == letter_id)
    res = await db.execute(stmt)
    letter = res.scalar_one_or_none()
    if not letter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Letter not found")

    letter.status = payload.status.value
    await db.commit()
    await db.refresh(letter)
    return letter
