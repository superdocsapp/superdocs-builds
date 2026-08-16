from fastapi import APIRouter

from app.services.nightly_batch import run_nightly_batch


router = APIRouter(
    prefix="/api/v1/batch",
    tags=["batch"],
)


@router.post("/run")
async def run_batch():
    """
    Run the nightly batch on demand, so the pending-report catch-up
    behavior can be demoed without waiting for a real night to pass.
    """

    return await run_nightly_batch()
