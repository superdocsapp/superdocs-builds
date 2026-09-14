"""Data model for one renewal cycle. Deliberately small - this is a single-cohort renewal tool, not a
general contract database (that's Task 1's job, and this project stays separate from it by design)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Customer:
    customer_id: str
    name: str


@dataclass
class ContractTerms:
    """Every field carries the exact quote it was read from - the whole point of this build (per the task
    card's own 'what strong looks like' bar) is that the governing clause is real, not assumed."""

    entitlement_units: float
    entitlement_quote: str
    monthly_fee: float
    fee_quote: str
    overage_rate: float
    overage_rate_quote: str


@dataclass
class UsagePeriod:
    customer_id: str
    period_label: str  # e.g. "2026-07"
    units_used: float


@dataclass
class TrueUpResult:
    customer_id: str
    entitlement_units: float
    units_used: float
    overage_units: float
    overage_rate: float
    true_up_amount: float
    governing_clause_quote: str


@dataclass
class RenewalException:
    customer_id: str
    reason: str  # "overage_true_up_required" | "clause_not_found" | ...


@dataclass
class RenewalPackage:
    customer: Customer
    terms: ContractTerms | None
    usage: UsagePeriod
    true_up: TrueUpResult | None
    exception: RenewalException | None
    session_id: str | None = None
    amendment_session_id: str | None = None
    exported_summary_markdown: str | None = None
    decisions: list[dict] = field(default_factory=list)
    renewal_quote: str | None = None
    talk_track: str | None = None
    usage_chart_url: str | None = None
    usage_report_uploaded: bool = False


def is_clean(package: RenewalPackage) -> bool:
    """A renewal is clean (moves through without a human) only if it has no exception at all - per the
    task card: 'the cohort batch surfaces real exceptions instead of dumping everything into review',
    which only means something if 'clean' is a real, checkable state, not just 'nobody flagged it yet'."""
    return package.exception is None
