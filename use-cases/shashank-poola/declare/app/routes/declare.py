from __future__ import annotations

from fastapi import APIRouter

from routes.analyze import router as analyze_router
from routes.statements import router as statements_router

router = APIRouter(prefix="/api/declare")
router.include_router(analyze_router)
router.include_router(statements_router)
