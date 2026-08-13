"""Shared schema for Task 2's revenue recognition memo drafter.

Same trust boundary as pipeline/state.py (Task 1): every conclusion that
matters is required to carry a verbatim source quote, and that quote is
independently verified in code against the actual contract text (see
drafter/analysis.py, reusing core/citations.py's quote_is_verifiable --
the same mechanism, not a reimplementation) before it's trusted. "Every
conclusion tied to the specific clause that drove it" (the card's own
"what strong looks like" bullet) is enforced here, not just prompted for.

THE JUDGEMENT REQUIREMENT, MADE LITERAL: the card's second "strong" bullet
is "areas of judgement are flagged as judgement, not stated as fact." Every
one of the three conclusion types below carries its own `is_judgement`
field directly on the record it applies to (not a separate, disconnected
list that could drift out of sync with which specific obligation/
allocation/timing call actually required judgement). A dedicated
JudgementNote list also exists for the memo's own "Areas of Judgement"
section, so a reviewer doesn't have to hunt through every obligation to
find every judgement call -- but the per-record flag is the source of
truth; the section is a rendering of it, not a second, independent claim.
"""

from __future__ import annotations

from typing import Literal, TypedDict

RecognitionPattern = Literal["point_in_time", "over_time"]


class PerformanceObligation(TypedDict):
    """One distinct promise to the customer. `is_distinct` is itself a
    judgement call in plenty of real contracts (e.g. is a warranty a
    separate obligation, or bundled into the product it covers?) -- flagged
    via `is_judgement`, not silently decided one way."""

    obligation_id: str  # short, stable, snake_case -- e.g. "software_license"
    description: str
    source_quote: str
    citation_verified: bool
    is_distinct: bool
    is_judgement: bool
    judgement_note: str  # required (may be "") -- explains the call when is_judgement
    requires_human_review: bool


class PriceAllocation(TypedDict):
    """How the total transaction price splits across obligations. Not every
    contract states a standalone price per obligation -- when it doesn't,
    an allocation still has to be produced (e.g. via a residual or
    estimated-standalone-price method), and THAT is exactly the kind of
    judgement call `is_judgement` exists to flag rather than hide."""

    obligation_id: str  # references PerformanceObligation.obligation_id
    allocated_amount: str  # e.g. "$45,000", or a stated basis if no dollar figure exists
    allocation_basis: str
    source_quote: str
    citation_verified: bool
    is_judgement: bool
    judgement_note: str
    requires_human_review: bool


class TimingConclusion(TypedDict):
    """When revenue for one obligation may be recognized."""

    obligation_id: str
    recognition_pattern: RecognitionPattern
    timing_basis: str
    source_quote: str
    citation_verified: bool
    is_judgement: bool
    judgement_note: str
    requires_human_review: bool


class JudgementNote(TypedDict):
    """One entry per judgement call, consolidated for the memo's own
    "Areas of Judgement" section. Derived FROM the is_judgement flags above
    at synthesis time (see drafter/synthesize.py) -- never an independent
    second source of truth that could disagree with them."""

    topic: str
    obligation_id: str
    explanation: str


class MemoAnalysis(TypedDict):
    """Everything drafter/analysis.py produces and verifies, before any
    memo text is ever assembled. No memo content is built from anything
    that isn't already in here, verified."""

    contract_filename: str
    performance_obligations: list[PerformanceObligation]
    price_allocations: list[PriceAllocation]
    timing_conclusions: list[TimingConclusion]


class DrafterState(TypedDict):
    """The full state threaded through Task 2's drafter run."""

    run_id: str
    contract_path: str
    contract_text: str
    contract_filename: str
    analysis: MemoAnalysis
    judgement_notes: list[JudgementNote]
    memo_html: str
    session_id: str
    job_id: str
    export_result: dict[str, object]
    stage_log: list[str]
