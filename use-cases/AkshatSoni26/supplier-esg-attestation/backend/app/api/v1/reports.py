from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.report import ProgrammeReportResponse
from app.services.aggregation_service import AggregationService

from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/reports", tags=["Executive Programme Reports"])


@router.get("/programme-summary", response_model=ProgrammeReportResponse)
async def get_programme_summary(
    cycle_year: int = 2026,
    db: AsyncSession = Depends(get_db)
):
    """
    Get aggregate ESG attestation statistics, risk profiles, pillar compliance averages,
    and chart data points for the executive dashboard and report.
    """
    service = AggregationService(db=db)
    try:
        metrics = await service.get_programme_metrics(cycle_year=cycle_year)
        return metrics
    except SQLAlchemyError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database aggregation error: {str(e)}")
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Data calculation error: {str(e)}")
