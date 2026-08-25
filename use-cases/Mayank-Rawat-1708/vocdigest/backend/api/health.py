"""
@file: backend/api/health.py
@description: Liveness and readiness endpoints. Readiness reports which external
    dependencies are actually reachable and configured, without ever echoing a key —
    the response says "set" or "unset", never a value or a prefix.
@flow: GET /health returns immediately. GET /health/ready checks the database with a
    trivial query and reports credential presence so an operator can tell a missing key
    from a broken database.
@dependencies:
    - backend.db.database: connection check
    - backend.config.settings: credential presence flags
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from backend.config import settings
from backend.db.database import session_scope

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "vocdigest"}


@router.get("/health/ready")
async def ready() -> dict[str, Any]:
    """Readiness with per-dependency detail.

    Credential fields are booleans on purpose. Returning even a masked prefix would put
    key material into logs and browser history for no diagnostic gain.
    """
    database_ok = False
    database_error: str | None = None
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        database_error = type(exc).__name__
        logger.warning("Readiness DB check failed: %s", exc)

    return {
        "status": "ready" if database_ok else "degraded",
        "database": {"connected": database_ok, "error": database_error},
        "credentials": {
            "superdocs_api_key": bool(settings.superdocs_api_key),
            "groq_api_key": bool(settings.groq_api_key),
        },
        "config": {
            "superdocs_base_url": settings.superdocs_base_url,
            "groq_model": settings.groq_model,
            "embedding_backend": settings.embedding_backend,
            "embedding_dim": settings.embedding_dim,
        },
    }
