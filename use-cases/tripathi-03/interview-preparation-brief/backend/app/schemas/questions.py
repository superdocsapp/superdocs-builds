"""Pydantic models for interview question generation."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

NO_EVIDENCE = "No evidence found."
REVISION_PLACEHOLDER_BASE = "https://revise.local/topic"


class Difficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


class RevisionLink(BaseModel):
    title: str
    url: str = Field(
        description="Placeholder revision URL — replace with real learning resources later",
    )


class InterviewQuestionItem(BaseModel):
    question: str = Field(min_length=1)
    difficulty: Difficulty = Difficulty.MEDIUM
    expected_answer: str = Field(
        default=NO_EVIDENCE,
        description="Expected answer grounded in resume/JD/company data when available",
    )
    resume_evidence: str = Field(
        default=NO_EVIDENCE,
        description="Exact resume span supporting an answer, or 'No evidence found.'",
    )
    missing_knowledge: list[str] = Field(
        default_factory=list,
        description="Gaps the candidate should revise for this question",
    )
    revision_links: list[RevisionLink] = Field(
        default_factory=list,
        description="Placeholder revision links for missing topics",
    )

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question cannot be empty")
        return cleaned

    @field_validator("resume_evidence", "expected_answer")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = (value or "").strip()
        return cleaned or NO_EVIDENCE


class InterviewQuestionBank(BaseModel):
    technical_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    behavioral_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    company_specific_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    scenario_based_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    system_design_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    coding_questions: list[InterviewQuestionItem] = Field(default_factory=list)


class InterviewQuestionLLMOutput(BaseModel):
    """Structured LLM output before post-validation."""

    technical_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    behavioral_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    company_specific_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    scenario_based_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    system_design_questions: list[InterviewQuestionItem] = Field(default_factory=list)
    coding_questions: list[InterviewQuestionItem] = Field(default_factory=list)


class QuestionCategoryLLMOutput(BaseModel):
    """Smaller per-category payload — more reliable on free Groq JSON mode."""

    questions: list[InterviewQuestionItem] = Field(default_factory=list)


class InterviewQuestionRequest(BaseModel):
    resume_text: str = Field(..., min_length=1)
    jd_text: str = Field(..., min_length=1)
    company_name: str = Field(..., min_length=1)
    company_data: str | dict = Field(
        default="",
        description="Company research overview/JSON or free-text company context",
    )
    role_summary: str | None = None

    @field_validator("resume_text", "jd_text", "company_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field cannot be empty")
        return cleaned


class InterviewQuestionResponse(BaseModel):
    company_name: str
    question_bank: InterviewQuestionBank
    totals: dict[str, int]
    message: str = "Interview questions generated successfully"
