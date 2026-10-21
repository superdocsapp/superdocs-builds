"""Stage 2 (synthesize) tests. No LLM involved -- this stage is pure,
deterministic assembly of already-verified data, so these are all
fake-data/logic tests. The two load-bearing guarantees: (1) nothing is
silently dropped, including unverified conclusions (unlike Task 1's
register, a memo reader needs to know what COULDN'T be verified, not just
what could), and (2) judgement notes render straight from what
drafter/analysis.py already derived, not re-decided here.
"""

from __future__ import annotations

from drafter.state import (
    DrafterState,
    JudgementNote,
    MemoAnalysis,
    PerformanceObligation,
    PriceAllocation,
    TimingConclusion,
)
from drafter.synthesize import render_memo_html, synthesize_memo


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
        "allocated_amount": "$45,000",
        "allocation_basis": "stated explicitly in contract",
        "source_quote": "annual fee of $45,000",
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


def test_verified_conclusions_render_without_a_review_flag() -> None:
    html = render_memo_html(_analysis(), [])
    assert "platform_access" in html
    assert "$45,000" in html
    assert "NEEDS HUMAN REVIEW" not in html


def test_unverified_conclusion_gets_an_inline_flag_and_a_dedicated_section() -> None:
    """The core guarantee for this stage: an unverified conclusion is NOT
    silently dropped -- it's rendered with an explicit flag AND listed in
    "Items Requiring Verification", unlike Task 1's register (where an
    unverified fact is just excluded)."""
    obligations = [_obligation(citation_verified=False, requires_human_review=True)]
    html = render_memo_html(_analysis(obligations=obligations), [])
    assert "NEEDS HUMAN REVIEW" in html
    assert "Items Requiring Verification" in html
    assert "could not be independently verified" in html
    assert "platform_access" in html.split("Items Requiring Verification")[1]


def test_all_verified_reports_it_honestly() -> None:
    html = render_memo_html(_analysis(), [])
    assert "All conclusions in this memo are backed by citations" in html


def test_no_judgement_calls_reports_it_honestly_not_as_an_omission() -> None:
    html = render_memo_html(_analysis(), [])
    assert "No areas of judgement were identified" in html


def test_judgement_notes_render_from_what_was_already_derived() -> None:
    notes: list[JudgementNote] = [
        {
            "topic": "Performance obligation: extended_warranty",
            "obligation_id": "extended_warranty",
            "explanation": "Warranty treated as a separate obligation per contract language.",
        }
    ]
    html = render_memo_html(_analysis(), notes)
    assert "extended_warranty" in html.split("Areas of Judgement")[1].split("Items Requiring")[0]
    assert "Warranty treated as a separate obligation" in html


def test_empty_analysis_reports_it_honestly_not_a_crash() -> None:
    html = render_memo_html(_analysis(obligations=[], allocations=[], timings=[]), [])
    assert "No performance obligations were identified" in html
    assert "No price allocation could be determined" in html
    assert "No timing conclusions were determined" in html


def test_synthesize_memo_stage_log_appends() -> None:
    state: DrafterState = {
        "run_id": "drafter-test",
        "contract_path": "contract.txt",
        "contract_text": "irrelevant",
        "contract_filename": "contract.txt",
        "analysis": _analysis(),
        "judgement_notes": [],
        "memo_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": ["analyze_contract"],
    }
    result = synthesize_memo(state)
    assert result["stage_log"] == ["analyze_contract", "synthesize_memo"]
    assert "<h1>Revenue Recognition Memo</h1>" in result["memo_html"]
