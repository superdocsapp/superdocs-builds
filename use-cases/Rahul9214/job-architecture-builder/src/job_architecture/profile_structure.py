"""Structural validation of employee-readable role profiles.

Semantic field structure is independent of WordprocessingML layout.
A Level expectations block may be seven paragraphs, one paragraph with
line breaks, or concatenated runs. Validation parses canonical markers,
not paragraph boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from job_architecture.level_text import (
    FIELD_AUTONOMY,
    FIELD_COMPLEXITY,
    FIELD_HEADER,
    FIELD_IMPACT,
    FIELD_LEADERSHIP,
    FIELD_PEOPLE,
    FIELD_SCOPE,
    RENDERED_FIELDS,
)

REQUIRED_RENDERED_FIELDS = RENDERED_FIELDS

PROFILE_SECTION_HEADINGS = (
    "Role title",
    "Job family",
    "Career track",
    "Level",
    "Classification",
    "Role purpose",
    "Responsibilities",
    "Scope / decision making",
    "Core competencies",
    "Level expectations",
    "Progression",
    "Source / evidence note",
)

_HEADING_LOOKUP = {item.lower(): item for item in PROFILE_SECTION_HEADINGS}
_HEADER_LINE = re.compile(r"^.+ \(definition version \d+\)\s*$")
_HEADER_MARKER = re.compile(
    r"(?P<full>(?P<label>[A-Za-z0-9][A-Za-z0-9+._/-]*) \(definition version (?P<version>\d+)\))"
)
_DIMENSION_PREFIXES = (
    (FIELD_SCOPE, "Scope:"),
    (FIELD_AUTONOMY, "Autonomy / decision authority:"),
    (FIELD_COMPLEXITY, "Complexity:"),
    (FIELD_IMPACT, "Impact:"),
    (FIELD_LEADERSHIP, "Leadership:"),
    (FIELD_PEOPLE, "People-management expectations:"),
)
_CANONICAL_ORDER = REQUIRED_RENDERED_FIELDS


@dataclass(frozen=True)
class StructureReport:
    ok: bool
    violations: tuple[str, ...]
    field_counts: dict[str, int]
    section_counts: dict[str, int]
    field_values: dict[str, str] = field(default_factory=dict)
    layout: dict[str, int] = field(default_factory=dict)


def apply_proposed_span_replace(text: str, before: str, after: str) -> str:
    """Apply a SuperDocs-style single span replacement. Does not mutate `text`."""
    if not before:
        raise ValueError("Replacement BEFORE span is empty")
    index = text.find(before)
    if index < 0:
        raise ValueError("Replacement BEFORE span was not found in the document text")
    return text[:index] + after + text[index + len(before) :]


def duplicate_block_via_narrow_header_replace(block: str) -> str:
    """Reproduce the live class of bug: replace only the version header with the full block."""
    header = next((line for line in block.splitlines() if _HEADER_LINE.match(line)), None)
    if header is None:
        raise ValueError("Level-expectations block has no version header to replace")
    return apply_proposed_span_replace(block, header, block)


def validate_level_expectations_block(text: str) -> StructureReport:
    markers = _find_semantic_markers(text)
    counts = {field_id: 0 for field_id in REQUIRED_RENDERED_FIELDS}
    values: dict[str, str] = {}
    violations: list[str] = []
    for field_id, _start, _end, matched in markers:
        counts[field_id] = counts.get(field_id, 0) + 1
        if field_id == FIELD_HEADER and FIELD_HEADER not in values:
            values[FIELD_HEADER] = matched
    leftover_prefix = text[: markers[0][1]].strip() if markers else text.strip()
    if leftover_prefix:
        if markers:
            violations.append(
                f"Unexpected extra content before Level expectations header: {leftover_prefix[:80]}"
            )
        else:
            violations.append(f"Unexpected extra line in level expectations: {leftover_prefix[:80]}")
    for index, (field_id, _start, end, matched) in enumerate(markers):
        next_start = markers[index + 1][1] if index + 1 < len(markers) else len(text)
        raw_value = text[end:next_start]
        if field_id == FIELD_HEADER:
            values.setdefault(FIELD_HEADER, matched)
            extra = raw_value.strip()
            if extra:
                violations.append(
                    f"Unexpected extra content between Level expectations fields: {extra[:80]}"
                )
            continue
        if field_id not in values:
            values[field_id] = raw_value.strip()
    for field_id in REQUIRED_RENDERED_FIELDS:
        n = counts[field_id]
        if n == 0:
            violations.append(f"Missing required level-expectations field {field_id}")
        elif n > 1:
            violations.append(f"Duplicate level-expectations field {field_id} (count={n})")
    if all(counts[item] == 2 for item in REQUIRED_RENDERED_FIELDS):
        violations.append("Duplicate complete Level expectations block")
    observed_order = tuple(item[0] for item in markers)
    if all(counts[item] == 1 for item in REQUIRED_RENDERED_FIELDS) and observed_order != _CANONICAL_ORDER:
        violations.append(
            "Level expectations fields are out of required order "
            f"(got {', '.join(observed_order)})"
        )
    return StructureReport(
        ok=not violations,
        violations=tuple(dict.fromkeys(violations)),
        field_counts=counts,
        section_counts={"level_expectations": 1 if text.strip() else 0},
        field_values=values,
    )


def validate_profile_document_text(text: str, *, layout: dict[str, int] | None = None) -> StructureReport:
    sections = split_profile_sections(text)
    section_counts = {name: 0 for name in PROFILE_SECTION_HEADINGS}
    violations: list[str] = []
    for heading, _body in sections:
        if heading in section_counts:
            section_counts[heading] += 1
    for heading, count in section_counts.items():
        if heading == "Level expectations" and count == 0:
            violations.append("Missing required profile section 'Level expectations'")
        elif count > 1:
            violations.append(f"Unexpected duplicate profile section {heading!r} (count={count})")
    bodies = [body for heading, body in sections if heading == "Level expectations"]
    field_counts = {field_id: 0 for field_id in REQUIRED_RENDERED_FIELDS}
    field_values: dict[str, str] = {}
    if not bodies:
        violations.append("No Level expectations section body to validate")
    else:
        nested = validate_level_expectations_block("\n".join(bodies))
        field_counts = nested.field_counts
        field_values = nested.field_values
        violations.extend(nested.violations)
    return StructureReport(
        ok=not violations,
        violations=tuple(dict.fromkeys(violations)),
        field_counts=field_counts,
        section_counts=section_counts,
        field_values=field_values,
        layout=dict(layout or {}),
    )


def split_profile_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        heading = _as_heading(stripped)
        if heading is not None:
            if current_heading or current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = heading
            current_lines = []
            continue
        current_lines.append(raw)
    if current_heading or current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return sections


def _find_semantic_markers(text: str) -> list[tuple[str, int, int, str]]:
    found: list[tuple[str, int, int, str]] = []
    for match in _HEADER_MARKER.finditer(text):
        found.append((FIELD_HEADER, match.start(), match.end(), match.group("full")))
    lowered = text.lower()
    for field_id, prefix in _DIMENSION_PREFIXES:
        start = 0
        needle = prefix.lower()
        while True:
            idx = lowered.find(needle, start)
            if idx < 0:
                break
            found.append((field_id, idx, idx + len(prefix), text[idx : idx + len(prefix)]))
            start = idx + len(prefix)
    found.sort(key=lambda item: (item[1], -item[2], item[0]))
    collapsed: list[tuple[str, int, int, str]] = []
    last_end = -1
    for item in found:
        if item[1] < last_end:
            continue
        collapsed.append(item)
        last_end = item[2]
    return collapsed


def _as_heading(line: str) -> str | None:
    if not line:
        return None
    if line.startswith("#"):
        line = line.lstrip("#").strip()
    if ":" in line and line.lower() not in {item.lower() for item in PROFILE_SECTION_HEADINGS}:
        return None
    return _HEADING_LOOKUP.get(line.lower())
