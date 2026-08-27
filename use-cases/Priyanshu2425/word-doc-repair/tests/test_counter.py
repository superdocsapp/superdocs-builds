"""Tests for `docrepair.counter` — the styling counter's pure logic.

`docs/PRD-SET-IT-YOUR-WAY.md` §3 amends B20 to B20′: a styled file is refused
if its word multiset differs from its authorised baseline, and only the
person can move that baseline, and only by supplying the exact text. B27
requires the model never write prose into a recovered document. This file
covers both halves: the baseline arithmetic (`baseline_from`,
`with_supplied`), reading what the person actually supplied
(`supplied_text`), the free pre-flight "no" (`why_refused_before_sending`),
and the post-turn guard (`why_not_acceptable_against`).

Offline throughout: no network, no key. `counter.py` is stdlib-only at
module scope, so nothing here needs one either. `.docx` bytes are built with
`docrepair.docx.write_docx` and the helpers in `tests/fixtures.py` rather
than checked in as binary blobs.
"""

from __future__ import annotations

from collections import Counter

import pytest

from docrepair import counter as c
from docrepair import docx
from docrepair.docx import Block

from tests import fixtures


def _doc(text: str) -> bytes:
    return docx.write_docx([Block("paragraph", text)])


# -- baseline arithmetic ------------------------------------------------------

def test_baseline_from_is_the_rebuilds_own_words():
    rebuild = _doc("One two THREE.")
    assert c.baseline_from(rebuild) == Counter({"one": 1, "two": 1, "three": 1})


def test_with_supplied_adds_the_words_the_person_typed():
    base = Counter({"one": 1})
    assert c.with_supplied(base, added="two three") == Counter(
        {"one": 1, "two": 1, "three": 1})


def test_with_supplied_removes_the_words_the_person_asked_to_remove():
    base = Counter({"one": 1, "two": 1, "three": 1})
    assert c.with_supplied(base, removed="two") == Counter({"one": 1, "three": 1})


def test_with_supplied_can_add_and_remove_in_the_same_turn():
    base = Counter({"one": 1, "two": 1})
    assert c.with_supplied(base, added="three", removed="two") == Counter(
        {"one": 1, "three": 1})


def test_removing_more_than_exists_does_not_go_negative():
    base = Counter({"one": 1})
    result = c.with_supplied(base, removed="one one one")
    assert result == Counter()
    assert all(v >= 0 for v in result.values())


def test_with_supplied_leaves_the_original_counter_untouched():
    base = Counter({"one": 1})
    c.with_supplied(base, added="two", removed="one")
    assert base == Counter({"one": 1}), "base must not be mutated in place"


# -- supplied_text -------------------------------------------------------------

def test_supplied_text_reads_a_straight_double_quoted_run():
    message = 'replace the last line with "and the second crane is approved."'
    assert c.supplied_text(message) == "and the second crane is approved."


def test_supplied_text_reads_a_straight_single_quoted_run():
    message = "replace the title with 'Final Report'"
    assert c.supplied_text(message) == "Final Report"


def test_supplied_text_reads_a_typographic_double_quoted_run():
    message = "replace the title with “Final Report”"
    assert c.supplied_text(message) == "Final Report"


def test_supplied_text_reads_a_typographic_single_quoted_run():
    message = "replace the title with ‘Final Report’"
    assert c.supplied_text(message) == "Final Report"


def test_supplied_text_returns_the_longest_quoted_run_when_several_appear():
    message = 'either "short" or "the much longer replacement sentence"'
    assert c.supplied_text(message) == "the much longer replacement sentence"


def test_supplied_text_is_empty_when_nothing_is_quoted():
    assert c.supplied_text("make the headings smaller") == ""


# -- a contraction must never be mistaken for the person supplying words ------
#
# `supplied_text` used to treat any pair of straight or typographic single
# quotes as a quoted run, including the apostrophes inside ordinary
# contractions. That was worse than a missed formatting request: `web.py`
# feeds `supplied_text()` into `with_supplied()` to move the authorised
# baseline (B20'), so a stray apostrophe did not just skip the prose check —
# it authorised a garbage span of the person's own instruction as permitted
# content, and the post-turn guard would then accept a returned file
# containing those words. Both defences (B27's pre-flight refusal and B20's
# baseline) failed together, in the same step, for the same reason.

