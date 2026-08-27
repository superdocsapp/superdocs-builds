"""The property the whole build rests on: a claim must be checkable.

The card's bar is extracting the actual commitments rather than summarising politely,
and the difference is evidence. These tests run entirely offline against a real thread —
no stand-in involved — so they fail for real reasons.
"""

from __future__ import annotations

from thread_to_letter.commitments import Commitment
from thread_to_letter.thread import Thread, normalise
from thread_to_letter.verify import MIN_FRAGMENT, locate, unsupported, verify


def _c(quote: str, source: str = "7", status: str = "firm") -> Commitment:
    return Commitment("Calder", "Northwind", "deliver mapping", "21 Mar", status,
                      source, quote)


def test_an_exact_quote_is_found(thread: Thread) -> None:
    found, index, _ = locate(thread, "we will deliver the schema mapping document by 21 March 2026")
    assert found and index == 7


def test_a_quote_survives_line_wrapping(thread: Thread) -> None:
    """Mail wraps at seventy-odd characters. A sentence typed as one thought arrives
    split across lines, and a checker that missed those would reject true commitments."""
    wrapped = "Revised commitment: we will deliver the schema mapping\ndocument by 21 March\n2026."
    found, index, _ = locate(thread, wrapped)
    assert found and index == 7


def test_an_elided_quote_is_still_evidence(thread: Thread) -> None:
    found, index, _ = locate(thread, "we will deliver ... by 21 March 2026")
    assert found and index == 7


def test_elision_cannot_smuggle_in_new_words(thread: Thread) -> None:
    """Every fragment must be real. The gap between them is not a licence to invent."""
    found, _, note = locate(thread, "we will deliver ... with a full refund if late")
    assert not found
    assert "do not appear" in note


def test_an_invented_quote_is_rejected(thread: Thread) -> None:
    found, _, note = locate(thread, "we guarantee delivery by 1 March or the work is free")
    assert not found
    assert "do not appear" in note


def test_a_quote_too_short_to_identify_anything_is_rejected(thread: Thread) -> None:
    found, _, note = locate(thread, "we will")
    assert not found
    assert "too short" in note
    assert len("we will") < MIN_FRAGMENT


def test_fragments_must_appear_in_order(thread: Thread) -> None:
    """Reordering someone's words changes what they said."""
    forwards, _, _ = locate(thread, "Bad news on the 14th ... 21 March 2026")
    backwards, _, _ = locate(thread, "21 March 2026 ... Bad news on the 14th")
    assert forwards
    assert not backwards


def test_curly_quotes_and_dashes_do_not_break_matching() -> None:
    assert normalise("we'll deliver - by then") == normalise("we'll deliver - by then")


def test_verification_marks_rather_than_deletes(thread: Thread) -> None:
    """A row the model could not back up is the one thing a reviewer most wants to see.
    Silently dropping it would hide the only failure mode worth watching for."""
    rows = [_c("we will deliver the schema mapping document by 21 March 2026"),
            _c("we promise a full refund")]
    verified = verify(thread, rows)
    assert len(verified) == 2
    assert verified[0].quote_found and not verified[1].quote_found
    assert [c.quote for c in unsupported(verified)] == ["we promise a full refund"]


def test_a_misattributed_quote_is_corrected_and_said_so(thread: Thread) -> None:
    row = _c("Northwind will pay the first invoice within 30 days", source="2")
    verify(thread, [row])
    assert row.quote_found
    assert row.source == "6"
    assert "actually said in message 6" in row.quote_note


def test_only_firm_and_verified_is_usable(thread: Thread) -> None:
    real = _c("we will deliver the schema mapping document by 21 March 2026")
    hedged = _c("We should be able to have the schema mapping done by the 14th",
                source="3", status="hedged")
    invented = _c("we promise the moon")
    verify(thread, [real, hedged, invented])
    assert real.usable
    assert not hedged.usable, "a hedge is not a commitment however real the quote"
    assert not invented.usable, "a firm claim with no evidence is not a commitment"
