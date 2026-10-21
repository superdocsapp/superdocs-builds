"""Pydantic request/response models for the FastAPI backend."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class FailureOut(BaseModel):
    what: str
    likely_cause: str
    next_action: str


class CaseSummaryOut(BaseModel):
    """One row of the Analysis dashboard."""

    case_id: str
    partner_name: Optional[str]
    contract_identifier: Optional[str]
    state: str
    eligibility_status: str
    blocking_reason: Optional[str]
    amendment_mechanism: Optional[str]
    pricing_lock_active: Optional[bool]
    mutual_consent_required: Optional[bool]
    requires_human_escalation: bool
    prompt_injection_present: bool
    notice_period_days: Optional[int]
    notice_period_type: Optional[str]
    pricing_clause_reference: Optional[str]
    pricing_clause_citation: Optional[str]
    confidence: float
    proposed_rate_changes: list["RateChangeOut"]
    failure: Optional[FailureOut] = None


class RateChangeOut(BaseModel):
    destination: Optional[str]
    old_rate_usd_per_min: Optional[float]
    new_rate_usd_per_min: Optional[float]
    change_pct: Optional[float]
    source_citation: str


class RunSummaryOut(BaseModel):
    run_id: str
    dry_run: bool
    proposed_effective_date: str
    cases: list[CaseSummaryOut]


class PendingChangeOut(BaseModel):
    change_id: str
    chunk_id: str
    old_html: Optional[str]
    new_html: Optional[str]
    ai_explanation: Optional[str]
    decision: Optional[bool] = None


class ReviewOut(BaseModel):
    case_id: str
    state: str
    pending_changes: list[PendingChangeOut]
    untouched_proof_note: str
    amendment_letter_markdown: Optional[str]
    instruction_sent: Optional[str]


class DecisionIn(BaseModel):
    change_id: str
    approved: bool
    feedback: Optional[str] = None


class DecisionsIn(BaseModel):
    decisions: list[DecisionIn]
    idempotency_key: str


class ExportRequestIn(BaseModel):
    idempotency_key: str
    format: str = "markdown"


class ExportOut(BaseModel):
    case_id: str
    state: str
    exported_contract_text: Optional[str]
    exported_letter_text: Optional[str]


class ControlReportRowOut(BaseModel):
    case_id: str
    partner_name: Optional[str]
    contract_identifier: Optional[str]
    state: str
    eligibility_status: str
    amendment_mechanism: Optional[str]
    pricing_lock_active: Optional[bool]
    mutual_consent_required: Optional[bool]
    requires_human_escalation: bool
    prompt_injection_present: bool
    exported: bool


class ControlReportOut(BaseModel):
    run_id: str
    rows: list[ControlReportRowOut]
    excluded_or_escalated: list[ControlReportRowOut]
