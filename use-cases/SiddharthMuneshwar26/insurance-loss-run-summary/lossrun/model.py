"""Domain model.

One rule governs this file and the two that follow it: **figures are parsed,
never inferred.** Claim counts, incurred totals and loss ratios in the review
document are arithmetic over rows read out of the loss runs. No model is asked
what a number is, because an underwriter cannot act on a total that might be a
plausible guess.

What the model *is* asked is the thing arithmetic cannot do: read the adjuster
notes, the application and the broker correspondence, and surface where the
prose disagrees with the figures. That division is the whole architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

OPEN_STATUSES = {"open", "reopened"}


@dataclass(frozen=True)
class Source:
    """Where a fact came from. Every figure in the deliverable carries one."""

    document: str
    valuation_date: str | None = None
    row: int | None = None
    is_reissue: bool = False

    def cite(self) -> str:
        bits = [self.document]
        if self.valuation_date:
            bits.append(f"valued {self.valuation_date}")
        if self.row is not None:
            bits.append(f"row {self.row}")
        return ", ".join(bits)


@dataclass
class Claim:
    claim_no: str
    policy_year: int
    policy_no: str
    coverage: str
    date_of_loss: str
    date_reported: str
    status: str
    claimant: str
    paid: float
    reserve: float
    incurred: float
    description: str
    source: Source

    @property
    def is_open(self) -> bool:
        return self.status.strip().lower() in OPEN_STATUSES

    def months_open(self, as_of: date) -> int:
        try:
            dol = date.fromisoformat(self.date_of_loss)
        except ValueError:
            return 0
        return (as_of.year - dol.year) * 12 + as_of.month - dol.month

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.cite()
        return d


@dataclass
class LossRun:
    """One loss run document, as read."""

    path: str
    policy_year: int
    policy_no: str
    period_start: str
    period_end: str
    valuation_date: str
    is_reissue: bool
    claims: list[Claim] = field(default_factory=list)
    stated_total: float | None = None
    stated_count: int | None = None
    earned_premium: float | None = None

    @property
    def summed_total(self) -> float:
        return round(sum(c.incurred for c in self.claims), 2)

    @property
    def label(self) -> str:
        kind = "reissue" if self.is_reissue else "original"
        return f"PY{self.policy_year} {kind} valued {self.valuation_date}"


@dataclass
class Conflict:
    """Two sources say different things. Surfaced, never resolved silently."""

    kind: str
    subject: str
    left: str
    right: str
    detail: str
    consequence: str = ""
    resolution: str | None = None      # set only by a human decision

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    """A rule fired."""

    rule: str
    title: str
    subject: str
    detail: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class YearSummary:
    policy_year: int
    policy_no: str
    claim_count: int
    open_count: int
    total_paid: float
    total_reserve: float
    total_incurred: float
    open_incurred: float
    earned_premium: float | None
    source: str
    superseded_by: str | None = None

    @property
    def loss_ratio(self) -> float | None:
        if not self.earned_premium:
            return None
        return round(self.total_incurred / self.earned_premium, 4)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["loss_ratio"] = self.loss_ratio
        return d


@dataclass
class Summary:
    insured: str
    years: list[YearSummary] = field(default_factory=list)
    open_claims: list[Claim] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    documents_read: list[str] = field(default_factory=list)
    documents_superseded: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    """Figures the app could not independently check. Named, never smoothed."""

    @property
    def total_incurred(self) -> float:
        return round(sum(y.total_incurred for y in self.years), 2)

    @property
    def total_claims(self) -> int:
        return sum(y.claim_count for y in self.years)

    @property
    def total_open(self) -> int:
        return sum(y.open_count for y in self.years)

    def to_dict(self) -> dict[str, Any]:
        return {
            "insured": self.insured,
            "totals": {
                "claims": self.total_claims,
                "open": self.total_open,
                "incurred": self.total_incurred,
            },
            "years": [y.to_dict() for y in self.years],
            "open_claims": [c.to_dict() for c in self.open_claims],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "findings": [f.to_dict() for f in self.findings],
            "documents_read": self.documents_read,
            "documents_superseded": self.documents_superseded,
            "unverified": self.unverified,
        }
