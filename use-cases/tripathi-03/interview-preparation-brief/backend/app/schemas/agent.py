"""Internal structured outputs used by LangGraph nodes."""

from pydantic import BaseModel, Field

from app.schemas.brief import (
    EvidenceAnswer,
    RoadmapPhase,
    SkillItem,
    StarAnswer,
)


class RoleSummaryOutput(BaseModel):
    role_summary: str
    required_skills: list[SkillItem] = Field(default_factory=list)


class SkillMatchOutput(BaseModel):
    matching_skills: list[SkillItem] = Field(default_factory=list)
    missing_skills: list[SkillItem] = Field(default_factory=list)
    gap_analysis_summary: str = ""
    resume_improvements: list[str] = Field(default_factory=list)
    technical_topics: list[str] = Field(default_factory=list)


class QuestionOutput(BaseModel):
    likely_interview_questions: list[str] = Field(
        default_factory=list,
        min_length=1,
        description="Up to 20 likely interview questions",
    )
    company_specific_questions: list[str] = Field(default_factory=list)
    behavioural_questions: list[str] = Field(
        default_factory=list,
        description="3-5 behavioural questions for STAR answers",
    )


class AnswerOutput(BaseModel):
    evidence_backed_answers: list[EvidenceAnswer] = Field(default_factory=list)
    star_answers: list[StarAnswer] = Field(default_factory=list)


class ReportExtrasOutput(BaseModel):
    roadmap: list[RoadmapPhase] = Field(default_factory=list)


class CompanyOverviewOutput(BaseModel):
    """Deprecated alias kept for compatibility; prefer CompanyExtractionOutput."""

    company_overview: str
    industry: str | None = None
    products: list[str] = Field(default_factory=list)
