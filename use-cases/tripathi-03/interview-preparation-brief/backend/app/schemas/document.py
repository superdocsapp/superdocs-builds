"""Pydantic schemas for documents and upload responses."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentSource(str, Enum):
    RESUME = "resume"
    JD = "jd"
    COMPANY = "company"


class DocumentUploadResponse(BaseModel):
    session_id: UUID
    resume_document_id: UUID
    jd_document_id: UUID
    company_name: str
    message: str = "Documents ingested successfully"


class DocumentMeta(BaseModel):
    id: UUID
    source: DocumentSource
    filename: str | None = None
    char_count: int = 0
    created_at: datetime


class SessionResponse(BaseModel):
    session_id: UUID
    company_name: str
    company_url: str | None = None
    documents: list[DocumentMeta] = Field(default_factory=list)
