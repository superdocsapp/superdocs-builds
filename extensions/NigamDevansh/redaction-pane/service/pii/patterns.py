"""Tier 1 — identifiers with a shape, and often a checksum.

An SSN is a regex plus a Luhn check; sending it to a model costs money, adds
latency, and can answer differently next time. Every match carries offsets
inside its block, because the pane shows the surrounding sentence and the
redaction replaces exactly the span. Nothing here is clever about context:
`4111 1111 1111 1111` in a test-card sentence is still a card number, and the
reviewer dismisses it in one click.

See extensions/redaction-pane/README.md § "How it finds things".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Categories are the reviewer's grouping, and they come from the assignment:
# personal data, health data, account identifiers, privileged passages.
PERSONAL = "personal"
HEALTH = "health"
ACCOUNT = "account"
PRIVILEGED = "privileged"


@dataclass(frozen=True, slots=True)
class Span:
    """One candidate, located exactly."""

    start: int
    end: int
    text: str
    kind: str
    """`ssn`, `credit_card`, `email` — what it is, shown on the row."""
    category: str
    """Which of the four groups the pane sorts it under."""
    detector: str
    """`pattern`, `ner`, `llm`. Shown, because a reviewer treats a regex hit and
    a model's guess differently, and hiding which is which would be dishonest."""
    confidence: float = 1.0


def _luhn(digits: str) -> bool:
    """The check that turns "sixteen digits" into "a card number". Without it,
    every order number and invoice reference is one, the pane fills with noise,
    and the reviewer learns to click through — past the real one too."""
    numbers = [int(d) for d in digits if d.isdigit()]
    if len(numbers) < 13:
        return False
    total = 0
    for index, digit in enumerate(reversed(numbers)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _ssn_valid(text: str) -> bool:
    """The ranges the SSA never issues, so obvious fakes do not fill the pane."""
    digits = re.sub(r"\D", "", text)
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    return (
        area not in {"000", "666"}
        and not area.startswith("9")
        and group != "00"
        and serial != "0000"
    )


PATTERNS: tuple[tuple[str, str, str, str], ...] = (
    # (kind, category, regex, validator name)
    ("ssn", PERSONAL, r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b", "ssn"),
    ("credit_card", ACCOUNT, r"\b(?:\d[ -]?){13,19}\b", "luhn"),
    ("iban", ACCOUNT, r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){2,7}[A-Z0-9]{1,4}\b", ""),
    ("routing_number", ACCOUNT, r"\bABA[: ]+\d{9}\b|\brouting(?: number)?[: ]+\d{9}\b", ""),
    ("account_number", ACCOUNT,
     r"\baccount(?: number| no\.?| #)?[: ]+[A-Z0-9-]{6,}\b", ""),
    ("email", PERSONAL, r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b", ""),
    ("phone", PERSONAL, r"\b(?:\+?\d{1,2}[ -]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b", ""),
    ("date_of_birth", PERSONAL,
     r"\b(?:DOB|date of birth)[: ]+"
     r"(?:\d{1,2}[ /.-]\d{1,2}[ /.-]\d{2,4}"
     r"|\d{1,2} \w+ \d{4}"
     r"|\w+ \d{1,2},? \d{4})", ""),
    ("passport", PERSONAL, r"\bpassport(?: number| no\.?)?[: ]+[A-Z0-9]{6,9}\b", ""),
    ("national_id", PERSONAL,
     r"\b(?:NHS|NI|national insurance)(?: number| no\.?)?[: ]+[A-Z0-9 ]{6,13}\b", ""),
    ("medical_record", HEALTH,
     r"\b(?:MRN|medical record(?: number)?)[: ]+[A-Z0-9-]{4,}\b", ""),
    ("health_condition", HEALTH,
     r"\b(?:diagnosed with|diagnosis of|prognosis of|treatment for|prescribed)\b"
     r"[^.,;\n]{0,60}", ""),
    ("insurance_id", HEALTH,
     r"\b(?:policy|member|insurance)(?: number| id| no\.?)[: ]+[A-Z0-9-]{5,}\b", ""),
)
"""Ordered, and the order matters: the first match wins its span. `credit_card`
before `phone` because a 16-digit run reads as both and only one has a checksum.
Overlaps are resolved in `find`, not by hoping the expressions are disjoint."""

_VALIDATORS = {"luhn": _luhn, "ssn": _ssn_valid}
_COMPILED = tuple(
    (kind, category, re.compile(pattern, re.IGNORECASE), validator)
    for kind, category, pattern, validator in PATTERNS
)


def find(text: str) -> list[Span]:
    """Every identifier in one block, in document order, no overlaps. The block
    is a SuperDocs chunk; offsets are relative to it, and the caller keeps the
    chunk id, so a confirmed candidate becomes an edit at exactly one block."""
    if not text:
        return []

    found: list[Span] = []
    for kind, category, pattern, validator in _COMPILED:
        for match in pattern.finditer(text):
            check = _VALIDATORS.get(validator)
            if check is not None and not check(match.group(0)):
                continue
            # Trim by moving the offsets, never by stripping the text.
            # `text[start:end] == span.text` is the invariant the system rests
            # on: the pane highlights by offset, the edit replaces by string, the
            # residue check searches for it. A stripped copy would break all three.
            start, end = match.start(), match.end()
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            if any(hit.start < end and start < hit.end for hit in found):
                continue  # already claimed by an earlier, more specific pattern
            found.append(
                Span(
                    start=start,
                    end=end,
                    text=text[start:end],
                    kind=kind,
                    category=category,
                    detector="pattern",
                )
            )
    return sorted(found, key=lambda span: span.start)


def sentence_around(text: str, start: int, end: int, *, limit: int = 240) -> str:
    """The sentence a candidate sits in — what the reviewer actually judges. "Is
    `4111…` sensitive?" has no answer; "in *Customer's card is 4111…*?" has an
    obvious one."""
    left = max(0, start - limit // 2)
    marks = (".", "\n", "!", "?", ";")
    opening = max(text.rfind(mark, left, start) + 1 for mark in marks)
    begin = opening if opening > left else left

    right = min(len(text), end + limit // 2)
    closes = [
        index
        for index in (text.find(mark, end, right) for mark in (".", "\n", "!", "?"))
        if index != -1
    ]
    finish = min(closes) + 1 if closes else right
    return text[begin:finish].strip()
