"""Transport/domain schemas.

These Pydantic models are the contract between layers. Engines emit them,
repositories persist them, the API serialises them — so an engine can be unit
tested with zero database.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(StrEnum):
    INVOICE = "invoice"
    CONTRACT = "contract"
    PURCHASE_ORDER = "purchase_order"
    POLICY = "policy"
    MEETING_NOTES = "meeting_notes"
    STATUS_REPORT = "status_report"
    FINANCIAL_STATEMENT = "financial_statement"
    LEGAL_DOCUMENT = "legal_document"
    COMPLIANCE_DOCUMENT = "compliance_document"
    UNKNOWN = "unknown"


class FactType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    ADDRESS = "address"
    DATE = "date"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    FINANCIAL_METRIC = "financial_metric"
    TABLE = "table"
    HEADING = "heading"
    OBLIGATION = "obligation"
    DELIVERABLE = "deliverable"
    DEADLINE = "deadline"
    INVOICE_NUMBER = "invoice_number"
    GST_NUMBER = "gst_number"
    TAX = "tax"
    REVENUE = "revenue"
    PROFIT = "profit"
    EXPENSE = "expense"
    NET_INCOME = "net_income"
    NUMBER = "number"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCategory(StrEnum):
    CONFLICT = "conflict"
    RULE = "rule"
    NUMERIC = "numeric"
    DATE = "date"


class FindingStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


NO_EVIDENCE = "Evidence Not Found"


class Citation(BaseModel):
    """Provenance for exactly one claim. `quote` is verbatim source text."""

    model_config = ConfigDict(frozen=True)

    document_id: UUID | None = None
    page: int | None = None
    section: str | None = None
    paragraph: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str = ""

    @property
    def locator(self) -> str:
        parts = []
        if self.page is not None:
            parts.append(f"p.{self.page}")
        if self.section:
            parts.append(self.section)
        if self.paragraph is not None:
            parts.append(f"¶{self.paragraph}")
        return " · ".join(parts) or "document"


class TextBlock(BaseModel):
    """Smallest addressable unit of a parsed document."""

    text: str
    page: int = 1
    paragraph: int = 0
    section: str | None = None
    char_start: int = 0
    char_end: int = 0
    kind: str = "paragraph"  # paragraph | heading | table_cell | ocr

    def citation(self, document_id: UUID | None = None, quote: str | None = None) -> Citation:
        return Citation(
            document_id=document_id,
            page=self.page,
            section=self.section,
            paragraph=self.paragraph,
            char_start=self.char_start,
            char_end=self.char_end,
            quote=(quote or self.text)[:500],
        )


class Table(BaseModel):
    page: int = 1
    section: str | None = None
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    caption: str | None = None


class ParsedDocument(BaseModel):
    text: str = ""
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    page_count: int = 0
    parser: str = "text"
    ocr_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID | None = None
    fact_type: FactType
    label: str = ""
    raw_value: str = ""
    normalized_value: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = None
    confidence: float = 0.5
    extractor: str = "deterministic"
    page: int | None = None
    section: str | None = None
    paragraph: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    citation: Citation | None = None
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    embedding: list[float] | None = None
    created_at: datetime | None = None

    @property
    def dedupe_key(self) -> str:
        """Stable identity so re-running a document is idempotent."""
        basis = f"{self.fact_type}|{self.label.lower().strip()}|{self.raw_value.lower().strip()}|{self.page}|{self.char_start}"
        return hashlib.sha1(basis.encode()).hexdigest()

    @property
    def numeric_value(self) -> float | None:
        value = self.normalized_value.get("amount", self.normalized_value.get("value"))
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def date_value(self) -> date | None:
        raw = self.normalized_value.get("iso_date")
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            return None


class Finding(BaseModel):
    """One reviewable issue. Never auto-applied — always human-gated."""

    id: UUID = Field(default_factory=uuid4)
    document_id: UUID | None = None
    category: FindingCategory
    finding_type: str
    severity: Severity = Severity.MEDIUM
    confidence: float = 0.5
    title: str
    explanation: str = ""
    expected_value: str | None = None
    actual_value: str | None = None
    difference: str | None = None
    suggested_correction: str | None = None
    evidence: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    related_fact_ids: list[UUID] = Field(default_factory=list)
    rule_id: UUID | None = None
    status: FindingStatus = FindingStatus.PENDING

    @property
    def fingerprint(self) -> str:
        basis = f"{self.category}|{self.finding_type}|{self.title}|{self.expected_value}|{self.actual_value}"
        return hashlib.sha1(basis.encode()).hexdigest()


class RuleResult(BaseModel):
    rule_id: UUID | None = None
    rule_name: str
    passed: bool | None  # None = indeterminate (no evidence)
    confidence: float = 0.0
    explanation: str = ""
    evidence: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    @property
    def outcome(self) -> str:
        if self.passed is None:
            return "indeterminate"
        return "pass" if self.passed else "fail"
