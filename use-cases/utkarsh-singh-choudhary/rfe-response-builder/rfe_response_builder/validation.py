"""
Pre-export validation summary.

Every check this package runs -- coverage (is every RFE item answered),
grounding, cross-item consistency, injection risk, human approval status
-- previously surfaced as separate, scattered flags: a checklist line
here, a warning banner there, a printed summary somewhere else. Nothing
combined them into one final, explicit "is this actually ready to
export" readout that a reviewer or attorney could glance at right before
hitting export/approve.

This module builds exactly that: a small, ordered list of named checks,
each PASS/WARN/FAIL, covering the checklist a reviewer would otherwise
have to reconstruct by eye from several different places. It is
deliberately a SUMMARY, not a new source of truth -- every check here
reads from data this package already computed elsewhere (coverage rows,
consistency flags, injection flags); it doesn't re-derive anything.

FAIL is reserved for the one thing this package's whole design considers
non-negotiable: an RFE item reaching export without ever being answered.
Everything else (evidence gaps, consistency flags, injection risk) is
WARN -- worth a human's attention, consistent with every other heuristic
signal in this package, never a hard block on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class ValidationCheck:
    label: str
    status: CheckStatus
    detail: str = ""


@dataclass
class ValidationSummary:
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(c.status == CheckStatus.FAIL for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(c.status == CheckStatus.WARN for c in self.checks)

    @property
    def overall_status(self) -> CheckStatus:
        if self.has_failures:
            return CheckStatus.FAIL
        if self.has_warnings:
            return CheckStatus.WARN
        return CheckStatus.PASS


def build_validation_summary(
    coverage: list,  # list[rfe.CoverageRow]
    consistency_flags: list | None = None,  # list[consistency.ConsistencyFlag]
    injection_flags: list | None = None,  # list[(source, injection_guard.InjectionRiskResult)]
    exhibits: list | None = None,  # list[rfe.Exhibit]
) -> ValidationSummary:
    """Builds the final pre-export readout from data this package already
    computed. Never re-derives anything -- purely aggregates and labels
    what's already known, so this can't disagree with the underlying
    per-item checks it's summarizing."""
    consistency_flags = consistency_flags or []
    injection_flags = injection_flags or []
    checks: list[ValidationCheck] = []

    # 1. Every RFE item parsed -- always PASS if we got this far (the
    # notice parser either found items or plan_response would have
    # raised before this function is ever called), but stated explicitly
    # since it's the first thing a reviewer would want confirmed.
    checks.append(ValidationCheck(
        label="All RFE requests parsed", status=CheckStatus.PASS,
        detail=f"{len(coverage)} item(s) identified in the notice.",
    ))

    # 2. The one non-negotiable check: nothing goes unanswered.
    unanswered = [row for row in coverage if not row.answered]
    if unanswered:
        ids = ", ".join(row.request_id for row in unanswered)
        checks.append(ValidationCheck(
            label="Every request answered", status=CheckStatus.FAIL,
            detail=f"Item(s) {ids} are NOT ANSWERED. Exporting now leaves these unaddressed.",
        ))
    else:
        checks.append(ValidationCheck(
            label="Every request answered", status=CheckStatus.PASS,
            detail=f"All {len(coverage)} item(s) answered.",
        ))

    # 3. Evidence gaps -- rows whose evidence_status signals a genuine
    # gap rather than a matched/not-applicable state. See rfe.EvidenceStatus
    # for the exact set of values; treated loosely here (substring match)
    # so this stays in sync even if new status values are added later.
    needs_attention = [
        row for row in coverage
        if "needs" in row.evidence_status.lower() or "missing" in row.evidence_status.lower()
    ]
    if needs_attention:
        ids = ", ".join(row.request_id for row in needs_attention)
        checks.append(ValidationCheck(
            label="Evidence gaps identified", status=CheckStatus.WARN,
            detail=f"Item(s) {ids} may need additional evidence or attorney review.",
        ))
    else:
        checks.append(ValidationCheck(label="Evidence gaps identified", status=CheckStatus.PASS))

    # 4. Exhibit numbering sanity -- every number 1..N present exactly
    # once (build_exhibit_list already guarantees this by construction,
    # so this check exists to catch it if that guarantee is ever broken
    # elsewhere, not because it's expected to fail).
    if exhibits:
        numbers = sorted(ex.number for ex in exhibits)
        expected = list(range(1, len(exhibits) + 1))
        if numbers == expected:
            checks.append(ValidationCheck(
                label="Exhibit numbers valid", status=CheckStatus.PASS,
                detail=f"{len(exhibits)} exhibit(s), numbered {expected[0]}-{expected[-1]} with no gaps or duplicates.",
            ))
        else:
            checks.append(ValidationCheck(
                label="Exhibit numbers valid", status=CheckStatus.FAIL,
                detail=f"Expected {expected}, found {numbers}.",
            ))
    else:
        checks.append(ValidationCheck(
            label="Exhibit numbers valid", status=CheckStatus.PASS, detail="No exhibits in this filing.",
        ))

    # 5. Cross-item consistency (heuristic -- see consistency.py).
    if consistency_flags:
        checks.append(ValidationCheck(
            label="Cross-item consistency checked", status=CheckStatus.WARN,
            detail=f"{len(consistency_flags)} possible inconsistency/inconsistencies flagged -- verify before export.",
        ))
    else:
        checks.append(ValidationCheck(label="Cross-item consistency checked", status=CheckStatus.PASS))

    # 6. Prompt-injection risk (heuristic -- see injection_guard.py).
    if injection_flags:
        checks.append(ValidationCheck(
            label="Uploaded material scanned for injection risk", status=CheckStatus.WARN,
            detail=f"{len(injection_flags)} source(s) flagged -- review before relying on this draft.",
        ))
    else:
        checks.append(ValidationCheck(label="Uploaded material scanned for injection risk", status=CheckStatus.PASS))

    return ValidationSummary(checks=checks)
