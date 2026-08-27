from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

StrictText = Annotated[str, Field(min_length=1, max_length=10000)]

class FactKind(str, Enum):
    CHARACTER = "CHARACTER"
    RELATIONSHIP = "RELATIONSHIP"
    LOCATION = "LOCATION"
    TIMELINE = "TIMELINE"
    WORLD_RULE = "WORLD_RULE"

class FindingType(str, Enum):
    CONTRADICTION = "CONTRADICTION"
    POSSIBLE_CONTRADICTION = "POSSIBLE_CONTRADICTION"
    NEW_INFORMATION = "NEW_INFORMATION"
    COMPATIBLE_UPDATE = "COMPATIBLE_UPDATE"
    INTENTIONAL_CHANGE = "INTENTIONAL_CHANGE"

class Resolution(str, Enum):
    KEEP_EXISTING = "KEEP_EXISTING"
    ACCEPT_NEW = "ACCEPT_NEW"
    INTENTIONAL_CHANGE = "INTENTIONAL_CHANGE"
    REJECT = "REJECT"

class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: UUID
    chapter: StrictText
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    chunk_id: StrictText
    evidence_text: StrictText

class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: FactKind
    entity: StrictText
    attribute: StrictText
    value: StrictText
    source: SourceRef
    confidence: float = Field(ge=0, le=1)
    supported: bool = True

    @model_validator(mode="after")
    def grounded(self) -> ExtractedFact:
        if self.supported and self.source.evidence_text.strip() == "":
            raise ValueError("supported facts require exact evidence")
        return self

class FindingView(BaseModel):
    id: UUID
    type: FindingType
    entity: str
    attribute: str
    existing_value: str | None
    new_value: str
    existing_evidence: SourceRef | None
    new_evidence: SourceRef
    explanation: str
    confidence: float
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    status: str

class SeriesCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: str = Field(default="", max_length=2000)

class SeriesView(SeriesCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime

class ReviewRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    resolution: Resolution
    rationale: str = Field(default="", max_length=2000)

class ProposedEditRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=10000)

class ApprovalRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    approved: bool
    feedback: str = Field(default="", max_length=10000)
