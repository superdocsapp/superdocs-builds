from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime, timezone
from uuid import UUID, uuid4


class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    corpus_ref: Optional[str] = None
    feed_ref: Optional[str] = None
    trigger: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunStep(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    node: str
    input_hash: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    output_ref: Optional[dict] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class Document(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    superdocs_doc_id: Optional[str] = None
    session_id: str
    filename: str
    file_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Chunk(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    chunk_id: str
    html: str
    content_hash: str
    embedding: Optional[list[float]] = None


ChangeFactType = Literal["renamed", "deprecated", "removed", "default_changed", "added"]


class ChangeFact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    type: ChangeFactType
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    evidence_span: Optional[str] = None
    source_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


FindingState = Literal["CONFIRMED_DRIFT", "NO_DRIFT", "UNKNOWN"]


class Finding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    change_fact_id: Optional[UUID] = None
    chunk_id: Optional[str] = None
    document_id: Optional[UUID] = None
    state: FindingState
    evidence_quote: Optional[str] = None
    evidence_chunk_id: Optional[str] = None
    proposed_old: Optional[str] = None
    proposed_new: Optional[str] = None
    verifier_verdict: Optional[str] = None
    judge_verdict: Optional[str] = None
    ai_explanation: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewDecision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    decision: Literal["approved", "rejected"]
    feedback: Optional[str] = None
    decided_at: datetime = Field(default_factory=datetime.utcnow)


class AppliedEdit(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    superdocs_job_id: str
    superdocs_change_id: Optional[str] = None
    applied_at: datetime = Field(default_factory=datetime.utcnow)


class QueueEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    kind: Literal["unknown", "failed"]
    reason: Optional[str] = None
    retries: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TraceRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    node: str
    input_hash: str
    decision: Optional[str] = None
    evidence: Optional[dict] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    superdocs_ops: int = 0
    ms: int = 0
    ts: datetime = Field(default_factory=datetime.utcnow)


class Job(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    kind: str
    status: Literal["pending", "claimed", "completed", "failed"] = "pending"
    agent: str
    payload: Optional[dict] = None
    result: Optional[dict] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ParsedDocument(BaseModel):
    document_id: UUID
    session_id: str
    superdocs_doc_id: str
    filename: str
    file_hash: str
    chunks: list[dict]
    html: str


class IngestionJob(BaseModel):
    run_id: UUID
    document_ids: list[UUID]


class ReviewBatch(BaseModel):
    run_id: UUID
    finding_ids: list[UUID]


class EditBatch(BaseModel):
    run_id: UUID
    approved_finding_ids: list[UUID]