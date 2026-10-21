"""Task 2's citation-verification tests. The key thing worth testing hard,
same as Task 1's stage 2/3 tests: a conclusion whose source_quote doesn't
actually appear in the contract must be flagged (citation_verified=False,
requires_human_review=True), never silently trusted just because the model
said so -- and a judgement call is not exempt from that check.
"""

from __future__ import annotations

from typing import Any

from drafter.analysis import analyze_contract
from drafter.state import DrafterState

_CONTRACT_TEXT = (
    "This Agreement grants Customer access to the Platform for a term of "
    "twelve (12) months, at an annual fee of $45,000. Support and "
    "onboarding services are provided as part of this Agreement."
)


def _state(contract_text: str = _CONTRACT_TEXT) -> DrafterState:
    return {
        "run_id": "drafter-test-run",
        "contract_path": "contract.txt",
        "contract_text": contract_text,
        "contract_filename": "contract.txt",
        "analysis": {
            "contract_filename": "contract.txt",
            "performance_obligations": [],
            "price_allocations": [],
            "timing_conclusions": [],
        },
        "judgement_notes": [],
        "memo_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }


class _FakeLLMClient:
    """One genuinely-verifiable obligation/allocation/timing set, plus one
    of each that cites text NOT actually present in the contract -- a
    stand-in for a hallucinated citation, same pattern as Task 1's fake
    clients."""

    def analyze_revenue_recognition(
        self, contract_text: str, idem_key: str | None = None
    ) -> dict[str, Any]:
        return {
            "performance_obligations": [
                {
                    "obligation_id": "platform_access",
                    "description": "Access to the SaaS platform",
                    # Genuinely present.
                    "source_quote": "access to the Platform",
                    "is_distinct": True,
                    "is_judgement": False,
                    "judgement_note": "",
                },
                {
                    "obligation_id": "extended_warranty",
                    "description": "A warranty this contract never mentions",
                    # NOT present anywhere in the fixture text.
                    "source_quote": "a five-year extended warranty on all hardware",
                    "is_distinct": True,
                    "is_judgement": True,
                    "judgement_note": "fabricated for the test",
                },
            ],
            "price_allocations": [
                {
                    "obligation_id": "platform_access",
                    "allocated_amount": "$45,000",
                    "allocation_basis": "stated explicitly in contract",
                    # Genuinely present.
                    "source_quote": "annual fee of $45,000",
                    "is_judgement": False,
                    "judgement_note": "",
                }
            ],
            "timing_conclusions": [
                {
                    "obligation_id": "platform_access",
                    "recognition_pattern": "over_time",
                    "timing_basis": "customer benefits throughout the term",
                    # Genuinely present.
                    "source_quote": "a term of twelve (12) months",
                    "is_judgement": False,
                    "judgement_note": "",
                }
            ],
        }


def test_verified_obligation_is_marked_true_and_not_flagged() -> None:
    result = analyze_contract(_state(), _FakeLLMClient())  # type: ignore[arg-type]
    by_id = {o["obligation_id"]: o for o in result["analysis"]["performance_obligations"]}
    assert by_id["platform_access"]["citation_verified"] is True
    assert by_id["platform_access"]["requires_human_review"] is False


def test_fabricated_obligation_citation_is_caught_even_when_flagged_as_judgement() -> None:
    """The core guarantee: is_judgement=True does NOT exempt a conclusion
    from citation verification. A judgement call still needs a real anchor
    in the contract text."""
    result = analyze_contract(_state(), _FakeLLMClient())  # type: ignore[arg-type]
    by_id = {o["obligation_id"]: o for o in result["analysis"]["performance_obligations"]}
    assert by_id["extended_warranty"]["citation_verified"] is False
    assert by_id["extended_warranty"]["requires_human_review"] is True


def test_verified_allocation_and_timing_are_marked_true() -> None:
    result = analyze_contract(_state(), _FakeLLMClient())  # type: ignore[arg-type]
    allocation = result["analysis"]["price_allocations"][0]
    timing = result["analysis"]["timing_conclusions"][0]
    assert allocation["citation_verified"] is True
    assert timing["citation_verified"] is True
    assert timing["recognition_pattern"] == "over_time"


def test_invalid_recognition_pattern_is_flagged_not_coerced() -> None:
    class _BadPatternLLMClient(_FakeLLMClient):
        def analyze_revenue_recognition(
            self, contract_text: str, idem_key: str | None = None
        ) -> dict[str, Any]:
            result = super().analyze_revenue_recognition(contract_text, idem_key)
            result["timing_conclusions"][0]["recognition_pattern"] = "sometime_probably"
            return result

    result = analyze_contract(_state(), _BadPatternLLMClient())  # type: ignore[arg-type]
    timing = result["analysis"]["timing_conclusions"][0]
    assert timing["citation_verified"] is False
    assert timing["requires_human_review"] is True


def test_judgement_notes_are_derived_from_is_judgement_flags() -> None:
    result = analyze_contract(_state(), _FakeLLMClient())  # type: ignore[arg-type]
    topics = {n["topic"] for n in result["judgement_notes"]}
    assert any("extended_warranty" in t for t in topics)
    # The non-judgement obligation/allocation/timing must NOT produce a note.
    assert not any("platform_access" in t for t in topics)


def test_malformed_item_is_skipped_not_crashed_on() -> None:
    class _MixedFakeLLMClient:
        def analyze_revenue_recognition(
            self, contract_text: str, idem_key: str | None = None
        ) -> dict[str, Any]:
            return {
                "performance_obligations": [
                    "not-a-dict",
                    {
                        "obligation_id": "platform_access",
                        "description": "ok",
                        "source_quote": "access to the Platform",
                        "is_distinct": True,
                        "is_judgement": False,
                        "judgement_note": "",
                    },
                ],
                "price_allocations": [],
                "timing_conclusions": [],
            }

    result = analyze_contract(_state(), _MixedFakeLLMClient())  # type: ignore[arg-type]
    assert len(result["analysis"]["performance_obligations"]) == 1
    assert result["analysis"]["performance_obligations"][0]["obligation_id"] == "platform_access"


def test_stage_log_appends() -> None:
    state = _state()
    state["stage_log"] = ["some_prior_stage"]
    result = analyze_contract(state, _FakeLLMClient())  # type: ignore[arg-type]
    assert result["stage_log"] == ["some_prior_stage", "analyze_contract"]
