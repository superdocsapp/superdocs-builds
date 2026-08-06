"""Pydantic models for AI Resume Analyzer."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EducationItem(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    details: str | None = None
    evidence: str = Field(
        ...,
        description="Exact resume span supporting this education entry",
    )


class ExperienceItem(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    evidence: str = Field(
        ...,
        description="Exact resume span supporting this experience entry",
    )


class ProjectItem(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    evidence: str = Field(
        ...,
        description="Exact resume span supporting this project entry",
    )


class AchievementItem(BaseModel):
    description: str
    evidence: str = Field(
        ...,
        description="Exact resume span supporting this achievement",
    )


class ResumeAnalysis(BaseModel):
    """Structured resume extraction. Unsupported fields stay empty/null — never invented."""

    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    achievements: list[AchievementItem] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    years_of_experience: float | None = Field(
        default=None,
        description="Only set when explicitly stated or fully supported by dated roles; else null",
    )
    years_of_experience_evidence: str | None = Field(
        default=None,
        description="Resume span supporting years_of_experience, if any",
    )


class ResumeExtractionOutput(BaseModel):
    """LLM extraction schema — evidence-grounded only."""

    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    achievements: list[AchievementItem] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    years_of_experience: float | None = None
    years_of_experience_evidence: str | None = None
    years_of_experience_explicitly_stated: bool = False


class EmbeddingInfo(BaseModel):
    session_id: UUID
    document_id: UUID
    chunk_count: int
    embedding_model: str
    dimensions: int
    source: str = "resume"


class ResumeAnalyzeTextRequest(BaseModel):
    resume_text: str = Field(..., min_length=1)
    candidate_name: str | None = None

    @field_validator("resume_text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("resume_text cannot be empty")
        return cleaned


class ResumeAnalyzerResponse(BaseModel):
    candidate_name: str | None = None
    analysis: ResumeAnalysis
    embeddings: EmbeddingInfo
    resume_char_count: int
    message: str = "Resume analyzed successfully"
