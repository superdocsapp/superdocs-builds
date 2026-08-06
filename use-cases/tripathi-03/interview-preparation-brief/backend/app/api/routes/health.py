"""Health check endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_db
from app.core.config import Settings

router = APIRouter()


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {
        "status": "healthy",
        "service": settings.app_name,
        "environment": settings.app_env,
    }
