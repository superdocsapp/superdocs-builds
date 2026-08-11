from pydantic import BaseModel, ConfigDict
from uuid import UUID
from typing import List, Optional
from datetime import datetime

class HealthCheckResponse(BaseModel):
    status: str
    database: str
    environment: str

class Evidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    evidence_id: UUID
    document_id: UUID
    filename: str
    chunk_id: UUID
    content: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    retrieval_score: float
    evidence_type: str  # supporting, contradicting, contextual, insufficient

class Citation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    excerpt: Optional[str] = None

class AnswerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    question: str
    answer: str
    status: str  # answered, insufficient_evidence, conflict, failed
    confidence: float
    citations: List[Citation]
    supporting_evidence: List[Evidence]
    contradicting_evidence: List[Evidence]
    reasoning_summary: str
    created_at: datetime

# NEW PHASE 5 DOSSIER SCHEMAS

class DossierCreate(BaseModel):
    name: str

class DossierQuestionRequest(BaseModel):
    questions: List[str]

class ReviewActionRequest(BaseModel):
    answer: Optional[str] = None
    reasoning_summary: Optional[str] = None
    reason: Optional[str] = None  # Rejection reason

class DossierFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    dossier_id: UUID
    question: str
    status: str
    review_status: str
    answer: Optional[str] = None
    confidence: Optional[float] = None
    reasoning_summary: Optional[str] = None
    citations: Optional[List[Citation]] = None
    supporting_evidence: Optional[List[Evidence]] = None
    contradicting_evidence: Optional[List[Evidence]] = None
    workflow_thread_id: str
    review_reason: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class DossierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    findings: List[DossierFindingResponse]


class StageMetric(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage_name: str
    status: str
    duration_ms: int
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    model_name: Optional[str] = None
    provider_name: Optional[str] = None
    estimated_cost: Optional[float] = None
    error_message: Optional[str] = None
    start_time: datetime
    end_time: datetime


class DossierMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dossier_id: UUID
    total_duration_ms: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    estimated_total_cost: float
    successful_stages: int
    failed_stages: int
    models_used: List[str]
    providers_used: List[str]
    stages: List[StageMetric]
