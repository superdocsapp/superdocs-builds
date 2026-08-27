from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="Release readiness review", min_length=1, max_length=240)


class DecisionInput(BaseModel):
    finding_id: str
    state: Literal["approved", "rejected", "more_evidence"]
    feedback: str | None = Field(default=None, max_length=4000)
    reviewer: str = Field(default="local-reviewer", max_length=120)


class DecisionBatch(BaseModel):
    decisions: list[DecisionInput]


class MCPRequest(BaseModel):
    operation: Literal[
        "get_run",
        "list_findings",
        "get_report",
        "submit_decisions",
        "resume_run",
    ]
    run_id: str
    payload: dict = Field(default_factory=dict)
