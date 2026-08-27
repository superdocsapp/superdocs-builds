from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CURRENT_ENVELOPE_VERSION = "1.0"
Identifier = Annotated[str, Field(
    min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")]
Instruction = Annotated[str, Field(min_length=1, max_length=2000)]
SectionReference = Annotated[str, Field(min_length=1, max_length=256)]


class EnvelopeVersion(StrEnum):
    V1 = "1.0"


class ReviewState(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Instruction
    target_sections: list[SectionReference] = Field(
        min_length=1, max_length=100)


class Restrictions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forbidden_sections: list[SectionReference] = Field(
        default_factory=list, max_length=100)
    forbidden_actions: list[Instruction] = Field(
        default_factory=list, max_length=100)


class HandoffEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    envelope_version: Literal[EnvelopeVersion.V1] = EnvelopeVersion.V1
    document_id: Identifier
    assigned_to: Identifier
    scope: Scope
    restrictions: Restrictions = Field(default_factory=Restrictions)
    review_state: ReviewState
    issued_by: Identifier
    issued_at: datetime

    @model_validator(mode="after")
    def validate_instructions(self) -> "HandoffEnvelope":
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise ValueError(
                "issued_at must include an explicit UTC offset or timezone")

        target_sections = set(self.scope.target_sections)
        forbidden_sections = set(self.restrictions.forbidden_sections)
        overlap = sorted(target_sections & forbidden_sections)
        if overlap:
            raise ValueError(
                "scope.target_sections and restrictions.forbidden_sections overlap: "
                + ", ".join(overlap))
        return self


def json_schema() -> dict:
    return HandoffEnvelope.model_json_schema()


def validate_envelope(raw: dict) -> HandoffEnvelope:
    return HandoffEnvelope.model_validate(raw)
