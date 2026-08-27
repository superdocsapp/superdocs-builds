"""Tests for freshness_auditor.normalize.

Table-driven, positive AND negative. Every match returned by find_numbers /
find_month_years must satisfy text[start:end] == raw; that invariant is
checked on every case below via `assert_matches_raw`, plus separately
against every real fixture document in fixtures/library and fixtures/drafts.

Note on that invariant: `assert_matches_raw` / the offset sweep at the
bottom of this file assert `text[m.start:m.end] == m.raw`. Because `m.raw`
is itself built as `text[m.start:m.end]` inside normalize.py, that
assertion holds by construction for *any* start/end the implementation
produces — it is not capable of catching a wrong offset, only a wrong
*slicing* of an already-wrong offset (which cannot happen). It is kept
here as a cheap guard against a future refactor that builds `raw`
differently (e.g. by concatenating token text instead of slicing), but it
must not be read as an offset-correctness test. Offset correctness is
covered by tests that assert a literal expected start/end, e.g.
`test_find_numbers_digit_number_offset_does_not_swallow_leading_whitespace`
below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from freshness_auditor.normalize import (
    MonthYearMatch,
    NumberMatch,
    find_month_years,
    find_numbers,
    values_equivalent,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def assert_matches_raw(text: str, matches) -> None:
    for m in matches:
        assert text[m.start:m.end] == m.raw, (text, m)


# --- find_numbers: surface-form table from the brief -----------------------

# (text, expected_value, expected_hedge, expected_scale)
NUMBER_TABLE = [
    ("1200", 1200.0, None, None),
    ("1,200", 1200.0, None, None),
    ("1 200", 1200.0, None, None),
    ("1.2k", 1200.0, None, "k"),
    ("1.2K", 1200.0, None, "k"),
    ("1.2 thousand", 1200.0, None, "thousand"),
    ("4.1 million", 4100000.0, None, "million"),
    ("4.1m", 4100000.0, None, "m"),
    ("4.1M", 4100000.0, None, "m"),
    ("twelve hundred", 1200.0, None, None),
    ("fourteen", 14.0, None, None),
    ("seventeen", 17.0, None, None),
    ("over 1,200", 1200.0, "over", None),
    ("more than 1200", 1200.0, "more than", None),
    ("~1,200", 1200.0, "~", None),
    ("approximately 1,200", 1200.0, "approximately", None),
    ("nearly 1,200", 1200.0, "nearly", None),
    ("3.2", 3.2, None, None),
    ("17%", 17.0, None, None),
]


@pytest.mark.parametrize("text,value,hedge,scale", NUMBER_TABLE)
def test_find_numbers_surface_forms(text, value, hedge, scale):
    matches = find_numbers(text)
    assert len(matches) == 1, matches
    m = matches[0]
    assert m.value == pytest.approx(value)
    assert m.hedge == hedge
    assert m.scale == scale
    assert_matches_raw(text, matches)


# --- find_numbers: additional spelled-out compositions ----------------------

WORD_NUMBER_TABLE = [
    ("zero", 0.0),
    ("twenty", 20.0),
    ("thirty", 30.0),
    ("ninety", 90.0),
    ("thirty five", 35.0),
    ("three thousand", 3000.0),
]


@pytest.mark.parametrize("text,value", WORD_NUMBER_TABLE)
def test_find_numbers_word_compositions(text, value):
    matches = find_numbers(text)
    assert len(matches) == 1, matches
    assert matches[0].value == pytest.approx(value)
    assert_matches_raw(text, matches)


def test_find_numbers_hedge_attaches_to_spelled_out_number():
    matches = find_numbers("over twelve hundred people")
    assert len(matches) == 1
    m = matches[0]
    assert m.value == 1200.0
    assert m.hedge == "over"
    assert m.raw == "over twelve hundred"


def test_find_numbers_word_order_of_hedge_and_scale_do_not_conflate():
    # "over" is a hedge word, but must not be mistaken for one when nothing
    # numeric follows it.
    matches = find_numbers("the ball sailed over the fence")
    assert matches == []


def test_find_numbers_hedge_word_far_from_number_does_not_attach():
    # "over" appears early in the sentence, well before the actual number —
    # a broken hedge rule (e.g. "attach the nearest hedge word anywhere
    # earlier in the sentence" instead of "immediately adjacent") would
    # wrongly attach it to "20" here. Unlike the fenceless-"over" test
    # above (which has no digits/number-words at all and would pass even
    # if hedge-adjacency were entirely broken), this text DOES contain a
    # real number, so a broken adjacency rule has something to wrongly
    # attach to and this test can actually fail.
    text = "over the years, our team has delivered work in 20 countries"
    matches = find_numbers(text)
    assert len(matches) == 1
    m = matches[0]
    assert m.raw == "20"
    assert m.value == 20.0
    assert m.hedge is None
    assert_matches_raw(text, matches)


# --- find_numbers: adjacent number-words that do NOT compose ---------------


def test_find_numbers_does_not_combine_unrelated_adjacent_number_words():
    # "twelve fourteen" is not valid English number composition (unlike
    # "twelve hundred" or "thirty five") — each word must surface as its
    # own separate match rather than being silently summed/concatenated.
    text = "twelve fourteen"
    matches = find_numbers(text)
    assert [(m.raw, m.value) for m in matches] == [("twelve", 12.0), ("fourteen", 14.0)]
    assert_matches_raw(text, matches)


def test_find_numbers_bare_magnitude_word_is_not_a_number():
    # "hundred"/"thousand" alone (nothing before them) is not matched —
    # matching it would require guessing whether it means "a hundred" or
    # something else.
    assert find_numbers("a hundred people attended") == []
    assert find_numbers("thousand of birds") == []


# --- find_numbers: ISO 9001 is reported as a genuine number match ----------


def test_find_numbers_reports_digits_inside_iso_standard_name():
    # "ISO 9001" genuinely contains the number 9001. This layer's job is to
    # report what it finds with accurate offsets; the subject-proximity
    # rule that prevents "ISO 9001" from being mistaken for a headcount
    # figure lives in detect.py (a separate, later task), not here. See the
    # module docstring / task report for more on this boundary.
    matches = find_numbers("certified under ISO 9001 standards")
    assert len(matches) == 1
    assert matches[0].raw == "9001"
    assert matches[0].value == 9001.0


# --- find_numbers: negative cases (must yield NO number match) -------------

NO_NUMBER_STRINGS = [
    "Our mission drives everything we do.",
    "We value integrity, trust, and community.",
    "The quick brown fox jumps over the lazy dog.",
    "Twentysomething professionals joined the programme.",
    "The thirteenth floor was renovated last year.",
]


@pytest.mark.parametrize("text", NO_NUMBER_STRINGS)
def test_find_numbers_negative_cases(text):
    assert find_numbers(text) == []


# --- find_numbers: word order / offsets -------------------------------------


def test_find_numbers_offsets_are_into_the_original_text():
    text = "Our teams operate in fourteen nations, delivering programs."
    matches = find_numbers(text)
    assert len(matches) == 1
    m = matches[0]
    assert text[m.start:m.end] == "fourteen"
    assert m.value == 14.0


def test_find_numbers_digit_number_offset_does_not_swallow_leading_whitespace():
    # Regression test for a real bug found by inspection (not by the
    # text[start:end] == raw invariant sweep elsewhere in this file — that
    # invariant is tautological by construction and cannot fail; see the
    # report). The bug: an optional hedge group followed by a bare `\s*`
    # let the digit-number match start one character early, swallowing the
    # preceding space, whenever NO hedge word was present. This text has no
    # hedge at all, so it exercises exactly the path that broke.
    text = "we employ 1200 staff"
    matches = find_numbers(text)
    assert len(matches) == 1
    m = matches[0]
    assert m.raw == "1200"
    assert m.start == 10
    assert m.end == 14
    assert m.hedge is None
    assert m.value == 1200.0


# --- find_month_years: surface-form table from the brief -------------------

MONTH_YEAR_TABLE = [
    ("March 2023", 2023, 3),
    ("Mar 2023", 2023, 3),
    ("03/2023", 2023, 3),
    ("3/2023", 2023, 3),
    ("2023-03", 2023, 3),
    ("March '23", 2023, 3),
]


@pytest.mark.parametrize("text,year,month", MONTH_YEAR_TABLE)
def test_find_month_years_surface_forms(text, year, month):
    matches = find_month_years(text)
    assert len(matches) == 1, matches
    m = matches[0]
    assert m.year == year
    assert m.month == month
    assert_matches_raw(text, matches)


def test_find_month_years_within_a_sentence():
    text = "renewed approximately in 03/2023, per the registry."
    matches = find_month_years(text)
    assert len(matches) == 1
    m = matches[0]
    assert (m.year, m.month) == (2023, 3)
    assert m.raw == "03/2023"
    assert_matches_raw(text, matches)


# --- find_month_years: reference numbers must NOT be misread as dates ------
#
# Proposal documents are full of reference/contract/RFP numbers shaped like
# `NN/MM/YYYY/NNN`. Before the fix, the `MM/YYYY` regex matched the middle
# two components of such a number as if it were a real month-year — a live
# false-positive source feeding a tool that rewrites text in someone's bid
# document. `over-matching is worse than missing` (task-2-brief.md).


NO_MONTH_YEAR_REFERENCE_NUMBER_STRINGS = [
    "RFP 12/2023/045",
    "12/2023/45",
    "Contract 03/2023/12",
]


@pytest.mark.parametrize("text", NO_MONTH_YEAR_REFERENCE_NUMBER_STRINGS)
def test_find_month_years_does_not_match_reference_numbers(text):
    assert find_month_years(text) == []


def test_find_month_years_still_matches_genuine_slash_form_in_prose():
    # The fix above must not collateral-damage the real thing it exists to
    # recognise: an MM/YYYY mention with no trailing reference-number
    # continuation.
    text = "renewed in 03/2023"
    matches = find_month_years(text)
    assert len(matches) == 1
    m = matches[0]
    assert (m.year, m.month) == (2023, 3)
    assert m.raw == "03/2023"
    assert_matches_raw(text, matches)


def test_find_month_years_does_not_misread_full_iso_date_as_month_year():
    # Same continuation-ambiguity problem, different form: "2023-03-15" is a
    # full ISO calendar date (year-month-DAY), not a month-year. Before the
    # fix, the YYYY-MM regex greedily matched "2023-03" out of it and
    # silently dropped the "-15", misreading a full date as "March 2023".
    assert find_month_years("2023-03-15") == []


def test_find_month_years_still_matches_genuine_iso_form():
    text = "2023-03"
    matches = find_month_years(text)
    assert len(matches) == 1
    m = matches[0]
    assert (m.year, m.month) == (2023, 3)
    assert_matches_raw(text, matches)


# --- find_month_years: reference numbers, mirror case (LEADING run) --------
#
# Fix round 1 closed the *trailing* continuation ("RFP 12/2023/045" and
# "2023-03-15" above). It disclosed, but did not close, the mirror-image
# *leading* continuation: a reference/contract number that happens to END
# in something shaped like MM/YYYY or YYYY-MM, e.g. a real "Contract No.
# 045/03/2023" — the date-shaped tail was still misread as March 2023,
# because nothing follows it for the trailing lookahead to catch. Same
# continuation-ambiguity reasoning as Finding 1, applied to the other side.

NO_MONTH_YEAR_LEADING_REFERENCE_NUMBER_STRINGS = [
    "Contract No. 045/03/2023",
    "our ref 99/03/2023",
    "Ref 12-2023-03",
]


@pytest.mark.parametrize("text", NO_MONTH_YEAR_LEADING_REFERENCE_NUMBER_STRINGS)
def test_find_month_years_does_not_match_reference_numbers_with_leading_run(text):
    assert find_month_years(text) == []


def test_find_month_years_still_matches_slash_form_at_start_of_string():
    # A genuine month-year at the very start of a string has nothing before
    # it to trigger the new leading guard — must still match. This is the
    # boundary case for the leading lookbehind: no preceding characters at
    # all, as opposed to a preceding space/word (already covered above).
    text = "03/2023 was the renewal date"
    matches = find_month_years(text)
    assert len(matches) == 1
    m = matches[0]
    assert (m.year, m.month) == (2023, 3)
    assert m.raw == "03/2023"
    assert_matches_raw(text, matches)


# --- find_month_years: deliberately out-of-scope vague forms ---------------

VAGUE_PERIOD_STRINGS = [
    "renewed in early 2023",
    "renewed in the spring of 2023",
    "renewed in Q1 2023",
]


@pytest.mark.parametrize("text", VAGUE_PERIOD_STRINGS)
def test_find_month_years_does_not_match_vague_periods(text):
    assert find_month_years(text) == []


# --- values_equivalent -------------------------------------------------------


def test_values_equivalent_exact_match():
    assert values_equivalent(1200.0, 1200.0, "integer") is True


def test_values_equivalent_different_values_not_equal():
    assert values_equivalent(14.0, 17.0, "integer") is False


def test_values_equivalent_decimal_with_unit_scale():
    # a "million people" fact stated as "4.1" in one document and
    # "4,100,000" in another (i.e. find_numbers would report 4.1 and
    # 4100000.0) must compare equal for a decimal-kind fact.
    assert values_equivalent(4.1, 4100000.0, "decimal") is True
    assert values_equivalent(3.2, 3200000.0, "decimal") is True


def test_values_equivalent_currency_with_unit_scale():
    assert values_equivalent(2.5, 2500000.0, "currency") is True


def test_values_equivalent_scale_guessing_does_not_apply_to_integer_kind():
    # integer facts in this ledger (headcount, country_count) carry no
    # "per-thousand" unit, so a thousand-fold coincidence must NOT be
    # treated as the same value — that would be a false positive waiting
    # to happen.
    assert values_equivalent(1.2, 1200.0, "integer") is False


def test_values_equivalent_scale_guessing_does_not_apply_to_percentage_kind():
    assert values_equivalent(17.0, 17000.0, "percentage") is False


def test_values_equivalent_text_kind_requires_exact_numeric_equality():
    assert values_equivalent(2023.0, 2023.0, "text") is True
    assert values_equivalent(2023.0, 2026.0, "text") is False


# --- invariant sweep across the real fixture documents ----------------------


def test_raw_matches_offsets_across_all_fixture_documents():
    html_files = list((FIXTURES_DIR / "library").glob("*.html")) + list(
        (FIXTURES_DIR / "drafts").glob("*.html")
    )
    assert html_files, "expected fixture HTML files to exist"
    for path in html_files:
        text = path.read_text(encoding="utf-8")
        assert_matches_raw(text, find_numbers(text))
        assert_matches_raw(text, find_month_years(text))


# --- dataclass shape sanity --------------------------------------------------


def test_number_match_is_frozen_dataclass():
    m = NumberMatch(raw="1200", value=1200.0, start=0, end=4, hedge=None, scale=None)
    with pytest.raises(Exception):
        m.value = 5.0  # type: ignore[misc]


def test_month_year_match_is_frozen_dataclass():
    m = MonthYearMatch(raw="March 2023", year=2023, month=3, start=0, end=10)
    with pytest.raises(Exception):
        m.year = 1999  # type: ignore[misc]
