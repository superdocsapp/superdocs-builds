"""Shared FastAPI dependencies (DB session, settings, services)."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.database.session import get_db_session
from app.services.brief.brief_service import BriefService
from app.services.brief.document_service import DocumentService
from app.services.company.company_research import CompanyResearchService
from app.services.questions.generator import InterviewQuestionGenerator
from app.services.report.service import InterviewReportService
from app.services.resume.analyzer import ResumeAnalyzerService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


def get_app_settings() -> Settings:
    return get_settings()


def get_document_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> DocumentService:
    return DocumentService(db=db, settings=settings)


def get_brief_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> BriefService:
    return BriefService(db=db, settings=settings)


def get_company_research_service() -> CompanyResearchService:
    return CompanyResearchService()


def get_resume_analyzer_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ResumeAnalyzerService:
    return ResumeAnalyzerService(db=db, settings=settings)


def get_question_generator() -> InterviewQuestionGenerator:
    return InterviewQuestionGenerator()


def get_interview_report_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> InterviewReportService:
    return InterviewReportService(db=db, settings=settings)
