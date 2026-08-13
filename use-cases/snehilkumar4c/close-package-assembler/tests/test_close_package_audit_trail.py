"""Tests for close_package/audit_trail.py. No LLM involved -- this stage
is pure re-shaping of already-verified data, so these are all fake-data/
logic tests. The load-bearing guarantee: every category of conclusion
(obligation, allocation, timing, schedule fact) shows up in the trail with
its ACTUAL verification/judgement status carried through unchanged, not
re-derived or silently dropped.
"""

from __future__ import annotations

from close_package.audit_trail import build_audit_trail
from close_package.state import ClosePackageState
from drafter.state import (
    DrafterState,
    MemoAnalysis,
    PerformanceObligation,
    PriceAllocation,
    TimingConclusion,
)


def _obligation(**overrides: object) -> PerformanceObligation:
    base: PerformanceObligation = {
        "obligation_id": "platform_access",
        "description": "Access to the platform",
        "source_quote": "access to the Platform",
        "citation_verified": True,
        "is_distinct": True,
        "is_judgement": True,
        "judgement_note": "distinctness required interpretation",
        "requires_human_review": False,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _allocation(**overrides: object) -> PriceAllocation:
    base: PriceAllocation = {
        "obligation_id": "platform_access",
        "allocated_amount": "$84,000",
        "allocation_basis": "stated explicitly in contract",
        "source_quote": "annual fee of $84,000",
        "citation_verified": True,
        "is_judgement": False,
        "judgement_note": "",
        "requires_human_review": False,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _timing(**overrides: object) -> TimingConclusion:
    base: TimingConclusion = {
        "obligation_id": "platform_access",
        "recognition_pattern": "over_time",
        "timing_basis": "customer benefits throughout the term",
        "source_quote": "a term of twelve (12) months",
        "citation_verified": False,
        "is_judgement": True,
        "judgement_note": "timing pattern required interpretation",
        "requires_human_review": True,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _state() -> ClosePackageState:
    analysis: MemoAnalysis = {
        "contract_filename": "contract.txt",
        "performance_obligations": [_obligation()],
        "price_allocations": [_allocation()],
        "timing_conclusions": [_timing()],
    }
    memo_state: DrafterState = {
        "run_id": "cp-test",
        "contract_path": "contract.txt",
        "contract_text": "irrelevant for this stage",
        "contract_filename": "contract.txt",
        "analysis": analysis,
        "judgement_notes": [],
        "memo_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }
    return {
        "run_id": "cp-test",
        "memo_state": memo_state,
        "schedule": {
            "contract_filename": "contract.txt",
            "schedule_facts": [
                {
                    "obligation_id": "platform_access",
                    "term_start_description": "the Effective Date",
                    "term_length_months": 12,
                    "source_quote": "twelve (12) months beginning on the Effective Date",
                    "citation_verified": True,
                    "requires_human_review": False,
                }
            ],
            "entries": [],
        },
        "audit_trail": [],
        "package_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": ["analyze_contract", "synthesize_memo", "extract_schedule_facts", "compute_schedule_entries"],
    }


def test_every_category_appears_in_the_trail() -> None:
    result = build_audit_trail(_state())
    categories = {e["category"] for e in result["audit_trail"]}
    assert categories == {
        "performance_obligation",
        "price_allocation",
        "timing_conclusion",
        "schedule_fact",
    }


def test_verification_and_judgement_status_carried_through_unchanged() -> None:
    """The core guarantee: this stage never re-derives or overrides what
    drafter/analysis.py and close_package/schedule.py already concluded
    about verification/judgement status."""
    result = build_audit_trail(_state())
    by_category = {e["category"]: e for e in result["audit_trail"]}

    # The obligation was verified and flagged as a judgement call.
    assert by_category["performance_obligation"]["citation_verified"] is True
    assert by_category["performance_obligation"]["is_judgement"] is True
    assert by_category["performance_obligation"]["judgement_note"] == "distinctness required interpretation"

    # The timing conclusion was UNVERIFIED and required review -- must
    # show up that way in the trail too, not silently cleaned up.
    assert by_category["timing_conclusion"]["citation_verified"] is False
    assert by_category["timing_conclusion"]["requires_human_review"] is True


def test_schedule_facts_are_never_marked_as_judgement_calls() -> None:
    """Schedule facts are mechanical extractions, not accounting
    characterizations -- they should never be flagged is_judgement=True,
    unlike obligation/timing conclusions."""
    result = build_audit_trail(_state())
    schedule_entry = next(e for e in result["audit_trail"] if e["category"] == "schedule_fact")
    assert schedule_entry["is_judgement"] is False


def test_stage_log_appends() -> None:
    result = build_audit_trail(_state())
    assert result["stage_log"][-1] == "build_audit_trail"
    assert result["stage_log"][:-1] == [
        "analyze_contract",
        "synthesize_memo",
        "extract_schedule_facts",
        "compute_schedule_entries",
    ]
