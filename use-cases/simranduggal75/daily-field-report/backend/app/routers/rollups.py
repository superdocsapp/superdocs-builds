from datetime import date

from fastapi import APIRouter, HTTPException

from app.services.weekly_rollup import save_weekly_rollup


router = APIRouter(
    prefix="/api/v1/rollups",
    tags=["rollups"],
)


@router.get("/weekly")
async def get_weekly_rollup(
    project: str,
    start_date: date,
    end_date: date,
):
    """
    Aggregate the persisted daily reports for a project between
    start_date and end_date (inclusive) into a grounded weekly rollup.
    """

    if end_date < start_date:
        raise HTTPException(
            status_code=400,
            detail="end_date must not be before start_date.",
        )

    return save_weekly_rollup(
        project=project,
        start_date=start_date,
        end_date=end_date,
    )