CONTRACTION_PROSE_REQUESTS = [
    "Can't you finish that last paragraph? It doesn't matter.",
    "I don't like it, can you write a closing sentence? It's a mess.",
    "Don't summarise it, but it's fine if you can't.",
]


@pytest.mark.parametrize("message", CONTRACTION_PROSE_REQUESTS)
def test_a_contraction_is_never_read_as_a_quoted_supply(message):
    assert c.supplied_text(message) == ""


@pytest.mark.parametrize("message", CONTRACTION_PROSE_REQUESTS)
def test_a_contraction_is_still_never_read_as_a_quoted_supply(message):
    """The counter refuses nothing on content now, so these no longer get
    turned away — but the extraction bug they were written for still
    matters. A contraction misread as a quote would move the authorised
    baseline, and the baseline is what `describe_change` reports against, so
    a misread would go on quietly excusing words nobody supplied."""
    assert c.supplied_text(message) == ""
    assert c.why_refused_before_sending(
        message, turns_left=5, allowance_known=True, allowance_remaining=5) == ""


def test_a_contraction_in_a_formatting_request_is_not_read_as_a_supply():
    message = "don't make the headings bigger"
    assert c.supplied_text(message) == ""
    assert c.why_refused_before_sending(
        message, turns_left=5, allowance_known=True, allowance_remaining=5
    ) == ""


def test_a_genuine_single_quoted_supply_is_still_read_correctly_around_a_contraction():
    message = "it's fine, use 'and the crane is approved' as the last line"
    assert c.supplied_text(message) == "and the crane is approved"
    assert c.why_refused_before_sending(
        message, turns_left=5, allowance_known=True, allowance_remaining=5
    ) == ""


def test_a_genuine_double_quoted_supply_is_unaffected_by_the_apostrophe_fix():
    message = 'replace the last line with "and the second crane is approved."'
    assert c.supplied_text(message) == "and the second crane is approved."
    assert c.why_refused_before_sending(
        message, turns_left=5, allowance_known=True, allowance_remaining=5
    ) == ""


# -- pre-flight: formatting must always pass -----------------------------------

FORMATTING_REQUESTS = [
    "make the headings smaller",
    "tighten the spacing",
    "hairline table rules",
    "let the chart run full width",
    "put the last line in italics",
    "wider margins",
    "set the caption in grey",
    "move the picture above the table",
    "make the title bold",
    "rewrite the heading style",
]


@pytest.mark.parametrize("message", FORMATTING_REQUESTS)
def test_ordinary_formatting_requests_are_never_refused(message):
    assert c.why_refused_before_sending(
        message, turns_left=5, allowance_known=True, allowance_remaining=5
    ) == ""


# -- pre-flight: prose must always be refused ----------------------------------

PROSE_REQUESTS = [
    "Can you finish that last paragraph? It stops mid-sentence.",
    "please summarise the report",
    "summarize the findings for me",
    "draft a closing paragraph",
    "write the missing section",
    "compose a disclaimer",
    "reword the summary",
    "rephrase the summary",
    "rewrite the summary",
    "expand on the introduction",
    "elaborate on the findings",
    "fill in the gap",
    "fill the gap at the end",
    "make up a plausible ending",
    "invent a signature block",
    "generate a subtotal row",
    "add a paragraph about the outcome",
    "add a sentence to close it out",
    "add a section on next steps",
    "continue the story from where it stops",
]


@pytest.mark.parametrize("message", PROSE_REQUESTS)
def test_the_counter_refuses_nothing_for_what_it_was_asked(message):
    """Owner's decision, 2026-08-26. At the counter the person is driving,
    and what they ask SuperDocs for is theirs to ask -- including asking it
    to write. The automatic pass is untouched and still refuses, because
    that is where the model acts with nobody watching.

    These are the exact messages that used to be turned away. Kept, inverted,
    rather than deleted: they are the record of what was decided, and if the
    refusal ever comes back they are the tests that will say so."""
    assert c.why_refused_before_sending(
        message, turns_left=5, allowance_known=True, allowance_remaining=5) == ""


def test_a_quoted_supply_is_never_refused_even_if_the_sentence_around_it_sounds_like_prose():
    message = 'replace the last line with "and the second crane is approved."'
    assert c.why_refused_before_sending(
        message, turns_left=5, allowance_known=True, allowance_remaining=5
    ) == ""


# -- pre-flight: the turn cap and the allowance, cheapest and most certain ----

