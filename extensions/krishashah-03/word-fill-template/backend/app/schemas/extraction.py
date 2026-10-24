from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    template_id: UUID
    input_type: Literal["text", "json", "csv"]
    content: Any = Field(..., description="Raw input: string for text/csv, string or object for json")


class ValidationIssueOut(BaseModel):
    field: str
    message: str


class GapOut(BaseModel):
    field: str
    reason: str


class ConditionResultOut(BaseModel):
    condition_key: str
    action: str
    resolved: bool
    include: Optional[bool] = None


class ProposedChangeOut(BaseModel):
    field: str
    placeholder: str
    current_value: Optional[Any] = None
    proposed_value: Optional[Any] = None
    status: str


class ExtractResponse(BaseModel):
    source_type: str
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any]
    validation_issues: list[ValidationIssueOut] = []
    gaps: list[GapOut] = []
    conditions: list[ConditionResultOut] = []
    proposed_changes: list[ProposedChangeOut] = []


class ValidateRequest(BaseModel):
    template_id: UUID
    normalized_data: dict[str, Any]
