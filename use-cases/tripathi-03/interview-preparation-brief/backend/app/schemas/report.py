"""Professional Interview Preparation Report schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.brief import (
    EvidenceAnswer,
    RoadmapPhase,
    SkillItem,
    StarAnswer,
)
from app.schemas.questions import InterviewQuestionBank


class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    DOCX = "docx"
    PDF = "pdf"
    JSON = "json"


class CoverPage(BaseModel):
    title: str = "Interview Preparation Report"
    candidate_name: str | None = None
    company_name: str
    target_role: str | None = None
    prepared_on: datetime = Field(default_factory=datetime.utcnow)
    tagline: str = "Evidence-grounded interview preparation — no fabricated experience"


class MatchScore(BaseModel):
    score: int = Field(ge=0, le=100)
    matching_count: int = 0
    missing_count: int = 0
    required_count: int = 0
    summary: str = ""


class RevisionItem(BaseModel):
    topic: str
    reason: str = ""
    priority: str = "Medium"  # High | Medium | Low
    revision_link: str = "https://revise.local/topic/overview"


class InterviewPreparationReportDocument(BaseModel):
    """Full professional report with all required sections."""

    cover_page: CoverPage
    company_overview: str = ""
    role_summary: str = ""
    resume_match_score: MatchScore = Field(default_factory=MatchScore)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    skill_gap: dict = Field(default_factory=dict)
    resume_improvements: list[str] = Field(default_factory=list)
    interview_questions: InterviewQuestionBank | dict = Field(default_factory=dict)
    evidence_backed_answers: list[EvidenceAnswer] = Field(default_factory=list)
    behavioral_answers: list[EvidenceAnswer] = Field(default_factory=list)
    star_stories: list[StarAnswer] = Field(default_factory=list)
    revision_plan: list[RevisionItem] = Field(default_factory=list)
    day_30_60_90_plan: list[RoadmapPhase] = Field(default_factory=list)
    final_recommendations: list[str] = Field(default_factory=list)

    # Optional flat lists for compatibility with existing brief UI
    likely_interview_questions: list[str] = Field(default_factory=list)
    company_specific_questions: list[str] = Field(default_factory=list)
    technical_topics: list[str] = Field(default_factory=list)
    matching_skills: list[SkillItem] = Field(default_factory=list)
    missing_skills: list[SkillItem] = Field(default_factory=list)
    required_skills: list[SkillItem] = Field(default_factory=list)


class ReportGenerateRequest(BaseModel):
    """Generate a report from provided grounded inputs (or from a completed brief)."""

    company_name: str
    company_overview: str = ""
    role_summary: str = ""
    candidate_name: str | None = None
    target_role: str | None = None
    required_skills: list[SkillItem] = Field(default_factory=list)
    matching_skills: list[SkillItem] = Field(default_factory=list)
    missing_skills: list[SkillItem] = Field(default_factory=list)
    gap_analysis_summary: str = ""
    resume_improvements: list[str] = Field(default_factory=list)
    technical_topics: list[str] = Field(default_factory=list)
    likely_interview_questions: list[str] = Field(default_factory=list)
    company_specific_questions: list[str] = Field(default_factory=list)
    evidence_backed_answers: list[EvidenceAnswer] = Field(default_factory=list)
    star_answers: list[StarAnswer] = Field(default_factory=list)
    roadmap: list[RoadmapPhase] = Field(default_factory=list)
    question_bank: dict | None = None
    final_recommendations: list[str] = Field(default_factory=list)


class ReportGenerateResponse(BaseModel):
    report: InterviewPreparationReportDocument
    message: str = "Interview Preparation Report generated successfully"


class ReportExportResponse(BaseModel):
    format: ExportFormat
    filename: str
    content_type: str
    # For JSON/Markdown/HTML text payloads; binary formats use StreamingResponse instead
    content: str | None = None