def test_the_turn_cap_refuses_before_anything_is_sent():
    reason = c.why_refused_before_sending(
        "make the title bold", turns_left=0,
        allowance_known=True, allowance_remaining=5)
    assert reason != ""


def test_a_zero_allowance_refuses():
    reason = c.why_refused_before_sending(
        "make the title bold", turns_left=5,
        allowance_known=True, allowance_remaining=0)
    assert reason != ""


def test_an_unknown_allowance_does_not_refuse():
    """B22: an unreadable balance proceeds — it is never reported as zero."""
    reason = c.why_refused_before_sending(
        "make the title bold", turns_left=5,
        allowance_known=False, allowance_remaining=0)
    assert reason == ""


def test_the_turn_cap_is_checked_before_the_allowance():
    reason = c.why_refused_before_sending(
        "make the title bold", turns_left=0,
        allowance_known=True, allowance_remaining=0)
    assert "tenth" in reason


# -- the guard: what came back --------------------------------------------------

def test_why_not_acceptable_against_accepts_a_faithful_restyle():
    sent = _doc("one two three")
    authorised = c.baseline_from(sent)

    assert c.why_not_acceptable_against(sent, sent, authorised) == ""


def test_why_not_acceptable_against_refuses_lost_pictures():
    sent = fixtures.illustrated()
    authorised = c.baseline_from(sent)
    got = docx.write_docx([Block("paragraph", "text only, no picture")])

    reason = c.why_not_acceptable_against(sent, got, authorised)
    assert "fewer pictures" in reason


def test_why_not_acceptable_against_refuses_invented_words():
    sent = _doc("one two three")
    authorised = c.baseline_from(sent)
    got = _doc("one two three and an invented signature block")

    reason = c.why_not_acceptable_against(sent, got, authorised)
    assert "wording changed" in reason


def test_why_not_acceptable_against_accepts_words_the_person_supplied():
    sent = _doc("one two three")
    base = c.baseline_from(sent)
    authorised = c.with_supplied(base, added="approved")
    got = _doc("one two three approved")

    assert c.why_not_acceptable_against(sent, got, authorised) == ""


def test_why_not_acceptable_against_still_refuses_words_outside_what_was_supplied():
    sent = _doc("one two three")
    base = c.baseline_from(sent)
    authorised = c.with_supplied(base, added="approved")
    got = _doc("one two three approved and also invented")

    reason = c.why_not_acceptable_against(sent, got, authorised)
    assert "wording changed" in reason


# -- consumer-facing sentences: no jargon, no overclaiming ----------------------

_FORBIDDEN_SUBSTRINGS = (
    "ZIP", "XML", "CRC", "zlib", "central directory", "ParseError",
    "TimeoutError", "Traceback", "stack trace", "NoneType", "utf-8", "b'",
    "0x",
)
_FORBIDDEN_CLAIMS = (
    "fully repaired", "fully restored", "completely repaired",
    "complete repair", "guaranteed", "guarantee", "perfect", "perfectly",
    "100%", "flawless", "as good as new", "everything was recovered",
    "nothing was lost",
)


def _all_consumer_sentences() -> list[str]:
    sentences = [
        c.why_refused_before_sending(
            "make the title bold", turns_left=0,
            allowance_known=True, allowance_remaining=0),
        c.why_refused_before_sending(
            "make the title bold", turns_left=5,
            allowance_known=True, allowance_remaining=0),
        c.why_refused_before_sending(
            "please summarise the report", turns_left=5,
            allowance_known=True, allowance_remaining=5),
    ]
    sent = fixtures.illustrated()
    authorised = c.baseline_from(sent)
    sentences.append(c.why_not_acceptable_against(
        sent, docx.write_docx([Block("paragraph", "no picture")]), authorised))
    sentences.append(c.why_not_acceptable_against(
        _doc("one"), _doc("one two invented"), c.baseline_from(_doc("one"))))
    return [s for s in sentences if s]


def test_consumer_facing_sentences_avoid_engine_vocabulary():
    for sentence in _all_consumer_sentences():
        for banned in _FORBIDDEN_SUBSTRINGS:
            assert banned not in sentence, (banned, sentence)


def test_consumer_facing_sentences_avoid_overclaiming():
    for sentence in _all_consumer_sentences():
        lowered = sentence.lower()
        for claim in _FORBIDDEN_CLAIMS:
            assert claim not in lowered, (claim, sentence)
