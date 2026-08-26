"""Orchestrates one partner contract's amendment case end to end.

Composes the existing deterministic pipeline (`src/pipeline.py`) for
eligibility/citations, `src/rate_diff.py` for the old-vs-new rate
comparison, a notice-sufficiency check against the proposed effective
date, and (only for eligible, sufficiently-noticed cases)
`src/integrations/superdocs_client.py` for the actual document-edit
proposal/approval/export leg.

Non-negotiable invariants carried over from `docs/DOMAIN_MODEL.md`:
  - Pricing-lock and mutual-consent contracts never reach SuperDocs at all
    (state goes straight to `blocked`; no session is ever opened for them).
  - `requires_review` contracts never reach SuperDocs either — a human
    must resolve the ambiguity out of band first.
  - Everything here only *composes* already-produced, cited facts; nothing
    in this module re-derives facts from raw contract text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from src.case_state import CaseState, IllegalStateTransition, transition
from src.domain.models import EligibilityStatus, ProposedRateChange
from src.integrations.superdocs_client import ProposedChange
from src.pipeline import ContractAnalysis, analyze_contract
from src.rate_diff import diff_rate_cards


@dataclass
class Failure:
    what: str
    likely_cause: str
    next_action: str

    def to_dict(self) -> dict[str, str]:
        return {"what": self.what, "likely_cause": self.likely_cause, "next_action": self.next_action}


@dataclass
class AmendmentCase:
    case_id: str
    document_id: str
    analysis: ContractAnalysis
    proposed_changes: list[ProposedRateChange]
    state: CaseState
    blocking_reason: Optional[str] = None
    failure: Optional[Failure] = None
    superdocs_session_id: Optional[str] = None
    superdocs_job_id: Optional[str] = None
    pending_changes: list[ProposedChange] = field(default_factory=list)
    approvals: dict[str, bool] = field(default_factory=dict)
    exported_contract_text: Optional[str] = None
    exported_letter_text: Optional[str] = None

    @property
    def partner_name(self) -> Optional[str]:
        return self.analysis.partner_contract.partner_name

    @property
    def eligibility_status(self) -> EligibilityStatus:
        return self.analysis.eligibility.status

    def set_state(self, target: CaseState) -> None:
        self.state = transition(self.state, target)

    def try_set_state(self, target: CaseState) -> Optional[IllegalStateTransition]:
        try:
            self.set_state(target)
            return None
        except IllegalStateTransition as exc:
            return exc

    def fail(self, failure: Failure) -> None:
        self.failure = failure
        try:
            self.set_state(CaseState.FAILED)
        except IllegalStateTransition:
            # Already terminal (e.g. exported) — record the failure without
            # forcing an illegal transition; the failure is still visible.
            pass


def check_notice_sufficiency(
    notice_period_days: Optional[int],
    reference_date: date,
    proposed_effective_date: date,
) -> Optional[str]:
    """Return a blocking reason if the proposed effective date does not
    satisfy the contract's required notice period, else None.

    A `None` notice_period_days (undefined/qualitative notice, e.g. case
    05's "commercially reasonable period") is NOT evaluated here — that
    contract is already forced to `requires_review` upstream by
    `rules/eligibility.py`, so this function is only ever reached with a
    concrete day count.
    """

    if notice_period_days is None:
        return None

    days_until_effective = (proposed_effective_date - reference_date).days
    if days_until_effective < notice_period_days:
        return (
            f"proposed effective date is only {days_until_effective} day(s) from the "
            f"reference date, but the contract requires at least {notice_period_days} "
            f"day(s) notice"
        )
    return None


def build_case(
    case_id: str,
    contract_path: str,
    old_rate_entries: list,
    new_rate_entries: list,
    reference_date: date,
    proposed_effective_date: date,
) -> AmendmentCase:
    """Run the deterministic pipeline + rate diff and set the case's
    initial state, without ever calling SuperDocs."""

    analysis = analyze_contract(contract_path, reference_date)
    proposed_changes = diff_rate_cards(analysis.document_id, old_rate_entries, new_rate_entries)

    case = AmendmentCase(
        case_id=case_id,
        document_id=analysis.document_id,
        analysis=analysis,
        proposed_changes=proposed_changes,
        state=CaseState.PENDING,
    )
    case.set_state(CaseState.ANALYSING)

    eligibility = analysis.eligibility
    if eligibility.status == EligibilityStatus.REQUIRES_REVIEW:
        case.blocking_reason = eligibility.exclusion_reason or "requires human escalation"
        case.set_state(CaseState.REQUIRES_REVIEW)
        return case

    if eligibility.status in (
        EligibilityStatus.NOT_ELIGIBLE,
        EligibilityStatus.NOT_ELIGIBLE_UNILATERALLY,
    ):
        case.blocking_reason = eligibility.exclusion_reason or f"eligibility status is '{eligibility.status.value}'"
        case.set_state(CaseState.BLOCKED)
        return case

    if analysis.pricing_clause is None:
        case.blocking_reason = "no pricing/amendment clause located in the attached contract"
        case.set_state(CaseState.REQUIRES_REVIEW)
        return case

    notice_days = analysis.notice.notice_period_days
    insufficient_notice_reason = check_notice_sufficiency(
        notice_days, reference_date, proposed_effective_date
    )
    if insufficient_notice_reason is not None:
        case.blocking_reason = insufficient_notice_reason
        case.set_state(CaseState.BLOCKED)
        return case

    # Eligible, clause located, notice sufficient: ready for a scoped
    # SuperDocs proposal. State stays ANALYSING until propose_case() below
    # actually calls SuperDocs (or, in dry-run mode, until the caller
    # inspects the prepared instruction without ever transitioning further).
    return case


def build_instruction(case: AmendmentCase) -> str:
    """Build the tightly-scoped chat_async instruction for an eligible case.

    Names the exact governing clause and lists only the changed
    destinations verbatim, per the pattern verified live against the real
    SuperDocs API: SuperDocs will not fabricate a rate table it cannot see
    in the document text, so the literal new rates must be supplied here.
    """

    clause_reference = (
        case.analysis.pricing_clause.clause_reference if case.analysis.pricing_clause else "the rate/pricing clause"
    )
    changed = [c for c in case.proposed_changes if c.new_rate_usd_per_min is not None]
    rate_lines = "\n".join(
        f"- {c.destination}: "
        f"{c.old_rate_usd_per_min if c.old_rate_usd_per_min is not None else 'no prior rate on file'} "
        f"-> {c.new_rate_usd_per_min} USD/min"
        for c in changed
    )

    return (
        f"In this contract, under the section governed by '{clause_reference}', update ONLY the rate "
        f"table so that the following destinations have these new per-minute rates:\n"
        f"{rate_lines}\n"
        f"Do not add, remove, or reword any other clause, heading, or non-rate content. "
        f"If no rate table is present in the document text, add one new section titled "
        f"'Schedule A — Rate Card (Amended)' immediately after the pricing clause containing "
        f"only this table, and make no other changes."
    )


def apply_job_status(case: AmendmentCase, job_status) -> None:
    """Record a polled SuperDocs job's pending changes onto the case and
    advance state to PROPOSED once the job reaches awaiting_approval."""

    case.superdocs_job_id = job_status.job_id
    if job_status.status == "awaiting_approval":
        case.pending_changes = job_status.pending_changes
        case.set_state(CaseState.PROPOSED)
    elif job_status.status == "failed":
        case.fail(
            Failure(
                what=f"SuperDocs job {job_status.job_id} failed",
                likely_cause="the SuperDocs AI could not complete the requested edit",
                next_action="review the instruction scope and retry propose_case, or escalate to manual review",
            )
        )
    elif job_status.status == "completed" and not job_status.pending_changes:
        # No changes were needed/proposed (e.g. rates already match) —
        # treat as approved with nothing pending.
        case.set_state(CaseState.APPROVED)


def record_decision(case: AmendmentCase, change_id: str, approved: bool) -> None:
    """Record one approve/reject decision and recompute the case's state."""

    known_ids = {c.change_id for c in case.pending_changes}
    if change_id not in known_ids:
        raise ValueError(
            f"change_id '{change_id}' is not a pending change on case '{case.case_id}' "
            f"(known: {sorted(known_ids)})"
        )
    case.approvals[change_id] = approved
    recompute_approval_state(case)


def recompute_approval_state(case: AmendmentCase) -> None:
    decided = [case.approvals.get(c.change_id) for c in case.pending_changes]

    if any(d is None for d in decided):
        case.try_set_state(CaseState.PARTIALLY_APPROVED)
        return

    if all(d is False for d in decided):
        # Every proposed change was rejected: nothing left to export.
        case.blocking_reason = "all proposed rate changes were rejected during review"
        case.try_set_state(CaseState.BLOCKED)
        return

    if all(d is True for d in decided):
        case.try_set_state(CaseState.APPROVED)
        return

    # Mixed approve/reject: partially approved, exportable only for the
    # approved subset (the export route enforces this explicitly).
    case.try_set_state(CaseState.PARTIALLY_APPROVED)


def unresolved_change_ids(case: AmendmentCase) -> list[str]:
    return [c.change_id for c in case.pending_changes if case.approvals.get(c.change_id) is None]


def rejected_change_ids(case: AmendmentCase) -> list[str]:
    return [c.change_id for c in case.pending_changes if case.approvals.get(c.change_id) is False]


def touched_chunk_ids(case: AmendmentCase) -> set[str]:
    """Chunk ids that SuperDocs actually proposed touching — used to prove
    non-rate content was not targeted (any chunk id NOT in this set was
    never included in a proposed change)."""

    return {c.chunk_id for c in case.pending_changes}
