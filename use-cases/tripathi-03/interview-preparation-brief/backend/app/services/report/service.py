"""Interview Preparation Report service — assemble + export."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import BriefNotFoundError
from app.core.logging import get_logger
from app.schemas.brief import BriefContent
from app.schemas.report import (
    ExportFormat,
    InterviewPreparationReportDocument,
    ReportGenerateRequest,
)
from app.services.brief.brief_service import BriefService
from app.services.report.assembler import ReportAssembler
from app.services.report.exporters import ReportExporter

logger = get_logger(__name__)


class InterviewReportService:
    def __init__(self, db: AsyncSession | None = None, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.assembler = ReportAssembler()
        self.exporter = ReportExporter()

    def generate(self, request: ReportGenerateRequest) -> InterviewPreparationReportDocument:
        return self.assembler.assemble(request)

    async def generate_from_brief(
        self,
        brief_id: UUID,
    ) -> InterviewPreparationReportDocument:
        if self.db is None:
            raise RuntimeError("Database session required to load brief")
        brief_service = BriefService(self.db, self.settings)
        brief = await brief_service.get_brief(brief_id)
        if brief.content is None:
            raise BriefNotFoundError("Brief has no completed content to export")
        return self.from_brief_content(brief.company_name, brief.content)

    def from_brief_content(
        self,
        company_name: str,
        content: BriefContent | dict,
        *,
        candidate_name: str | None = None,
        question_bank: dict | None = None,
    ) -> InterviewPreparationReportDocument:
        if isinstance(content, dict):
            content = BriefContent.model_validate(content)

        request = ReportGenerateRequest(
            company_name=company_name,
            company_overview=content.company_overview,
            role_summary=content.role_summary,
            candidate_name=candidate_name,
            target_role=content.role_summary.split("\n")[0][:120] if content.role_summary else None,
            required_skills=content.required_skills,
            matching_skills=content.matching_skills,
            missing_skills=content.missing_skills,
            gap_analysis_summary=content.gap_analysis.summary if content.gap_analysis else "",
            resume_improvements=content.resume_improvements,
            technical_topics=content.technical_topics,
            likely_interview_questions=content.likely_interview_questions,
            company_specific_questions=content.company_specific_questions,
            evidence_backed_answers=content.evidence_backed_answers,
            star_answers=content.star_answers,
            roadmap=content.roadmap,
            question_bank=question_bank,
        )
        return self.assembler.assemble(request)

    def export(
        self,
        report: InterviewPreparationReportDocument,
        fmt: ExportFormat | str,
    ) -> tuple[bytes, str, str]:
        if isinstance(fmt, str):
            fmt = ExportFormat(fmt.lower())
        payload, content_type, filename = self.exporter.export(report, fmt)
        logger.info("Exported report format=%s filename=%s bytes=%s", fmt, filename, len(payload))
        return payload, content_type, filename
