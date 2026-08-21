"""The carry-forward, which is half of what the card calls strong.

The property under test is not "a JSON file can be written". It is that Storm B's
report opens Storm A's items with the right status because it read them, and that
running the events twice does not change the answer.
"""

from __future__ import annotations

import pytest

from afteraction.corpus import load_corpus, load_lessons_opened, load_resolutions
from afteraction.lessons import CarryForwardError, apply_event, inherited, raised_here, summarise
from afteraction.models import LessonStatus


def _apply(event_id: str, store: list | None = None) -> list:
    corpus = load_corpus(event_id)
    return apply_event(
        store or [],
        corpus,
        load_lessons_opened(event_id),
        load_resolutions(event_id),
    )


def test_storm_a_opens_its_lessons():
    store = _apply("storm-a")
    assert len(store) == 4
    assert all(x.status is LessonStatus.OPEN for x in store)
    assert all(x.opened_in_event == "storm-a" for x in store)


def test_storm_b_inherits_storm_a_and_closes_one():
    store = _apply("storm-b", _apply("storm-a"))
    carried = {x.lesson_id: x for x in inherited(store, "storm-b")}

    assert set(carried) == {"LL-A1", "LL-A2", "LL-A3", "LL-A4"}
    assert carried["LL-A2"].status is LessonStatus.CLOSED
    assert carried["LL-A2"].closed_in_event == "storm-b"
    assert carried["LL-A1"].status is LessonStatus.OPEN
    assert carried["LL-A3"].status is LessonStatus.OPEN
    # LL-A4 was raised by a consumer report nobody inspected during storm-a, and
    # storm-b closed it by sending a gang to look.
    assert carried["LL-A4"].status is LessonStatus.CLOSED
    assert carried["LL-A4"].closed_sources == ["FLD-0005"]


def test_a_closed_item_cites_the_evidence_that_closed_it():
    """Not the evidence that raised it. Those live in different events' logs."""
    store = _apply("storm-b", _apply("storm-a"))
    closed = next(x for x in store if x.lesson_id == "LL-A2")
    assert closed.closed_sources == ["TEL-0001", "COM-0002"]  # storm-b's records
    assert closed.sources == ["TEL-0001", "COM-0003"]  # storm-a's, untouched
    assert closed.closed_in_event == "storm-b"


def test_an_item_still_open_records_why_it_is_still_open():
    """An item nobody looked at and an item examined and found unfixed are different
    facts, and two consecutive reports have to be able to tell them apart."""
    store = _apply("storm-b", _apply("storm-a"))
    still_open = next(x for x in store if x.lesson_id == "LL-A1")
    assert still_open.last_reviewed_event == "storm-b"
    assert still_open.carry_note
    assert still_open.carry_sources == ["CRW-0006"]


def test_storm_b_raises_its_own_item_without_inheriting_it():
    store = _apply("storm-b", _apply("storm-a"))
    mine = raised_here(store, "storm-b")
    assert [x.lesson_id for x in mine] == ["LL-B1"]
    assert summarise(store, "storm-b") == {
        "inherited": 4,
        "inherited_open": 2,
        "inherited_closed": 2,
        "raised_here": 1,
    }


def test_applying_the_same_event_twice_changes_nothing():
    """Re-running must be safe: without this the carry-forward is an artefact of how
    many times the pipeline happened to run, not a property of the events."""
    once = _apply("storm-b", _apply("storm-a"))
    twice = _apply("storm-b", _apply("storm-b", _apply("storm-a")))
    assert [x.model_dump() for x in once] == [x.model_dump() for x in twice]


def test_full_replay_from_empty_is_stable():
    first = _apply("storm-b", _apply("storm-a"))
    second = _apply("storm-b", _apply("storm-a", first))
    assert [x.model_dump() for x in first] == [x.model_dump() for x in second]


def test_a_closure_citing_an_unknown_entry_is_refused():
    corpus = load_corpus("storm-b")
    with pytest.raises(CarryForwardError, match="not in this event's log"):
        apply_event(
            _apply("storm-a"),
            corpus,
            [],
            [{"lesson_id": "LL-A1", "status": LessonStatus.CLOSED, "note": "done", "sources": ["EL-9999"]}],
        )


def test_a_closure_for_an_item_nobody_opened_is_refused():
    corpus = load_corpus("storm-b")
    with pytest.raises(CarryForwardError, match="which no event has ever opened"):
        apply_event(
            [],
            corpus,
            [],
            [{"lesson_id": "LL-ZZ", "status": LessonStatus.CLOSED, "note": "done", "sources": ["EL-0004"]}],
        )


def test_an_event_cannot_close_an_item_it_raised_itself():
    corpus = load_corpus("storm-a")
    with pytest.raises(CarryForwardError, match="both opened and resolved"):
        apply_event(
            [],
            corpus,
            load_lessons_opened("storm-a"),
            [{"lesson_id": "LL-A1", "status": LessonStatus.CLOSED, "note": "x", "sources": ["EL-0010"]}],
        )
