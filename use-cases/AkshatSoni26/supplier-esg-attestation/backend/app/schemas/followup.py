from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.schemas.enums import LetterStatus


class FollowUpLetterCreate(BaseModel):
    attestation_id: str
    custom_remediation_deadline_days: int = 30
    additional_notes: str | None = None


class FollowUpLetterResponse(BaseModel):
    id: str
    attestation_id: str
    recipient_email: str
    subject: str
    content_markdown: str
    superdocs_doc_id: str | None = None
    superdocs_export_url: str | None = None
    status: LetterStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FollowUpLetterStatusUpdate(BaseModel):
    status: LetterStatus
