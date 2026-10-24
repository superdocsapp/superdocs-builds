from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentRunCreate(BaseModel):
    template_id: UUID
    normalized_data: dict[str, Any]
    source_type: str = "text"
    raw_data: dict[str, Any] = {}


class DocumentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    template_id: UUID
    record_id: Optional[UUID] = None
    status: str
    review_data: dict[str, Any]
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    applied_changes: list[dict[str, Any]] = []
    resolved_gaps: dict[str, Any] = {}
    status: str = "completed"
