"""Pydantic Input/Output contracts for each LangGraph node."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.schemas.brief import (
    EvidenceAnswer,
    RoadmapPhase,
    SkillItem,
    StarAnswer,
)

NO_EVIDENCE = "No evidence found."


# ---------------------------------------------------------------------------
# ResumeParser
# ---------------------------------------------------------------------------


class ResumeParserInput(BaseModel):
    session_id: str = Field(min_length=1)
    resume_text: str = Field(min_length=1)

    @field_validator("resume_text")
    @classmethod
    def strip_resume(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("resume_text cannot be empty")
        return cleaned


class ResumeParserOutput(BaseModel):
    resume_normalized: str = Field(min_length=1)
    resume_char_count: int = Field(ge=1)


# ---------------------------------------------------------------------------
# JDParser
# ---------------------------------------------------------------------------


class JDParserInput(BaseModel):
    session_id: str = Field(min_length=1)
    jd_text: str = Field(min_length=1)

    @field_validator("jd_text")
    @classmethod
    def strip_jd(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("jd_text cannot be empty")
        return cleaned


class JDParserOutput(BaseModel):
    role_summary: str = Field(min_length=1)
    required_skills: list[SkillItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# CompanyResearch
# ---------------------------------------------------------------------------


class CompanyResearchInput(BaseModel):
    session_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    company_url: str | None = None


class CompanyResearchOutput(BaseModel):
    company_overview: str = Field(min_length=1)
    company_context: str = ""
    company_profile: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# SkillGapAnalysis
# ---------------------------------------------------------------------------


class SkillGapAnalysisInput(BaseModel):
    session_id: str = Field(min_length=1)
    resume_normalized: str = Field(min_length=1)
    jd_text: str = Field(min_length=1)
    role_summary: str = Field(min_length=1)
    required_skills: list[SkillItem] = Field(default_factory=list)


class SkillGapAnalysisOutput(BaseModel):
    matching_skills: list[SkillItem] = Field(default_factory=list)
    missing_skills: list[SkillItem] = Field(default_factory=list)
    gap_analysis_summary: str = ""
    resume_improvements: list[str] = Field(default_factory=list)
    technical_topics: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# QuestionGeneration
# ---------------------------------------------------------------------------


class QuestionGenerationInput(BaseModel):
    session_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    company_overview: str = ""
    role_summary: str = Field(min_length=1)
    required_skills: list[SkillItem] = Field(default_factory=list)
    matching_skills: list[SkillItem] = Field(default_factory=list)
    missing_skills: list[SkillItem] = Field(default_factory=list)
    jd_text: str = ""
    resume_normalized: str = ""


class QuestionGenerationOutput(BaseModel):
    likely_interview_questions: list[str] = Field(min_length=1)
    company_specific_questions: list[str] = Field(default_factory=list)
    behavioural_questions: list[str] = Field(default_factory=list)

    @field_validator("likely_interview_questions")
    @classmethod
    def non_empty_questions(cls, value: list[str]) -> list[str]:
        cleaned = [q.strip() for q in value if q and q.strip()]
        if not cleaned:
            raise ValueError("likely_interview_questions must contain at least one question")
        return cleaned


# ---------------------------------------------------------------------------
# AnswerGeneration
# ---------------------------------------------------------------------------


class AnswerGenerationInput(BaseModel):
    session_id: str = Field(min_length=1)
    likely_interview_questions: list[str] = Field(min_length=1)
    behavioural_questions: list[str] = Field(default_factory=list)
    evidence_fallback: str = NO_EVIDENCE


class AnswerGenerationOutput(BaseModel):
    evidence_backed_answers: list[EvidenceAnswer] = Field(default_factory=list)
    star_answers: list[StarAnswer] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# InterviewPreparationReport
# ---------------------------------------------------------------------------


class InterviewPreparationReportInput(BaseModel):
    session_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    company_overview: str = ""
    role_summary: str = Field(min_length=1)
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


class InterviewPreparationReportOutput(BaseModel):
    roadmap: list[RoadmapPhase] = Field(default_factory=list)
    report: dict = Field(default_factory=dict)

    @field_validator("report")
    @classmethod
    def report_not_empty(cls, value: dict) -> dict:
        if not value:
            raise ValueError("report payload cannot be empty")
        return value
