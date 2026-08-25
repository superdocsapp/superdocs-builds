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


class ExportBlockedError(ValueError):
    """Raised when a pre-export validation summary has one or more FAIL
    checks and the caller did not explicitly opt in to exporting anyway.

    FAIL is reserved for the one non-negotiable check this package
    enforces: an RFE item reaching export without ever being answered
    (see build_validation_summary below). Historically this FAIL was only
    logged, never enforced, which contradicted the "non-negotiable check"
    language throughout this module -- callers could export an
    unanswered item without ever being stopped. This error is how that
    gets enforced: raise it, and require an explicit
    allow_export_with_failures=True (or an explicit human "export
    anyway?" confirmation) before proceeding."""

    def __init__(self, summary: "ValidationSummary"):
        self.summary = summary
        failures = [c.detail or c.label for c in summary.checks if c.status == CheckStatus.FAIL]
        message = (
            "Pre-export validation FAILED -- export blocked: " + "; ".join(failures)
            + ". Pass allow_export_with_failures=True (CLI: --allow-export-with-failures) "
              "to export anyway."
        )
        super().__init__(message)


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
    ungrounded_by_request: dict[str, list[str]] | None = None,  # see item #9 below
    weak_quality_request_ids: list[str] | None = None,  # see item #9 below
) -> ValidationSummary:
    """Builds the final pre-export readout from data this package already
    computed. Never re-derives anything -- purely aggregates and labels
    what's already known, so this can't disagree with the underlying
    per-item checks it's summarizing.

    `ungrounded_by_request` and `weak_quality_request_ids`, if given, are
    the same per-item drafting data both review.py's start_review and
    generate.py's build_response_packet already compute for every
    substantively-drafted item -- `ungrounded_facts` (see grounding.py)
    and a WEAK `quality_verdict` (see judge.py, opt-in via
    QUALITY_GATE_ENABLED). Previously these two heuristic signals were
    only ever logged (logger.warning) or printed in an ad-hoc post-run
    summary, never surfaced in the one-glance pre-export readout a
    reviewer actually looks at -- so a WEAK verdict or an ungrounded fact
    could sit unnoticed while the validation summary showed a clean bill
    of health. Passing them here closes that gap: both become explicit
    WARN rows, same as every other heuristic signal in this summary.
    Omitted (None/empty dict or list) is fine -- both rows just PASS with
    a note that nothing was checked, exactly like the other optional
    inputs above when a caller doesn't have that data."""
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

    # 7. Fact-grounding (heuristic -- see grounding.py).
    ungrounded_by_request = ungrounded_by_request or {}
    flagged_ids = [rid for rid, facts in ungrounded_by_request.items() if facts]
    if ungrounded_by_request:
        if flagged_ids:
            total_facts = sum(len(ungrounded_by_request[rid]) for rid in flagged_ids)
            checks.append(ValidationCheck(
                label="Draft text checked for unsupported facts", status=CheckStatus.WARN,
                detail=f"Item(s) {', '.join(sorted(flagged_ids))}: {total_facts} possibly-unsupported "
                       f"detail(s) -- verify against source material before relying on this draft.",
            ))
        else:
            checks.append(ValidationCheck(label="Draft text checked for unsupported facts", status=CheckStatus.PASS))
    else:
        checks.append(ValidationCheck(
            label="Draft text checked for unsupported facts", status=CheckStatus.PASS,
            detail="No per-item drafting data supplied -- grounding was not checked here.",
        ))

    # 8. LLM-as-judge quality gate (opt-in, QUALITY_GATE_ENABLED -- see
    # judge.py). Absence of `weak_quality_request_ids` covers both "gate
    # never ran" (the common case, since it's off by default) and
    # "nothing came back WEAK" -- neither is a finding worth a WARN, only
    # an actual WEAK verdict is.
    weak_quality_request_ids = weak_quality_request_ids or []
    if weak_quality_request_ids:
        checks.append(ValidationCheck(
            label="Quality gate verdicts", status=CheckStatus.WARN,
            detail=f"Item(s) {', '.join(sorted(weak_quality_request_ids))} graded WEAK (drafted text "
                   f"may not directly address the officer's stated concern) -- review before relying "
                   f"on this draft.",
        ))
    else:
        checks.append(ValidationCheck(
            label="Quality gate verdicts", status=CheckStatus.PASS,
            detail="No item(s) graded WEAK, or the quality gate did not run for this session.",
        ))

    return ValidationSummary(checks=checks)
