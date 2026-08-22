from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.schemas.enums import SupplierTier, Region, AttestationStatus


class QuestionnaireIssuanceRequest(BaseModel):
    supplier_id: str
    cycle_year: int = 2026
    custom_instructions: str | None = None


class QuestionnaireIssuanceResponse(BaseModel):
    attestation_id: str
    supplier_id: str
    supplier_name: str
    tier: SupplierTier
    region: Region
    cycle_year: int
    status: AttestationStatus
    document_title: str
    document_content_markdown: str
    included_annexes: list[str]
    superdocs_document_id: str | None = None
    export_url: str | None = None
    issued_at: datetime


class AttestationCycleResponse(BaseModel):
    id: str
    supplier_id: str
    cycle_year: int
    status: AttestationStatus
    issued_document_id: str | None = None
    issued_document_url: str | None = None
    response_document_id: str | None = None
    response_document_name: str | None = None
    response_format: str | None = None
    submitted_at: datetime | None = None
    normalized_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
