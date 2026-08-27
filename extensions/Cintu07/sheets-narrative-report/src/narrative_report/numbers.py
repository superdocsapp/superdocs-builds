"""Formatting, substitution and the numeric-integrity check.

This module is the reason the build can claim "the numbers in the prose match
the sheet exactly". The claim is not that the model is careful, it is that the
model is never given the chance to type a digit.

The flow is:

1. The model writes prose containing only ``{{fact:key}}`` tokens.
2. :func:`substitute` replaces each token with a formatted value **and records
   the exact character span it wrote**.
3. :func:`find_unverified_numerals` walks the result and reports any digit that
   is not inside one of those spans.

Step 3 is what makes it checkable rather than hopeful. A model that ignores the
instruction and writes "revenue rose to 4.2 million" does not produce a subtly
wrong report; it produces a loud, located failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .models import Fact, FactSet, FormatSpec

TOKEN_RE = re.compile(r"\{\{fact:([A-Za-z0-9_.\-]+)\}\}")

DEFAULT_CURRENCY_SYMBOL = "$"

_QUANTIZERS: dict[FormatSpec, Decimal] = {
    "currency0": Decimal("1"),
    "currency2": Decimal("0.01"),
    "signed_currency0": Decimal("1"),
    "number0": Decimal("1"),
    "number1": Decimal("0.1"),
    "number2": Decimal("0.01"),
    "percent0": Decimal("1"),
    "percent1": Decimal("0.1"),
    "signed_percent1": Decimal("0.1"),
    "multiple1": Decimal("0.1"),
}


class NumericIntegrityError(RuntimeError):
    """Raised when rendered prose contains a number we cannot trace to a fact."""


@dataclass(frozen=True, slots=True)
class Violation:
    """An untraceable numeral found in rendered prose."""

    text: str
    start: int
    end: int
    context: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"unverified numeral {self.text!r} at {self.start} in “…{self.context}…”"


@dataclass(slots=True)
class Rendered:
    """Result of substituting tokens into a template."""

    text: str
    spans: list[tuple[int, int]] = field(default_factory=list)
    used_keys: list[str] = field(default_factory=list)
    unknown_tokens: list[str] = field(default_factory=list)


def format_fact(fact: Fact, currency_symbol: str = DEFAULT_CURRENCY_SYMBOL) -> str:
    """Render a fact as it will appear in the document.

    Decimal in, string out, half-up rounding, the convention finance readers
    expect, and stable across runs so that an unchanged fact renders to
    byte-identical text.
    """
    if fact.unit == "text" or fact.fmt == "text":
        return str(fact.value)

    assert isinstance(fact.value, Decimal)  # guaranteed by Fact.__post_init__
    quantum = _QUANTIZERS[fact.fmt]
    value = fact.value.quantize(quantum, rounding=ROUND_HALF_UP)

    # Normalise negative zero: -0.04 rounded to 1dp must not print "-0.0".
    if value == 0:
        value = abs(value)

    magnitude = abs(value)
    decimals = -quantum.as_tuple().exponent
    grouped = f"{magnitude:,.{decimals}f}"
    negative = value < 0

    if fact.fmt in ("currency0", "currency2"):
        return f"-{currency_symbol}{grouped}" if negative else f"{currency_symbol}{grouped}"
    if fact.fmt == "signed_currency0":
        return f"{'-' if negative else '+'}{currency_symbol}{grouped}"
    if fact.fmt in ("percent0", "percent1"):
        return f"-{grouped}%" if negative else f"{grouped}%"
    if fact.fmt == "signed_percent1":
        return f"{'-' if negative else '+'}{grouped}%"
    if fact.fmt == "multiple1":
        return f"-{grouped}x" if negative else f"{grouped}x"
    return f"-{grouped}" if negative else grouped


def substitute(
    template: str,
    facts: FactSet,
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL,
) -> Rendered:
    """Replace ``{{fact:key}}`` tokens, recording where each value landed.

    Unknown tokens are left in place rather than silently dropped: a token that
    survives into the output is visible in the review UI and caught by
    :func:`assert_clean`, which is far safer than emitting a sentence with a
    hole where a number should be.
    """
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    used: list[str] = []
    unknown: list[str] = []
    cursor = 0
    length = 0

    for match in TOKEN_RE.finditer(template):
        literal = template[cursor : match.start()]
        out.append(literal)
        length += len(literal)

        key = match.group(1)
        if key in facts:
            value = format_fact(facts[key], currency_symbol)
            spans.append((length, length + len(value)))
            used.append(key)
            out.append(value)
            length += len(value)
        else:
            unknown.append(key)
            out.append(match.group(0))
            length += len(match.group(0))
        cursor = match.end()

    out.append(template[cursor:])
    return Rendered("".join(out), spans, used, unknown)


def _text_regions(html: str) -> list[tuple[int, int]]:
    """Character ranges of ``html`` that are visible text, not markup.

    Numbers inside tags are everywhere and legitimate, ``data-chunk-id``
    values, image widths, hex colours. Only what a reader actually sees is
    subject to the integrity rule.
    """
    regions: list[tuple[int, int]] = []
    start = 0
    depth = 0
    for i, ch in enumerate(html):
        if ch == "<":
            if depth == 0 and i > start:
                regions.append((start, i))
            depth += 1
        elif ch == ">":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    start = i + 1
    if depth == 0 and start < len(html):
        regions.append((start, len(html)))
    return regions


_ENTITY_RE = re.compile(r"&#?\w+;")

# A separator only belongs to the number when digits follow it, so a value at
# the end of a sentence ("$1,234.") yields the run "1,234" and not "1,234." ,
# otherwise every sentence-final figure would overrun its fact span by one
# character and be reported as a violation.
_DIGIT_RUN_RE = re.compile(r"\d+(?:[,.]\d+)*")


def find_unverified_numerals(rendered: Rendered) -> list[Violation]:
    """Every numeral in visible text that did not come from a fact.

    This is the load-bearing check. It runs on the model's proposed prose
    *before* a human ever sees it, and again on the final document.
    """
    text = rendered.text
    protected = rendered.spans
    entity_spans = [m.span() for m in _ENTITY_RE.finditer(text)]
    violations: list[Violation] = []

    def covered(lo: int, hi: int, spans: list[tuple[int, int]]) -> bool:
        return any(s <= lo and hi <= e for s, e in spans)

    for region_start, region_end in _text_regions(text):
        for match in _DIGIT_RUN_RE.finditer(text, region_start, region_end):
            lo, hi = match.span()
            if covered(lo, hi, protected) or covered(lo, hi, entity_spans):
                continue
            violations.append(
                Violation(
                    text=match.group(0),
                    start=lo,
                    end=hi,
                    context=text[max(0, lo - 40) : hi + 40].replace("\n", " "),
                )
            )
    return violations


# Words that assert a size or direction. If the model types one of these itself
# rather than taking it from a fact, the claim is ungrounded: it was not derived
# from the cells, and a later data change cannot invalidate it, so it goes stale
# silently. That is the same failure as a wrong number, wearing words.
_QUANTITY_WORDS = re.compile(
    r"\b(materiall?y|sharply|modestly|slightly|significantly|substantially|dramatically"
    r"|marginally|steeply|strongly|markedly|considerably|notably|roughly|approximately"
    r"|about|nearly|almost|around|surged|plummeted|soared|collapsed|spiked"
    r"|doubled|tripled|halved"
    # Claims about a pattern across periods, not about one figure. Grounding
    # every number is not enough on its own: "revenue reached $2,388,000,
    # marking the fourth consecutive period of growth" has a correct figure
    # wrapped in an assertion nobody checked. The streak fact exists so the
    # model has a grounded way to say this, and these words catch it saying it
    # any other way.
    r"|consecutive|consistently|steadily|uninterrupted|unbroken|every\s+quarter"
    r"|every\s+period|each\s+quarter|trend|trending|streak|momentum|reversal"
    r"|continues?\s+to|year\s+on\s+year|quarter\s+on\s+quarter)\b",
    re.IGNORECASE,
)


def find_ungrounded_quantity_words(rendered: Rendered) -> list[Violation]:
    """Claims about size, direction or pattern that did not come from a fact.

    Reported as findings rather than hard failures: unlike a wrong number, a
    qualitative claim is a judgement the reviewer may well accept. But they
    should be told it is the model's word and not the sheet's.
    """
    text = rendered.text
    protected = rendered.spans
    found: list[Violation] = []

    for region_start, region_end in _text_regions(text):
        for match in _QUANTITY_WORDS.finditer(text, region_start, region_end):
            lo, hi = match.span()
            if any(s <= lo and hi <= e for s, e in protected):
                continue
            found.append(
                Violation(
                    text=match.group(0),
                    start=lo,
                    end=hi,
                    context=text[max(0, lo - 40) : hi + 40].replace("\n", " "),
                )
            )
    return found


def assert_clean(rendered: Rendered) -> None:
    """Raise unless the rendered prose is fully traceable.

    Deliberately fails on leftover tokens as well as stray numerals: an
    unresolved ``{{fact:…}}`` means the report is making a claim it cannot
    support, which is exactly the failure mode this build refuses to ship.
    """
    problems: list[str] = []
    if rendered.unknown_tokens:
        problems.append("unresolved fact tokens: " + ", ".join(sorted(set(rendered.unknown_tokens))))
    violations = find_unverified_numerals(rendered)
    if violations:
        problems.append("; ".join(str(v) for v in violations))
    if problems:
        raise NumericIntegrityError(" | ".join(problems))


def referenced_keys(template: str) -> tuple[str, ...]:
    """Fact keys a template depends on, in first-appearance order."""
    seen: dict[str, None] = {}
    for match in TOKEN_RE.finditer(template):
        seen.setdefault(match.group(1), None)
    return tuple(seen)
