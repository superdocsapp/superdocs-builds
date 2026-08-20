from typing import Literal

from pydantic import BaseModel, Field


ReviewDecision = Literal[
    "APPROVE",
    "REJECT",
    "REQUEST_CLARIFICATION",
]


class ReviewFindingRequest(BaseModel):
    reviewer: str = Field(
        min_length=1,
        max_length=255,
    )

    decision: ReviewDecision

    comment: str | None = None


class ReviewFindingResponse(BaseModel):
    finding_id: str
    status: str
    reviewer: str
    comment: str | None
    reviewed_at: str