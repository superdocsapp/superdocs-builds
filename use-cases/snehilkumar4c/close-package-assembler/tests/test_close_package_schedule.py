"""Tests for close_package/schedule.py -- Task 2.2's one genuinely new
piece of domain logic. Two things worth testing hard, same discipline as
every other stage: (1) a schedule fact whose citation doesn't actually
verify (or whose obligation_id doesn't match an established obligation)
must be flagged, never silently trusted; (2) the arithmetic that turns
verified facts into an actual period-by-period schedule must be correct,
and must flag (never guess at) anything it can't compute.
"""

from __future__ import annotations

from typing import Any

from close_package.schedule import (
    build_obligations_context,
    compute_schedule_entries,
    extract_schedule_facts,
)
from close_package.state import ClosePackageState
from drafter.state import (
    DrafterState,
    MemoAnalysis,
    PerformanceObligation,
    PriceAllocation,
    TimingConclusion,
)

_CONTRACT_TEXT = (
    "This Agreement grants Customer access to the Platform for a term of "
    "twelve (12) months beginning on the Effective Date, at an annual fee "
    "of $84,000."
)


def _obligation(**overrides: object) -> PerformanceObligation:
    base: PerformanceObligation = {
        "obligation_id": "platform_access",
        "description": "Access to the platform",
        "source_quote": "access to the Platform",
        "citation_verified": True,
        "is_distinct": True,
        "is_judgement": False,
        "judgement_note": "",
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
        "citation_verified": True,
        "is_judgement": False,
        "judgement_note": "",
        "requires_human_review": False,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _analysis(
    obligations: list[PerformanceObligation] | None = None,
    allocations: list[PriceAllocation] | None = None,
    timings: list[TimingConclusion] | None = None,
) -> MemoAnalysis:
    return {
        "contract_filename": "contract.txt",
        "performance_obligations": obligations if obligations is not None else [_obligation()],
        "price_allocations": allocations if allocations is not None else [_allocation()],
        "timing_conclusions": timings if timings is not None else [_timing()],
    }


def _state(analysis: MemoAnalysis | None = None) -> ClosePackageState:
    memo_state: DrafterState = {
        "run_id": "cp-test",
        "contract_path": "contract.txt",
        "contract_text": _CONTRACT_TEXT,
        "contract_filename": "contract.txt",
        "analysis": analysis if analysis is not None else _analysis(),
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
            "schedule_facts": [],
            "entries": [],
        },
        "audit_trail": [],
        "package_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }


class _FakeLLMClient:
    def __init__(self, facts: list[dict[str, Any]]) -> None:
        self._facts = facts

    def extract_recognition_schedule_facts(
        self, contract_text: str, obligations_context: str, idem_key: str | None = None
    ) -> list[dict[str, Any]]:
        return self._facts


def test_build_obligations_context_includes_recognition_pattern() -> None:
    context = build_obligations_context(_analysis())
    assert "platform_access" in context
    assert "over_time" in context


def test_verified_schedule_fact_is_marked_true() -> None:
    llm = _FakeLLMClient(
        [
            {
                "obligation_id": "platform_access",
                "term_start_description": "the Effective Date",
                "term_length_months": 12,
                # Genuinely present in the fixture contract text.
                "source_quote": "twelve (12) months beginning on the Effective Date",
            }
        ]
    )
    result = extract_schedule_facts(_state(), llm)  # type: ignore[arg-type]
    fact = result["schedule"]["schedule_facts"][0]
    assert fact["citation_verified"] is True
    assert fact["requires_human_review"] is False


def test_fabricated_schedule_fact_citation_is_caught() -> None:
    llm = _FakeLLMClient(
        [
            {
                "obligation_id": "platform_access",
                "term_start_description": "the Effective Date",
                "term_length_months": 12,
                # NOT present anywhere in the fixture contract.
                "source_quote": "a term of ninety-nine (99) years",
            }
        ]
    )
    result = extract_schedule_facts(_state(), llm)  # type: ignore[arg-type]
    fact = result["schedule"]["schedule_facts"][0]
    assert fact["citation_verified"] is False
    assert fact["requires_human_review"] is True


def test_schedule_fact_with_unknown_obligation_id_is_flagged() -> None:
    """A schedule fact for an obligation_id that was never actually
    established by Task 2's own analysis must never be silently trusted."""
    llm = _FakeLLMClient(
        [
            {
                "obligation_id": "an_obligation_that_does_not_exist",
                "term_start_description": "the Effective Date",
                "term_length_months": 12,
                "source_quote": "twelve (12) months beginning on the Effective Date",
            }
        ]
    )
    result = extract_schedule_facts(_state(), llm)  # type: ignore[arg-type]
    fact = result["schedule"]["schedule_facts"][0]
    assert fact["citation_verified"] is False


def test_malformed_schedule_fact_is_skipped_not_crashed_on() -> None:
    llm = _FakeLLMClient(["not-a-dict"])  # type: ignore[list-item]
    result = extract_schedule_facts(_state(), llm)  # type: ignore[arg-type]
    assert result["schedule"]["schedule_facts"] == []


def test_compute_schedule_entries_splits_over_time_evenly() -> None:
    state = _state()
    state["schedule"]["schedule_facts"] = [
        {
            "obligation_id": "platform_access",
            "term_start_description": "the Effective Date",
            "term_length_months": 12,
            "source_quote": "twelve (12) months beginning on the Effective Date",
            "citation_verified": True,
            "requires_human_review": False,
        }
    ]
    result = compute_schedule_entries(state)
    entries = result["schedule"]["entries"]
    assert len(entries) == 12
    assert entries[0]["period_label"] == "Month 1 of 12"
    assert entries[0]["recognized_amount"] == "$7,000.00"
    assert entries[0]["requires_human_review"] is False
    # Total across all months must reconstruct the original allocated amount.
    total = sum(float(e["recognized_amount"].replace("$", "").replace(",", "")) for e in entries)
    assert round(total, 2) == 84000.00


def test_compute_schedule_entries_duplicate_verified_fact_keeps_first_not_silently_last() -> None:
    """If the model ever returns two verified schedule facts for the same
    obligation_id, that's a real ambiguity -- it must not be silently
    resolved by whichever happened to be last in the list. The first
    verified fact is kept deterministically, and computation still
    proceeds (this is a logged anomaly, not a fatal one)."""
    state = _state()
    state["schedule"]["schedule_facts"] = [
        {
            "obligation_id": "platform_access",
            "term_start_description": "the Effective Date",
            "term_length_months": 12,
            "source_quote": "twelve (12) months beginning on the Effective Date",
            "citation_verified": True,
            "requires_human_review": False,
        },
        {
            "obligation_id": "platform_access",
            "term_start_description": "some other description",
            "term_length_months": 24,  # a genuinely different, conflicting fact
            "source_quote": "a term of twelve (12) months",
            "citation_verified": True,
            "requires_human_review": False,
        },
    ]
    result = compute_schedule_entries(state)
    entries = result["schedule"]["entries"]
    # The FIRST fact (12 months) is the one that wins, not the second (24).
    assert len(entries) == 12
    assert entries[0]["period_label"] == "Month 1 of 12"


def test_compute_schedule_entries_point_in_time_is_a_single_entry() -> None:
    analysis = _analysis(timings=[_timing(recognition_pattern="point_in_time")])
    state = _state(analysis)
    result = compute_schedule_entries(state)
    entries = result["schedule"]["entries"]
    assert len(entries) == 1
    assert entries[0]["period_label"] == "Period 1 (point-in-time)"
    assert entries[0]["recognized_amount"] == "$84,000.00"
    assert entries[0]["requires_human_review"] is False


def test_compute_schedule_entries_flags_over_time_with_no_verified_term_length() -> None:
    """The core guarantee: an over-time obligation with no usable schedule
    fact does NOT get a silently-guessed schedule -- it's flagged."""
    state = _state()  # no schedule_facts at all
    result = compute_schedule_entries(state)
    entries = result["schedule"]["entries"]
    assert len(entries) == 1
    assert entries[0]["requires_human_review"] is True
    assert "unavailable" in entries[0]["period_label"]


def test_compute_schedule_entries_flags_unparseable_dollar_amount() -> None:
    analysis = _analysis(
        allocations=[_allocation(allocated_amount="included in bundle, no standalone price stated")]
    )
    state = _state(analysis)
    result = compute_schedule_entries(state)
    entries = result["schedule"]["entries"]
    assert len(entries) == 1
    assert entries[0]["requires_human_review"] is True


def test_stage_log_appends_through_both_stages() -> None:
    state = _state()
    state["stage_log"] = ["analyze_contract", "synthesize_memo"]
    llm = _FakeLLMClient([])
    result1 = extract_schedule_facts(state, llm)  # type: ignore[arg-type]
    state.update(result1)  # type: ignore[typeddict-item]
    result2 = compute_schedule_entries(state)
    assert result2["stage_log"] == [
        "analyze_contract",
        "synthesize_memo",
        "extract_schedule_facts",
        "compute_schedule_entries",
    ]
