"""Aggregates all API routers into one include point."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import admin, approvals, documents, edits, exports, health, jobs

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(admin.router)
api_router.include_router(documents.router)
api_router.include_router(edits.router)
api_router.include_router(approvals.router)
api_router.include_router(exports.router)
api_router.include_router(jobs.router)
