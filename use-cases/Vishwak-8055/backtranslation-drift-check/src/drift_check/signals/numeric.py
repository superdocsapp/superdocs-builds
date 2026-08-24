"""Numeric, date, percentage, and unit drift detection.

Strategy: scan both texts for numeric "tokens" in a fixed priority order
(dates, then percentages, then currency, then number+unit, then bare
numbers), consuming matched spans so a percentage is never also counted as a
bare number. Tokens of the same kind are then compared *in order of
appearance* between source and back-translation. This is a positional
heuristic, not true alignment — see LIMITATIONS.md #3 — but it is accurate
for the common case this system targets: short, single-topic sections where
numbers appear in the same order in a faithful translation.

Severity policy (see DECISIONS.md #6): a numeric change is escalated to
CRITICAL when it sits next to a safety/dosage/regulatory keyword (mg, mL,
°C/°F, "regulatory", "authority", "safety", "law") or is a date; general
commercial numbers (fees, ordinary deadlines) default to HIGH, since any
numeric change to an obligation is still a materially different document.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from drift_check.models import DriftCategory, Severity
from drift_check.signals import Signal

Kind = Literal["date", "percentage", "currency", "unit_quantity", "number"]

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_ALTERNATION = "|".join(_MONTHS.keys())

_DATE_MD_Y = re.compile(rf"\b({_MONTH_ALTERNATION})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE)
_DATE_D_MY = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALTERNATION})\s+(\d{{4}})\b", re.IGNORECASE)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_PERCENT = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s?%")
_CURRENCY = re.compile(r"([$€£])\s?(\d[\d,]*(?:\.\d+)?)")

_UNIT_WORDS = [
    "mg", "kg", "g", "mL", "ml", "L", "l", "km", "miles", "mi",
    "°C", "°F", "days", "day", "months", "month", "years", "year",
    "hours", "hour", "minutes", "minute",
]
_UNIT_ALTERNATION = "|".join(re.escape(u) for u in sorted(_UNIT_WORDS, key=len, reverse=True))
_NUMBER_WITH_UNIT = re.compile(rf"\b(\d[\d,]*(?:\.\d+)?)\s?({_UNIT_ALTERNATION})\b")

_BARE_NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")

_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}
_WORD_NUM_ALTERNATION = "|".join(sorted(_WORD_NUMBERS.keys(), key=len, reverse=True))
_WORD_NUMBER_PATTERN = re.compile(
    rf"\b({_WORD_NUM_ALTERNATION})(?:-({_WORD_NUM_ALTERNATION}))?\b",
    re.IGNORECASE,
)
_WORD_NUMBER_WITH_UNIT = re.compile(
    rf"\b({_WORD_NUM_ALTERNATION})(?:-({_WORD_NUM_ALTERNATION}))?\s+({_UNIT_ALTERNATION})\b",
    re.IGNORECASE,
)

_SAFETY_KEYWORDS = re.compile(
    r"\b(mg|ml|mL|°c|°f|dos(e|age)|regulatory|authority|law|safety|incident|penalt(y|ies))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NumericToken:
    kind: Kind
    raw: str
    normalized: str
    start: int
    end: int
    unit: str | None = None


def _word_number_value(text: str, m: re.Match[str]) -> int | None:
    tens = _WORD_NUMBERS.get(m.group(1).lower())
    ones = _WORD_NUMBERS.get(m.group(2).lower()) if m.group(2) else None
    if tens is None:
        return None
    if ones is not None:
        return tens + ones
    return tens


def _extract_tokens(text: str) -> list[NumericToken]:
    consumed: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(not (end <= lo or start >= hi) for lo, hi in consumed)

    tokens: list[NumericToken] = []

    for pattern, fmt in ((_DATE_MD_Y, "mdY"), (_DATE_D_MY, "dMY"), (_DATE_ISO, "iso")):
        for m in pattern.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            if fmt == "mdY":
                month, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
                iso = f"{year:04d}-{_MONTHS[month]:02d}-{day:02d}"
            elif fmt == "dMY":
                day, month, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
                iso = f"{year:04d}-{_MONTHS[month]:02d}-{day:02d}"
            else:
                iso = m.group(0)
            tokens.append(NumericToken("date", m.group(0), iso, m.start(), m.end()))
            consumed.append((m.start(), m.end()))

    for m in _PERCENT.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        value = m.group(1).replace(",", "")
        tokens.append(NumericToken("percentage", m.group(0), value, m.start(), m.end()))
        consumed.append((m.start(), m.end()))

    for m in _CURRENCY.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        value = m.group(2).replace(",", "")
        tokens.append(NumericToken("currency", m.group(0), value, m.start(), m.end(), unit=m.group(1)))
        consumed.append((m.start(), m.end()))

    for m in _NUMBER_WITH_UNIT.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        value = m.group(1).replace(",", "")
        unit = m.group(2)
        tokens.append(NumericToken("unit_quantity", m.group(0), value, m.start(), m.end(), unit=unit))
        consumed.append((m.start(), m.end()))

    for m in _WORD_NUMBER_WITH_UNIT.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        value = _word_number_value(text, m)
        if value is None:
            continue
        unit = m.group(3)
        tokens.append(NumericToken("unit_quantity", m.group(0), str(value), m.start(), m.end(), unit=unit))
        consumed.append((m.start(), m.end()))

    for m in _BARE_NUMBER.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        value = m.group(0).replace(",", "")
        tokens.append(NumericToken("number", m.group(0), value, m.start(), m.end()))
        consumed.append((m.start(), m.end()))

    for m in _WORD_NUMBER_PATTERN.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        value = _word_number_value(text, m)
        if value is None:
            continue
        tokens.append(NumericToken("number", m.group(0), str(value), m.start(), m.end()))
        consumed.append((m.start(), m.end()))

    tokens.sort(key=lambda t: t.start)
    return tokens


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{text[lo:hi].strip()}{suffix}"


def _is_safety_relevant(text: str, start: int, end: int, window: int = 60) -> bool:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    return bool(_SAFETY_KEYWORDS.search(text[lo:hi]))


_KIND_TO_CATEGORY = {
    "date": DriftCategory.DATE_CHANGE,
    "percentage": DriftCategory.PERCENTAGE_CHANGE,
    "currency": DriftCategory.NUMERIC_CHANGE,
    "unit_quantity": DriftCategory.UNIT_CHANGE,
    "number": DriftCategory.NUMERIC_CHANGE,
}

# Unit spelling variants that refer to the same physical unit (e.g. "mi" vs
# "miles") are canonicalized before comparison, so a spelling choice alone
# is never mistaken for a unit-system change.
_UNIT_CANONICAL = {"mi": "miles"}


def _canonical_unit(unit: str) -> str:
    lowered = unit.lower()
    return _UNIT_CANONICAL.get(lowered, lowered)


# Explicit, narrow conversion policy (spec section 5 / DECISIONS.md #11):
# only unit pairs listed here are ever treated as "the translator correctly
# localized this value" — everything else that changes unit is flagged for
# human review rather than silently accepted or silently rewritten.
_CONVERSION_TABLE: dict[tuple[str, str], Callable[[float], float]] = {
    ("°c", "°f"): lambda c: c * 9 / 5 + 32,
    ("°f", "°c"): lambda f: (f - 32) * 5 / 9,
    ("g", "kg"): lambda g: g / 1000,
    ("kg", "g"): lambda kg: kg * 1000,
    ("mg", "g"): lambda mg: mg / 1000,
    ("g", "mg"): lambda g: g * 1000,
    ("mg", "kg"): lambda mg: mg / 1_000_000,
    ("kg", "mg"): lambda kg: kg * 1_000_000,
    ("ml", "l"): lambda ml: ml / 1000,
    ("l", "ml"): lambda liters: liters * 1000,
    ("km", "miles"): lambda km: km * 0.621371,
    ("miles", "km"): lambda mi: mi / 0.621371,
}


@dataclass(frozen=True, slots=True)
class ConversionCheck:
    verdict: Literal["legitimate_conversion", "invalid_conversion", "unsupported_conversion"]
    expected_value: float | None


def _check_unit_conversion(s_tok: NumericToken, b_tok: NumericToken, s_unit: str, b_unit: str) -> ConversionCheck:
    try:
        source_value = float(s_tok.normalized)
        actual_value = float(b_tok.normalized)
    except ValueError:
        return ConversionCheck("unsupported_conversion", None)

    convert = _CONVERSION_TABLE.get((s_unit, b_unit))
    if convert is None:
        return ConversionCheck("unsupported_conversion", None)

    expected_value = convert(source_value)
    # Absolute floor covers reasonable integer rounding (e.g. 35.6°F -> "36°F");
    # relative component covers larger magnitudes proportionally.
    tolerance = max(0.5, abs(expected_value) * 0.03)
    if abs(expected_value - actual_value) <= tolerance:
        return ConversionCheck("legitimate_conversion", expected_value)
    return ConversionCheck("invalid_conversion", expected_value)


def _unit_conversion_signal(
    source_text: str, back_translation_text: str, s_tok: NumericToken, b_tok: NumericToken, check: ConversionCheck
) -> Signal:
    if check.verdict == "invalid_conversion":
        expected_str = f"{check.expected_value:.1f}{b_tok.unit}" if check.expected_value is not None else "?"
        difference = (
            f"Unit changed AND the converted value is wrong: '{s_tok.raw}' → '{b_tok.raw}' "
            f"(a correct conversion would read approximately {expected_str})"
        )
        confidence = 0.9
    else:
        difference = (
            f"Unit system changed with no configured conversion policy for this unit pair: "
            f"'{s_tok.raw}' → '{b_tok.raw}'. Flagged for human review rather than guessed at."
        )
        confidence = 0.65
    return Signal(
        category=DriftCategory.UNIT_CHANGE,
        severity=Severity.CRITICAL,
        difference=difference,
        evidence_signal=f"unit_quantity:{s_tok.raw}->{b_tok.raw}:{check.verdict}",
        source_excerpt=_excerpt(source_text, s_tok.start, s_tok.end),
        back_translation_excerpt=_excerpt(back_translation_text, b_tok.start, b_tok.end),
        confidence=confidence,
        literal_replacement=None,  # never auto-rewrite a physical quantity — always human review
    )


def detect_numeric_drift(source_text: str, back_translation_text: str) -> list[Signal]:
    src_tokens = _extract_tokens(source_text)
    bt_tokens = _extract_tokens(back_translation_text)

    signals: list[Signal] = []
    by_kind_src: dict[Kind, list[NumericToken]] = {}
    by_kind_bt: dict[Kind, list[NumericToken]] = {}
    for t in src_tokens:
        by_kind_src.setdefault(t.kind, []).append(t)
    for t in bt_tokens:
        by_kind_bt.setdefault(t.kind, []).append(t)

    for kind in ("date", "percentage", "currency", "unit_quantity", "number"):
        src_list = by_kind_src.get(kind, [])
        bt_list = by_kind_bt.get(kind, [])
        paired = min(len(src_list), len(bt_list))
        for i in range(paired):
            s_tok, b_tok = src_list[i], bt_list[i]
            value_changed = s_tok.normalized != b_tok.normalized
            s_unit = _canonical_unit(s_tok.unit or "")
            b_unit = _canonical_unit(b_tok.unit or "")
            unit_changed = kind == "unit_quantity" and s_unit != b_unit

            if kind == "unit_quantity" and unit_changed:
                check = _check_unit_conversion(s_tok, b_tok, s_unit, b_unit)
                if check.verdict == "legitimate_conversion":
                    continue  # correctly localized value in a different unit system — not drift
                signals.append(_unit_conversion_signal(source_text, back_translation_text, s_tok, b_tok, check))
                continue

            if not value_changed:
                continue

            category = DriftCategory.NUMERIC_CHANGE if kind == "unit_quantity" else _KIND_TO_CATEGORY[kind]
            safety = _is_safety_relevant(source_text, s_tok.start, s_tok.end)
            severity = Severity.CRITICAL if (kind == "date" or safety) else Severity.HIGH

            literal_replacement = None
            if kind in ("number", "percentage", "currency", "unit_quantity"):
                # Digits are language-invariant, so a literal find/replace in
                # the target text is safe to propose automatically. Only
                # reachable here when the unit itself did NOT change.
                literal_replacement = (b_tok.raw, s_tok.raw)

            difference = f"Value changed: '{s_tok.raw}' → '{b_tok.raw}'"

            signals.append(
                Signal(
                    category=category,
                    severity=severity,
                    difference=difference,
                    evidence_signal=f"{kind}:{s_tok.raw}->{b_tok.raw}",
                    source_excerpt=_excerpt(source_text, s_tok.start, s_tok.end),
                    back_translation_excerpt=_excerpt(back_translation_text, b_tok.start, b_tok.end),
                    confidence=0.9,
                    literal_replacement=literal_replacement,
                )
            )

        if len(src_list) != len(bt_list):
            difference = (
                f"Count of {kind} values differs: source has {len(src_list)}, "
                f"back-translation has {len(bt_list)}"
            )
            signals.append(
                Signal(
                    category=_KIND_TO_CATEGORY[kind],
                    severity=Severity.MEDIUM,
                    difference=difference,
                    evidence_signal=f"{kind}_count:{len(src_list)}->{len(bt_list)}",
                    source_excerpt=_excerpt(source_text, 0, min(60, len(source_text))),
                    back_translation_excerpt=_excerpt(back_translation_text, 0, min(60, len(back_translation_text))),
                    confidence=0.35,
                )
            )

    return signals
