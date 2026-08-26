"""Splits the master policy document into core and annex sections."""

from __future__ import annotations

import re
from pathlib import Path

HEADING_RE = re.compile(r"^## (\d+) (.+)$", re.MULTILINE)


def parse_sections(text: str) -> list[dict]:
    """Split a numbered document into sections.

    A section number that appears more than once is only ever safe to
    collapse when every occurrence is byte-identical — that is a flaky
    SuperDocs export repeating the whole document verbatim (observed live,
    compounding with each further export call on the same session: 9
    sections became 72 headings, exactly 8 verbatim copies), not a content
    problem. Comparing copies with `==` (not corelock.normalise — nothing
    outside lock-time/verify-time may normalise text) is deliberately
    strict: the moment two copies of the same number actually differ, that
    is a real conflict — content genuinely merged or corrupted — and this
    raises rather than guessing which copy is right. Live testing found a
    duplicated export used to slip through undetected: a later
    `{s["number"]: s for s in sections}` lookup elsewhere would silently
    pick the LAST copy of each number. This is the one place every caller
    (lock-time, verify-time, translation, notices) parses a document, so
    catching it here closes the whole class rather than one call site.
    """
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        raise ValueError("no numbered headings found")

    all_sections = []
    for i, match in enumerate(matches):
        number = int(match.group(1))
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        all_sections.append({"number": number, "heading": heading, "body": body})

    by_number: dict[int, list[dict]] = {}
    for section in all_sections:
        by_number.setdefault(section["number"], []).append(section)

    conflicting = sorted(
        number
        for number, copies in by_number.items()
        if len({(c["heading"], c["body"]) for c in copies}) > 1
    )
    if conflicting:
        raise ValueError(
            f"section number(s) {conflicting} appear more than once with different "
            "content in this document — it may have been corrupted by an export "
            "call. Fix: this document cannot be safely parsed as one policy pack; "
            "inspect the raw export."
        )

    seen: set[int] = set()
    sections = []
    for section in all_sections:
        if section["number"] in seen:
            continue
        seen.add(section["number"])
        sections.append(section)
    return sections


def load_sections(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return parse_sections(text)


def assert_matches_manifest(sections: list[dict], manifest: dict) -> None:
    declared = manifest["sections"]
    if len(sections) != len(declared):
        raise ValueError(
            f"parsed {len(sections)} sections but manifest declares {len(declared)}"
        )
    for parsed, expected in zip(sections, declared):
        if parsed["number"] != expected["number"]:
            raise ValueError(
                f"section order mismatch: parsed number {parsed['number']}, "
                f"manifest expects {expected['number']}"
            )
        if parsed["heading"] != expected["heading"]:
            raise ValueError(
                f"section {parsed['number']} heading {parsed['heading']!r} "
                f"does not match manifest heading {expected['heading']!r}"
            )
