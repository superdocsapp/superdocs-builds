from fastapi import APIRouter, HTTPException

from app.superdocs.client import (
    SuperDocsClient,
    SuperDocsError,
)


router = APIRouter(
    prefix="/superdocs",
    tags=["superdocs"],
)


@router.get("/health")
async def superdocs_health():
    client = SuperDocsClient()

    try:
        sessions = await client.verify_key()

        return {
            "status": "ok",
            "superdocs": "connected",
            "sessions": sessions,
        }

    except SuperDocsError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )