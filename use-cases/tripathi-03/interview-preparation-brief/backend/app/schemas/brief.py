"""Pydantic schemas for the Interview Preparation Brief document."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class BriefStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BriefCreateRequest(BaseModel):
    session_id: UUID


class BriefStatusResponse(BaseModel):
    brief_id: UUID
    session_id: UUID
    status: BriefStatus
    current_step: str | None = None
    error: str | None = None


class SkillItem(BaseModel):
    name: str
    category: str | None = None
    evidence: str | None = None


class GapAnalysis(BaseModel):
    matching_skills: list[SkillItem] = Field(default_factory=list)
    missing_skills: list[SkillItem] = Field(default_factory=list)
    summary: str = ""


class EvidenceAnswer(BaseModel):
    question: str
    answer: str
    evidence_spans: list[str] = Field(default_factory=list)
    has_evidence: bool = False


class StarAnswer(BaseModel):
    question: str
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    has_evidence: bool = False
    note: str | None = None


class RoadmapPhase(BaseModel):
    phase: str
    goals: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class BriefContent(BaseModel):
    company_overview: str = ""
    role_summary: str = ""
    required_skills: list[SkillItem] = Field(default_factory=list)
    gap_analysis: GapAnalysis = Field(default_factory=GapAnalysis)
    matching_skills: list[SkillItem] = Field(default_factory=list)
    missing_skills: list[SkillItem] = Field(default_factory=list)
    resume_improvements: list[str] = Field(default_factory=list)
    likely_interview_questions: list[str] = Field(default_factory=list)
    evidence_backed_answers: list[EvidenceAnswer] = Field(default_factory=list)
    technical_topics: list[str] = Field(default_factory=list)
    company_specific_questions: list[str] = Field(default_factory=list)
    star_answers: list[StarAnswer] = Field(default_factory=list)
    roadmap: list[RoadmapPhase] = Field(default_factory=list)


class BriefResponse(BaseModel):
    brief_id: UUID
    session_id: UUID
    status: BriefStatus
    company_name: str
    content: BriefContent | None = None
    created_at: datetime
    updated_at: datetime
