"""The report has to read like something a utility would file.

These caught real defects in the first drafted report: "1 mutual-aid crews",
"0 hours 38 minutes", "25 hours 0 minutes", and a log note whose proper noun was
mangled to "northbank Power" by a lead-in that downcased its first letter. None of
them are crashes, and all of them would be the first thing a reader noticed.
"""

from __future__ import annotations

import re

import pytest

from afteraction.corpus import available_events, load_corpus
from afteraction.facts import TIMELINE, _duration, build_facts

ALL_EVENTS = available_events()


@pytest.fixture(scope="module", params=ALL_EVENTS)
def facts(request):
    return build_facts(load_corpus(request.param))


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (0.6333, "38 minutes"),
        (25.0, "25 hours"),
        (1.0, "1 hour"),
        (2.6833, "2 hours 41 minutes"),
        (3.5, "3 hours 30 minutes"),
        (0.0166, "1 minute"),
    ],
)
def test_durations_read_naturally(hours, expected):
    assert _duration(hours) == expected


def test_no_claim_says_zero_hours_or_zero_minutes(facts):
    for claim in facts.claims:
        # word-bounded: "20 hours" is fine and contains "0 hours" as a substring
        assert not re.search(r"\b0 hours\b", claim.text), claim.text
        assert not re.search(r"\b0 minutes\b", claim.text), claim.text


def test_counts_agree_with_their_nouns(facts):
    """No '1 crews', no '1 channels'."""
    for claim in facts.claims:
        bad = re.findall(r"\b1 (crews|channels|consumer counts|consumer communications)\b", claim.text)
        assert not bad, f"{claim.claim_id}: {bad} in {claim.text!r}"


def test_record_notes_reach_the_model_exactly_as_written(facts):
    """The note is the record, so it is handed over unedited.

    The timeline's prose is now written by SuperDocs from a window's raw records, which
    makes the instruction the place where this property lives. Every note in every
    window must appear in it verbatim — trimming, re-casing or paraphrasing a note
    before sending it would alter the record and call the result a quotation.
    """
    from afteraction.sections import timeline_instruction

    instruction = timeline_instruction(facts)
    assert instruction
    for window in facts.windows:
        for entry in window.entries:
            assert entry.note in instruction, f"{entry.entry_id} was altered before being sent"


def test_every_window_record_is_offered_with_its_own_id(facts):
    """A window's records are listed against their ids, so the bullet that comes back
    can carry every one of them and traceability has something to resolve."""
    from afteraction.sections import timeline_instruction

    instruction = timeline_instruction(facts)
    for window in facts.windows:
        for entry in window.entries:
            assert f"  {entry.entry_id}  " in instruction


def test_proper_nouns_survive_into_the_timeline(facts):
    """'Durgapur circle' must never appear as 'durgapur circle'.

    Grafting a note onto a lead-in by downcasing its first letter is how proper nouns
    get mangled, and these notes are the record.
    """
    from afteraction.sections import timeline_instruction

    instruction = timeline_instruction(facts)
    assert "durgapur" not in instruction
    assert "neamatpur" not in instruction


def test_large_numbers_are_grouped(facts):
    """A commission reads 41,250, not 41250."""
    for claim in facts.claims:
        assert not re.search(r"\b\d{5,}\b", claim.text), claim.text
