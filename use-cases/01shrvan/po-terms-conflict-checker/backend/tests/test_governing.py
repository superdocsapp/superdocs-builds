"""Which document governs — the part that must never bluff.

The claim being tested is not "it produces an answer". It is that the answer is **derived from the
recorded sequence**, changes when the sequence changes, names what it relied on, and says
INCONCLUSIVE rather than reaching for the nearest rule.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.governing import (
    EventKind,
    GoverningAnalysis,
    Party,
    Playbook,
    SequenceEvent,
    analyse,
    derive_facts,
)

PLAYBOOK = Playbook.from_file(Path(__file__).parents[2] / "rules" / "last-shot-england.json")


def event(kind: EventKind, day: int, by: Party) -> SequenceEvent:
    return SequenceEvent(kind=kind, on=date(2026, 2, day), by=by)


# The classic battle of the forms: buyer orders, supplier acknowledges on its own terms, goods
# arrive and are accepted without a word.
LAST_SHOT_SUPPLIER = [
    event(EventKind.PO_ISSUED, 9, Party.BUYER),
    event(EventKind.ACKNOWLEDGEMENT_RETURNED, 12, Party.SUPPLIER),
    event(EventKind.GOODS_DELIVERED, 26, Party.SUPPLIER),
    event(EventKind.GOODS_ACCEPTED, 26, Party.BUYER),
]


def test_the_supplier_fires_the_last_shot_and_wins() -> None:
    result = analyse(LAST_SHOT_SUPPLIER, PLAYBOOK)

    assert result.likely_to_govern is Party.SUPPLIER
    assert result.rule_id == "LS-1"
    assert not result.is_inconclusive


def test_an_objection_before_performance_changes_the_answer() -> None:
    """The same documents, one extra event, opposite outcome.

    This is what separates an analysis from a guess: it moves when the facts move.
    """
    objected = [*LAST_SHOT_SUPPLIER, event(EventKind.OBJECTION_SENT, 14, Party.BUYER)]

    before = analyse(LAST_SHOT_SUPPLIER, PLAYBOOK)
    after = analyse(objected, PLAYBOOK)

    assert before.likely_to_govern is Party.SUPPLIER
    assert after.likely_to_govern is Party.BUYER, (
        "an objection lodged before performance must stop performance reading as acceptance"
    )
    assert after.rule_id == "LS-3"


def test_an_objection_lodged_after_delivery_does_not_rescue_the_buyer() -> None:
    """Timing is the whole doctrine. An objection after performance is too late."""
    too_late = [*LAST_SHOT_SUPPLIER, event(EventKind.OBJECTION_SENT, 28, Party.BUYER)]

    result = analyse(too_late, PLAYBOOK)

    assert result.likely_to_govern is Party.SUPPLIER
    assert result.facts_relied_on.objection_before_performance is False


def test_nothing_performed_yet_leaves_the_exchange_open() -> None:
    paper_only = LAST_SHOT_SUPPLIER[:2]

    result = analyse(paper_only, PLAYBOOK)

    assert result.rule_id == "LS-4"
    assert result.likely_to_govern is None
    assert "still open" in result.conclusion


def test_event_order_does_not_change_the_answer() -> None:
    """Facts are derived by date, so a caller may supply events in any order."""
    shuffled = list(reversed(LAST_SHOT_SUPPLIER))

    assert analyse(shuffled, PLAYBOOK).rule_id == analyse(LAST_SHOT_SUPPLIER, PLAYBOOK).rule_id


# --- refusing to guess ---------------------------------------------------------------------------


def test_an_empty_sequence_is_inconclusive_and_says_what_is_missing() -> None:
    result = analyse([], PLAYBOOK)

    assert result.is_inconclusive
    assert result.likely_to_govern is None
    assert result.missing_to_decide, "an inconclusive result must name the gap, not just shrug"
    assert any("terms" in item for item in result.missing_to_decide)
    assert any("performed" in item for item in result.missing_to_decide)


def test_paper_with_no_performance_reports_the_missing_fact() -> None:
    facts = derive_facts(LAST_SHOT_SUPPLIER[:2])

    assert facts.last_terms_from is Party.SUPPLIER
    assert facts.first_performance_on is None
    assert facts.performance_followed_last_terms is False


# --- the analysis shows its work -----------------------------------------------------------------


def test_every_analysis_names_the_facts_it_relied_on() -> None:
    prose = analyse(LAST_SHOT_SUPPLIER, PLAYBOOK).as_prose()

    assert "Facts this depends on:" in prose
    assert "last set of terms was sent by the supplier" in prose
    assert "did not object before performance" in prose
    assert "2026-02-12" in prose, "the date of the governing document is stated"


def test_every_analysis_carries_the_disclaimer() -> None:
    for events in ([], LAST_SHOT_SUPPLIER, LAST_SHOT_SUPPLIER[:2]):
        prose = analyse(events, PLAYBOOK).as_prose()
        assert "not legal advice" in prose, "a legal position must never be stated bare"
        assert "counsel" in prose


def test_the_doctrine_is_data_not_code() -> None:
    """A different jurisdiction is a new JSON file, not a code change."""
    first_shot = Playbook.model_validate(
        {
            "doctrine": "House view: first shot prevails",
            "summary": "The buyer's order governs unless expressly displaced in writing.",
            "authority_note": "Fictional house policy, for testing that doctrine is swappable.",
            "rules": [
                {
                    "id": "FS-1",
                    "conclusion": "buyer",
                    "when": {"performance_followed_last_terms": True},
                    "because": "House policy treats the purchase order as governing.",
                }
            ],
            "inconclusive_because": "No rule matched.",
        }
    )

    assert analyse(LAST_SHOT_SUPPLIER, PLAYBOOK).likely_to_govern is Party.SUPPLIER
    assert analyse(LAST_SHOT_SUPPLIER, first_shot).likely_to_govern is Party.BUYER, (
        "swapping the rule file must swap the conclusion, with no code change"
    )


def test_a_supplier_objection_is_refused_rather_than_mis_analysed() -> None:
    """This playbook models buyer objections. Anything else fails loudly."""
    with pytest.raises(ValidationError, match="objections raised by the buyer"):
        SequenceEvent(
            kind=EventKind.OBJECTION_SENT, on=date(2026, 2, 14), by=Party.SUPPLIER
        )


def test_the_disclaimer_is_not_something_a_caller_can_forget() -> None:
    assert "not legal advice" in GoverningAnalysis.DISCLAIMER
