"""Shared schema for Task 2.2's close-package assembler.

Compounds directly on Task 2's engine (drafter/), per TASK.md's own
"marginal cost is new business logic on infrastructure that already
exists" framing: a close package is drafter's already-verified
DrafterState, PLUS a revenue recognition schedule (the one genuinely new
piece of domain logic -- see schedule.py), PLUS an audit trail (zero new
LLM calls -- audit_trail.py derives it entirely from data schedule.py and
drafter/analysis.py already verified).
"""

from __future__ import annotations

from typing import Any, TypedDict

from drafter.state import DrafterState


class ScheduleFact(TypedDict):
    """One structured timing fact needed to build a recognition schedule
    for one obligation -- when its recognition period starts and how long
    it runs. Verified the same way every other citation in this project
    is: independently checked against the actual contract text, never
    trusted just because the model returned it."""

    obligation_id: str
    term_start_description: str
    term_length_months: int
    source_quote: str
    citation_verified: bool
    requires_human_review: bool


class ScheduleEntry(TypedDict):
    """One row of the assembled period-by-period revenue recognition
    schedule -- pure arithmetic on already-verified data, no new claim.
    requires_human_review covers the case where the arithmetic couldn't
    actually be done (e.g. an unparseable dollar amount, or a missing/
    unverified schedule fact for an over-time obligation) -- surfaced,
    never silently guessed at or dropped."""

    obligation_id: str
    period_label: str
    recognized_amount: str
    basis: str  # "straight_line_over_time" | "point_in_time"
    requires_human_review: bool


class RevenueSchedule(TypedDict):
    contract_filename: str
    schedule_facts: list[ScheduleFact]
    entries: list[ScheduleEntry]


class AuditTrailEntry(TypedDict):
    """One line of the close package's audit trail. Derived entirely from
    data drafter/analysis.py and close_package/schedule.py already
    produced and verified -- audit_trail.py makes zero new LLM calls and
    asserts zero new claims independent of what's already been checked."""

    category: str  # "performance_obligation" | "price_allocation" | "timing_conclusion" | "schedule_fact"
    subject: str
    conclusion: str
    source_quote: str
    citation_verified: bool
    is_judgement: bool
    judgement_note: str
    requires_human_review: bool


class ClosePackageState(TypedDict):
    """The full state threaded through a Task 2.2 close-package run."""

    run_id: str
    memo_state: DrafterState
    schedule: RevenueSchedule
    audit_trail: list[AuditTrailEntry]
    package_html: str
    session_id: str
    job_id: str
    export_result: dict[str, Any]
    stage_log: list[str]
