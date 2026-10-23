"""Aggregate API routers."""

from fastapi import APIRouter

from app.api.routes import briefs, company, documents, health, questions, reports, resume, superdocs

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(briefs.router, prefix="/briefs", tags=["briefs"])
api_router.include_router(company.router, prefix="/company", tags=["company"])
api_router.include_router(resume.router, prefix="/resume", tags=["resume"])
api_router.include_router(questions.router, prefix="/questions", tags=["questions"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(superdocs.router, prefix="/superdocs", tags=["superdocs"])
