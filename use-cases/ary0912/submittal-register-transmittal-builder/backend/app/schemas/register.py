from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


RegisterStatus = Literal[
    "NOT_RECEIVED",
    "RECEIVED",
    "UNDER_REVIEW",
    "REVIEWED",
    "OVERDUE",
]


class RegisterItemResponse(BaseModel):
    id: str
    project_id: str
    number: str
    title: str
    description: str | None
    specification_section: str
    required_by: str | None
    required_form: str | None
    source_evidence: str | None
    specification_revision: str | None
    status: str
    register_status: RegisterStatus
    due_date: date | None
    created_at: datetime
    updated_at: datetime | None
    finding_count: int = 0
    unresolved_finding_count: int = 0
    reviewed_finding_count: int = 0


class SubmittalDetailResponse(RegisterItemResponse):
    findings: list[dict] = Field(default_factory=list)
    transmittal: dict | None = None


class RegisterResponse(BaseModel):
    project_id: str
    items: list[RegisterItemResponse]


class RegisterStatusUpdate(BaseModel):
    status: RegisterStatus


class OverdueRegisterResponse(BaseModel):
    project_id: str
    overdue_count: int
    items: list[RegisterItemResponse]


class RegisterRequirementRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    specification_section: str = Field(min_length=1)
    required_by: str | None = None
    required_form: str | None = None
    source_evidence: str = Field(min_length=1)
    specification_revision: str | None = None
    due_date: date | None = None


class GenerateRegisterRequest(BaseModel):
    requirements: list[RegisterRequirementRequest]


class GenerateRegisterResponse(BaseModel):
    project_id: str
    count: int
    items: list[RegisterItemResponse]


class RegisterRequirement(RegisterRequirementRequest):
    """Normalized input boundary for future extraction adapters."""
    pass
