"""Typed domain models for the telecom contract-analysis core.

Every extracted fact is carried inside a `SourceCitation`, which is the
uniform envelope requiring: document ID, page/section (where available),
quoted/normalized source span, confidence, and extraction method. Facts that
cannot be supported by document text stay `None` rather than being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExtractionMethod(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    MODEL_REASONING = "model_reasoning"
    FIXTURE_RECORDED = "fixture_recorded"


class DocumentType(str, Enum):
    CONTRACT = "contract"
    RATE_CARD = "rate_card"
    AMENDMENT_LETTER_TEMPLATE = "amendment_letter_template"
    PLAYBOOK = "playbook"
    UNKNOWN = "unknown"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NOT_ELIGIBLE_UNILATERALLY = "not_eligible_unilaterally"
    REQUIRES_REVIEW = "requires_review"


@dataclass(frozen=True)
class DocumentReference:
    """Identifies a source document within the corpus."""

    document_id: str
    file_path: str
    document_type: DocumentType


@dataclass(frozen=True)
class SourceCitation:
    """Uniform provenance envelope required on every extracted fact."""

    document_id: str
    source_span: str
    confidence: float
    extraction_method: ExtractionMethod
    section: Optional[str] = None
    page: Optional[int] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


@dataclass(frozen=True)
class PartnerContract:
    """Partner and contract metadata for one agreement."""

    document_id: str
    partner_name: Optional[str]
    our_entity: Optional[str]
    contract_date: Optional[str]
    contract_identifier: Optional[str]
    governing_law: Optional[str]
    citation: SourceCitation


@dataclass(frozen=True)
class RateEntry:
    """A single per-destination rate row from a rate table/card."""

    rate_card_id: Optional[str]
    destination: Optional[str]
    prefix: Optional[str]
    rate_usd_per_min: Optional[float]
    effective_date: Optional[str]
    expiry_date: Optional[str]
    citation: SourceCitation


@dataclass(frozen=True)
class PricingClause:
    """The clause(s) governing rate amendments for a contract."""

    document_id: str
    clause_reference: Optional[str]
    current_rates_reference: Optional[str]
    citation: SourceCitation
    supporting_clauses: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NoticeRequirement:
    """Notice-period and delivery-method requirements for an amendment."""

    document_id: str
    notice_period_days: Optional[int]
    notice_period_type: Optional[str]
    delivery_method: Optional[str]
    objection_window: Optional[str]
    citation: SourceCitation


@dataclass(frozen=True)
class Conflict:
    """An unresolved internal conflict or dependency on unattached material."""

    document_id: str
    description: str
    citation: SourceCitation


@dataclass(frozen=True)
class EligibilityDecision:
    """Final amendment-eligibility determination for a contract."""

    document_id: str
    status: EligibilityStatus
    amendment_mechanism: Optional[str]
    exclusion_reason: Optional[str]
    pricing_lock_active: Optional[bool]
    mutual_consent_required: Optional[bool]
    requires_human_escalation: bool
    citations: tuple[SourceCitation, ...]
    prompt_injection_present: bool = False
    prompt_injection_note: Optional[str] = None


@dataclass(frozen=True)
class ProposedRateChange:
    """A candidate rate change between an old and new rate card entry."""

    document_id: str
    destination: Optional[str]
    old_rate_usd_per_min: Optional[float]
    new_rate_usd_per_min: Optional[float]
    change_pct: Optional[float]
    citation: SourceCitation


@dataclass(frozen=True)
class AmendmentLetterData:
    """Data prepared to populate the amendment-letter template.

    Populated only when `eligibility.status == EligibilityStatus.ELIGIBLE`.
    Pricing-lock, mutual-consent, and requires-review cases must never reach
    letter generation with populated proposed-effective-date/rate fields.
    """

    document_id: str
    partner_legal_name: Optional[str]
    our_legal_name: Optional[str]
    contract_identifier: Optional[str]
    contract_date: Optional[str]
    amendment_clause_reference: Optional[str]
    rate_schedule_reference: Optional[str]
    required_notice_period_days: Optional[int]
    notice_delivery_method: Optional[str]
    blocked: bool
    blocked_reason: Optional[str]
    citation: SourceCitation


@dataclass(frozen=True)
class ControlReportRow:
    """One row of the aggregate control report across the corpus."""

    document_id: str
    partner_name: Optional[str]
    contract_identifier: Optional[str]
    eligibility_status: EligibilityStatus
    amendment_mechanism: Optional[str]
    pricing_lock_active: Optional[bool]
    mutual_consent_required: Optional[bool]
    requires_human_escalation: bool
    prompt_injection_present: bool
    open_conflicts: int
