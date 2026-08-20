from typing import Any, Literal

from pydantic import BaseModel, Field


DocumentType = Literal[
    "pod",
    "invoice",
    "damage_photo",
    "repair_quote",
    "salvage_quote",
]


class ClaimEvidence(BaseModel):
    filename: str
    document_type: DocumentType
    upload_id: str | None = None
    session_id: str | None = None
    content: str | None = None


class FreightClaimCreate(BaseModel):
    carrier: str = Field(..., min_length=1)
    evidence: list[ClaimEvidence] = Field(
        default_factory=list
    )


class FreightClaim(BaseModel):
    claim_id: str
    session_id: str
    carrier: str

    evidence: list[ClaimEvidence] = Field(
        default_factory=list
    )

    status: str = "created"

    job_id: str | None = None

    pending_changes: list[dict[str, Any]] = Field(
        default_factory=list
    )

    claim_response: dict[str, Any] | None = None

    packet_response: dict[str, Any] | None = None

    chaser_response: dict[str, Any] | None = None