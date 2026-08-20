"""Shared data models for the Box metadata write-back workflow."""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DocClass(str, Enum):
    CONTRACT = "contract"
    INVOICE = "invoice"
    AMENDMENT = "amendment"
    POLICY = "policy"
    CORRESPONDENCE = "correspondence"
    UNKNOWN = "unknown"


class ExtractedFields(BaseModel):
    """Structured fields the pipeline writes into the Box metadata template.

    Every field is Optional[...] on purpose: the brief requires that a field
    be left empty rather than guessed when the source document does not say.
    A populated field always carries a `source_confidence` companion so a
    reviewer knows how much to trust it; a None field means "the document
    did not support a value," which is a different, and honest, answer than
    a wrong guess.
    """

    doc_class: DocClass = DocClass.UNKNOWN
    doc_class_confidence: float = 0.0

    counterparty_name: Optional[str] = None
    effective_date: Optional[str] = None  # ISO 8601 date string
    expiration_date: Optional[str] = None
    contract_value: Optional[str] = None  # kept as string; currency varies
    key_terms_summary: Optional[str] = None
    retention_category: Optional[str] = None

    companion_document_id: Optional[str] = None  # Box file ID of generated companion doc
    normalized: bool = False

    extraction_notes: str = ""  # honest notes on what could not be determined

    # Per-field confidence for everything extract_node populated, e.g.
    # {"counterparty_name": 0.92, "contract_value": 0.55}. Kept separate
    # from the field values themselves so a low-confidence value can be
    # held back from metadata (see ReviewQueue) without losing the value
    # entirely -- it's queued for a human, not discarded.
    field_confidence: dict[str, float] = Field(default_factory=dict)

    # Fields extracted with confidence below the review threshold are
    # removed from the fields above and staged here instead, keyed the
    # same way, so the metadata write only ever contains fields a human
    # has effectively vouched for (either by being above-threshold, which
    # is a standing policy decision, or by explicit approval).
    pending_review_ids: list[str] = Field(default_factory=list)


class PendingReview(BaseModel):
    """A single low-confidence field, held out of Box metadata until a
    human approves or rejects it. This is the same 'human gates it' idea
    the brief applies to Task 1's conflicts/findings, applied here to
    low-confidence extraction instead."""

    review_id: str
    file_id: str
    version_sha1: str
    field_name: str
    proposed_value: str
    confidence: float
    status: str = "pending"  # pending | approved | rejected
    created_at: float = 0.0
    decided_at: Optional[float] = None


class MetadataChange(BaseModel):
    """One entry in a file's metadata audit trail: what changed, when,
    and because of which source document version. Only written when the
    new value actually differs from the old one -- reprocessing a file
    where nothing changed produces zero new history entries, which is
    what lets 'byte-identical where you promise untouched' be provable
    rather than asserted."""

    file_id: str
    field_name: str
    old_value: Optional[str]
    new_value: Optional[str]
    version_sha1: str
    timestamp: float
    reason: str  # e.g. "initial extraction", "reprocessed: new version", "review approved"


class StageCost(BaseModel):
    """Cost/latency for a single pipeline stage, rolled up per run."""

    stage: str
    latency_ms: float
    operations: int  # SuperDocs operations spent (each chat call = 1)


class BoxFileVersion(BaseModel):
    file_id: str
    version_id: str
    name: str
    sha1: str


class GovernanceState(BaseModel):
    """What we are NEVER allowed to touch."""
    legal_hold: bool = False
    retention_policy_locked: bool = False
    classification_label: Optional[str] = None
