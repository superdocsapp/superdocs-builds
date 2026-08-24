"""Request/response models for the public API."""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TenantCreateResponse(BaseModel):
    tenant_id: str
    # Shown exactly once — the server stores only a hash.
    api_key: str
    key_prefix: str


class EditRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=8000)
    model_tier: str | None = None
    webhook_url: HttpUrl | None = None


class ExportRequest(BaseModel):
    format: str = Field(default="docx", pattern="^(docx|pdf|html|md|txt)$")
    webhook_url: HttpUrl | None = None


class DecisionRequest(BaseModel):
    approved: bool
    feedback: str | None = Field(default=None, max_length=2000)


class JobAccepted(BaseModel):
    job_id: str
    status: str
