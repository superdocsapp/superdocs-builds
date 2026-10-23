"""Pydantic schemas for SuperDocs integration endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SuperDocsStartRequest(BaseModel):
    instruction: str | None = Field(
        default=None,
        description="Optional polish instruction. Defaults to formatting-only prompt.",
    )
    approval_mode: str = Field(
        default="ask_every_time",
        description="ask_every_time (HITL) or approve_all",
    )


class SuperDocsStartResponse(BaseModel):
    brief_id: str
    session_id: str
    job_id: str
    status: str
    approval_mode: str
    upload: dict[str, Any] = Field(default_factory=dict)
    message: str


class SuperDocsJobStatusResponse(BaseModel):
    job_id: str
    status: str
    pending_changes: list[dict[str, Any]] = Field(default_factory=list)
    pending_count: int = 0
    ai_response: str | None = None
    raw_metadata_keys: list[str] = Field(default_factory=list)


class ChangeDecision(BaseModel):
    change_id: str
    approved: bool
    feedback: str | None = None


class SuperDocsApproveRequest(BaseModel):
    job_id: str
    approved: bool = True
    changes: list[ChangeDecision] | None = None
    feedback: str | None = None


class SuperDocsApproveResponse(BaseModel):
    session_id: str
    job_id: str
    approved: bool
    result: dict[str, Any] = Field(default_factory=dict)
    message: str


class SuperDocsHealthResponse(BaseModel):
    enabled: bool
    configured: bool
    base_url: str
    message: str
