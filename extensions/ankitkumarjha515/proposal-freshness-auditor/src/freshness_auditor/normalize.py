"""Surface-form normalization: turn numbers and month-year mentions found in
free text into comparable canonical values.

This module does not know about facts, subjects, or documents — that is the
detection engine's job (`detect.py`, a separate task). It only answers two
questions: "what numbers/month-years appear in this text, with what offsets
and what canonical value?" and "are two canonical values the same?".

Design principle carried through every function here: **a missed match is
recoverable (a human can still spot it), a spurious match is not** — it
becomes a false correction in someone's live bid document. Every regex and
every word-grammar rule below is written to fail closed: when a surface form
is ambiguous, `find_numbers`/`find_month_years` do not guess.

Number-word, scale-word, and month-name tables are module-level data
structures (see the `_ONES` / `_TENS` / `_MAGNITUDES` / `SCALE_MULTIPLIERS` /
`_MONTH_NAMES` dicts below) so that adding a word is a data edit, not a
logic edit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Public data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumberMatch:
    raw: str  # exactly the matched span, i.e. text[start:end]
    value: float  # canonical numeric value, e.g. 1200.0
    start: int  # char offset in the text passed in
    end: int
    hedge: str | None  # "over" | "more than" | "approximately" | "~" | "nearly" | None
    scale: str | None  # "k" | "m" | "thousand" | "million" | "billion" | None


@dataclass(frozen=True)
class MonthYearMatch:
    raw: str  # exactly the matched span, i.e. text[start:end]
    year: int
    month: int  # 1-12
    start: int
    end: int


# ---------------------------------------------------------------------------
# Module-level data tables — extend these, never the logic below, to teach
# the normalizer a new word.
# ---------------------------------------------------------------------------

# Spelled-out integers 0-20 (per the brief's minimum bar). "twenty" is kept
# here rather than in _TENS because, unlike thirty..ninety, it does not take
# a trailing-ones compound in ordinary English ("twenty two" is written as
# "twenty-two"/"22", not composed the same way "thirty five" is).
_ONES: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}

# Tens words that take an optional trailing-ones compound, e.g. "thirty five".
_TENS: dict[str, int] = {
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

# Magnitude words. "hundred" multiplies the group accumulated so far;
# thousand/million/billion close out a group and scale it.
_MAGNITUDES: dict[str, int] = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}

_BASE_WORDS: dict[str, int] = {**_ONES, **_TENS}
_ALL_NUMBER_WORDS: set[str] = set(_BASE_WORDS) | set(_MAGNITUDES)

# Scale abbreviations/words recognised attached to (or following) a digit
# number, e.g. "1.2k", "4.1 million". Deliberately does not include a bare
# "b" suffix — the public contract's `scale` type only allows the literal
# "billion", not "b", so there is no attached-letter form for it.
SCALE_MULTIPLIERS: dict[str, float] = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "million": 1_000_000.0,
    "billion": 1_000_000_000.0,
}

# Hedge phrases that soften a stated value. Order does not matter for
# correctness (regex alternation + \b/backtracking disambiguates), but is
# kept roughly longest-first for readability.
_HEDGE_ALTERNATION = r"more\ than|approximately|nearly|over|~"

_MONTH_NAMES: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# ---------------------------------------------------------------------------
# Compiled regexes (built from the tables above)
# ---------------------------------------------------------------------------

_WORD_ALT = "|".join(
    re.escape(w) for w in sorted(_ALL_NUMBER_WORDS, key=len, reverse=True)
)
_MONTH_ALT = "|".join(
    re.escape(w) for w in sorted(_MONTH_NAMES, key=len, reverse=True)
)

# Digit-form numbers: optional hedge, an integer (plain or thousands-grouped
# by comma or space), optional decimal fraction, optional percent/scale
# suffix. The hedge + its trailing whitespace are bundled in ONE optional
# group so that at a position where the hedge does not match, nothing is
# consumed — this is what stops the regex from accidentally starting a
# match one character early on bare whitespace.
_DIGIT_NUMBER_RE = re.compile(
    r"""
    (?:(?P<hedge>""" + _HEDGE_ALTERNATION + r""")\s*)?
    (?P<int>\d{1,3}(?:[, ]\d{3})+|\d+)
    (?P<frac>\.\d+)?
    (?:
        (?P<pct>%)
      | (?P<scale_letter>[kKmM])\b
      | \s+(?P<scale_word>thousand|million|billion)\b
    )?
    """,
    re.VERBOSE | re.IGNORECASE,
)

# A maximal run of consecutive number-words (e.g. "twelve hundred", but also
# "twelve fourteen" if that ever occurs in text — grammar validity is
# checked afterwards in Python, not here). Optional leading hedge, bundled
# the same way as the digit regex.
_WORD_NUMBER_OUTER_RE = re.compile(
    r"(?:(?P<hedge>" + _HEDGE_ALTERNATION + r")\s*)?"
    r"(?P<words>\b(?:" + _WORD_ALT + r")(?:[\s-]+(?:" + _WORD_ALT + r"))*\b)",
    re.IGNORECASE,
)

_WORD_TOKEN_RE = re.compile(r"\b(?:" + _WORD_ALT + r")\b", re.IGNORECASE)

# Month-year forms. Deliberately does NOT attempt vague periods like
# "early 2023", "spring of 2023", "Q1 2023" — see module docstring and the
# brief: those are not equivalent to one specific month, and guessing which
# month they mean is exactly the over-matching this module refuses to do.
#
# The numeric forms (`MM/YYYY`, `YYYY-MM`) each carry BOTH a trailing and a
# leading guard against being read out of a longer digit/separator run —
# `(?!/\d)` / `(?<!\d/)` for the slash form, `(?!-\d)` / `(?<!\d-)` for the
# ISO form. Without these, a reference/contract/RFP number shaped like
# `NN/MM/YYYY/NNN` (or just `NN/MM/YYYY`) reads its middle (or trailing)
# two components as a valid month-year, and an ISO calendar date
# `YYYY-MM-DD` reads its first two components the same way:
#   - trailing:  "RFP 12/2023/045"        -> would misread as "December 2023"
#   - trailing:  "2023-03-15" (full date) -> would misread as "March 2023"
#   - leading:   "Contract No. 045/03/2023" -> would misread as "March 2023"
#   - leading:   "Ref 12-2023-03"           -> would misread as "March 2023"
# Proposal documents are full of both reference-number and full-date shapes,
# so this is a live false-positive source, not a hypothetical one. Each
# guard only blocks a continuation that is itself digit+separator — a
# genuine month-year with a space, punctuation, or nothing on either side
# (`"renewed in 03/2023"`, `"03/2023 was the renewal date"`, bare
# `"2023-03"`) still matches, because in-prose context around a real date
# is not itself another digit run glued on by a slash or dash.
_MONTH_YEAR_RE = re.compile(
    r"""
    (?:
        \b(?P<month_name>""" + _MONTH_ALT + r""")\.?
        (?:
            \s+(?P<year4>\d{4})
          | \s*['’](?P<year2>\d{2})
        )
        \b
    )
    |
    (?:
        (?<!\d/)\b(?P<mm>0?[1-9]|1[0-2])/(?P<yyyy_slash>\d{4})(?!/\d)\b
    )
    |
    (?:
        (?<!\d-)\b(?P<yyyy_iso>\d{4})-(?P<mm_iso>0[1-9]|1[0-2])(?!-\d)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_hedge(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().lower())


def _build_digit_match(text: str, m: re.Match) -> NumberMatch:
    raw_int = m.group("int").replace(",", "").replace(" ", "")
    frac = m.group("frac") or ""
    value = float(raw_int + frac)

    hedge_raw = m.group("hedge")
    hedge = _canonical_hedge(hedge_raw) if hedge_raw else None

    scale_letter = m.group("scale_letter")
    scale_word = m.group("scale_word")
    if scale_letter:
        scale = scale_letter.lower()
        value = round(value * SCALE_MULTIPLIERS[scale], 6)
    elif scale_word:
        scale = scale_word.lower()
        value = round(value * SCALE_MULTIPLIERS[scale], 6)
    else:
        scale = None

    return NumberMatch(
        raw=text[m.start():m.end()],
        value=value,
        start=m.start(),
        end=m.end(),
        hedge=hedge,
        scale=scale,
    )


def _consume_one_number(tokens: list[str], start: int) -> tuple[float, int] | None:
    """Greedily consume the longest run beginning at `start` that forms a
    grammatically valid English cardinal number, per a simplified grammar:

        group   := TENS [ONES<10]        (e.g. "thirty five" -> 35)
                 | ONES_OR_TEEN_OR_TWENTY (e.g. "fourteen" -> 14, "zero" -> 0)
        segment := group ["hundred"]      (e.g. "twelve hundred" -> 1200)
        number  := segment (MAGNITUDE segment?)*   (MAGNITUDE = thousand/
                                                      million/billion)

    Returns `None` if `tokens[start]` cannot begin a number (e.g. a bare
    "hundred"/"thousand" with nothing before it — "hundred" alone is not
    treated as 100, since that would require guessing whether it means "a
    hundred" or is part of some other phrase).

    This stops rather than guesses at anything outside the grammar — e.g.
    two bare ones/teens back to back ("twelve fourteen") do NOT combine into
    one number; each is reported as its own separate match by the caller.
    """
    if tokens[start] not in _BASE_WORDS:
        return None

    i = start
    n = len(tokens)
    total = 0
    current = 0
    have_group = False  # an unscaled group has been accumulated since the last magnitude

    while i < n:
        tok = tokens[i]
        if tok in _TENS:
            if have_group:
                break
            current += _TENS[tok]
            have_group = True
            i += 1
            if i < n and tokens[i] in _ONES and _ONES[tokens[i]] < 10:
                current += _ONES[tokens[i]]
                i += 1
        elif tok in _ONES:
            if have_group:
                break
            current += _ONES[tok]
            have_group = True
            i += 1
        elif tok == "hundred":
            current = (current if have_group else 1) * 100
            have_group = True
            i += 1
        elif tok in _MAGNITUDES:  # thousand / million / billion
            base = current if have_group else 1
            total += base * _MAGNITUDES[tok]
            current = 0
            have_group = False
            i += 1
        else:
            break

    return float(total + current), i - start


def _iter_number_word_groups(tokens: list[str]):
    """Yield (value, token_start_idx, token_end_idx) for every grammatically
    valid number embedded in `tokens`, left to right. A token that cannot
    start a group (a stray magnitude word) is skipped by itself."""
    i = 0
    n = len(tokens)
    while i < n:
        result = _consume_one_number(tokens, i)
        if result is None:
            i += 1
            continue
        value, count = result
        yield value, i, i + count
        i += count


def _build_word_matches(text: str, m: re.Match) -> list[NumberMatch]:
    words_start = m.start("words")
    words_text = m.group("words")
    token_spans = [
        (t.group(0).lower(), words_start + t.start(), words_start + t.end())
        for t in _WORD_TOKEN_RE.finditer(words_text)
    ]
    tokens = [t[0] for t in token_spans]

    hedge_raw = m.group("hedge")
    canonical_hedge = _canonical_hedge(hedge_raw) if hedge_raw else None
    hedge_start = m.start("hedge") if hedge_raw else None

    results: list[NumberMatch] = []
    for idx, (value, tok_start, tok_end) in enumerate(_iter_number_word_groups(tokens)):
        span_start = token_spans[tok_start][1]
        span_end = token_spans[tok_end - 1][2]
        if idx == 0 and hedge_raw:
            start = hedge_start
            hedge = canonical_hedge
        else:
            start = span_start
            hedge = None
        results.append(
            NumberMatch(
                raw=text[start:span_end],
                value=value,
                start=start,
                end=span_end,
                hedge=hedge,
                scale=None,  # fully spelled-out numbers carry no separate scale marker
            )
        )
    return results


def _pivot_two_digit_year(yy: int) -> int:
    """2-digit year pivot, following the common strftime %y convention:
    00-68 -> 2000-2068, 69-99 -> 1969-1999."""
    return 2000 + yy if yy <= 68 else 1900 + yy


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_numbers(text: str) -> list[NumberMatch]:
    """Find every number in `text`: digit forms (with thousands grouping,
    decimals, percent, scale letters/words, and hedges) and spelled-out
    cardinal words (zero..twenty, thirty..ninety, hundred/thousand/million/
    billion composition).

    Returns matches sorted by start offset. `text[m.start:m.end] == m.raw`
    holds for every match. Overlapping candidate matches are resolved by
    keeping the earlier one and discarding anything that would overlap it
    (this should not normally trigger — digit and word-number matches use
    disjoint character classes — but is kept as a defensive invariant).
    """
    matches: list[NumberMatch] = []
    for m in _DIGIT_NUMBER_RE.finditer(text):
        matches.append(_build_digit_match(text, m))
    for run in _WORD_NUMBER_OUTER_RE.finditer(text):
        matches.extend(_build_word_matches(text, run))

    matches.sort(key=lambda nm: (nm.start, nm.end))
    deduped: list[NumberMatch] = []
    last_end = -1
    for nm in matches:
        if nm.start < last_end:
            continue
        deduped.append(nm)
        last_end = nm.end
    return deduped


def find_month_years(text: str) -> list[MonthYearMatch]:
    """Find month-year mentions: "March 2023", "Mar 2023", "March '23",
    "03/2023", "3/2023", "2023-03". Vague periods ("early 2023", "spring of
    2023", "Q1 2023") are deliberately not matched — see module docstring."""
    matches: list[MonthYearMatch] = []
    for m in _MONTH_YEAR_RE.finditer(text):
        if m.group("month_name"):
            month = _MONTH_NAMES[m.group("month_name").lower()]
            if m.group("year4"):
                year = int(m.group("year4"))
            else:
                year = _pivot_two_digit_year(int(m.group("year2")))
        elif m.group("mm"):
            month = int(m.group("mm"))
            year = int(m.group("yyyy_slash"))
        else:
            year = int(m.group("yyyy_iso"))
            month = int(m.group("mm_iso"))
        matches.append(
            MonthYearMatch(
                raw=text[m.start():m.end()],
                year=year,
                month=month,
                start=m.start(),
                end=m.end(),
            )
        )
    return matches


# Ratios accounted for when comparing a numeric fact stated in raw units
# against the same fact stated in thousands/millions/billions of that unit
# (e.g. a "million people" fact written once as "4.1" and once as
# "4,100,000"). Mirrors the scale multipliers `find_numbers` recognises.
_EQUIVALENCE_SCALE_FACTORS = (1_000.0, 1_000_000.0, 1_000_000_000.0)

# Kinds for which unit-scale equivalence is considered. Restricted to kinds
# whose fixtures actually carry a "per-thousand/million" unit (decimal,
# currency) — integer/percentage/year/text facts in this ledger have no such
# unit, so guessing a scale for them would only invite false positives.
_SCALE_AWARE_KINDS = {"decimal", "currency"}


def values_equivalent(a: float, b: float, kind: str) -> bool:
    """True when `a` and `b` represent the same fact value.

    Rule: two values are equivalent if they are numerically equal (within
    floating-point tolerance), OR — for `kind in {"decimal", "currency"}`
    only — if one equals the other scaled by 1,000 / 1,000,000 / 1,000,000,000.
    That second clause exists because a fact whose unit is e.g. "million
    people" is legitimately written both as "4.1" and as "4,100,000" in
    different documents; `find_numbers` would report 4.1 and 4100000.0 for
    those two spans respectively, and without this rule they would look
    like different values. It does not apply to integer/percentage/year/
    text kinds, where the current fixtures carry no such unit and a
    thousandfold "match" would almost always be a coincidence, not the same
    fact restated.
    """
    if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
        return True
    if kind in _SCALE_AWARE_KINDS:
        for factor in _EQUIVALENCE_SCALE_FACTORS:
            if math.isclose(a * factor, b, rel_tol=1e-6, abs_tol=1e-6):
                return True
            if math.isclose(b * factor, a, rel_tol=1e-6, abs_tol=1e-6):
                return True
    return False
