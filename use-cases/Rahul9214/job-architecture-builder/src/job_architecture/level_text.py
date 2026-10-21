"""Dimension-surgical rendering of canonical level expectations.

Profile `level_expectations` is a structured block of named fields. A canonical
level change updates only the rendered fields that correspond to changed
LevelDefinition dimensions. Unchanged fields, including fallback wording, stay
byte-identical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from job_architecture.models import LevelDefinition

CANONICAL_DIMENSIONS = (
    "scope",
    "autonomy",
    "decision_authority",
    "complexity",
    "impact",
    "leadership",
    "people_management",
    "version",
    "label",
)

FIELD_HEADER = "header"
FIELD_SCOPE = "scope"
FIELD_AUTONOMY = "autonomy"
FIELD_COMPLEXITY = "complexity"
FIELD_IMPACT = "impact"
FIELD_LEADERSHIP = "leadership"
FIELD_PEOPLE = "people_management"

RENDERED_FIELDS = (
    FIELD_HEADER,
    FIELD_SCOPE,
    FIELD_AUTONOMY,
    FIELD_COMPLEXITY,
    FIELD_IMPACT,
    FIELD_LEADERSHIP,
    FIELD_PEOPLE,
)

CANONICAL_TO_RENDERED = {
    "scope": FIELD_SCOPE,
    "autonomy": FIELD_AUTONOMY,
    "decision_authority": FIELD_AUTONOMY,
    "complexity": FIELD_COMPLEXITY,
    "impact": FIELD_IMPACT,
    "leadership": FIELD_LEADERSHIP,
    "people_management": FIELD_PEOPLE,
    "version": FIELD_HEADER,
    "label": FIELD_HEADER,
}

_FIELD_PREFIXES = (
    (FIELD_SCOPE, "Scope:"),
    (FIELD_AUTONOMY, "Autonomy / decision authority:"),
    (FIELD_COMPLEXITY, "Complexity:"),
    (FIELD_IMPACT, "Impact:"),
    (FIELD_LEADERSHIP, "Leadership:"),
    (FIELD_PEOPLE, "People-management expectations:"),
)

_HEADER = re.compile(r"^(?P<label>.+?) \(definition version (?P<version>\d+)\)\s*$")

_STANDARD_PREFIX = {
    FIELD_SCOPE: "Scope: ",
    FIELD_AUTONOMY: "Autonomy / decision authority: ",
    FIELD_COMPLEXITY: "Complexity: ",
    FIELD_IMPACT: "Impact: ",
    FIELD_LEADERSHIP: "Leadership: ",
    FIELD_PEOPLE: "People-management expectations: ",
}


@dataclass(frozen=True)
class ExpectationLine:
    field_id: str | None
    prefix: str
    value: str
    raw: str


@dataclass(frozen=True)
class ParsedLevelExpectations:
    lines: tuple[ExpectationLine, ...]

    def raw_for(self, field_id: str) -> str | None:
        for item in self.lines:
            if item.field_id == field_id:
                return item.raw
        return None

    def value_for(self, field_id: str) -> str | None:
        for item in self.lines:
            if item.field_id == field_id:
                return item.value
        return None

    def render(self) -> str:
        return "\n".join(item.raw for item in self.lines)


def changed_dimensions(old: LevelDefinition, new: LevelDefinition) -> frozenset[str]:
    changed: set[str] = set()
    for name in CANONICAL_DIMENSIONS:
        if getattr(old, name) != getattr(new, name):
            changed.add(name)
    return frozenset(changed)


def rendered_fields_for(canonical_changes: Iterable[str]) -> frozenset[str]:
    return frozenset(
        CANONICAL_TO_RENDERED[name] for name in canonical_changes if name in CANONICAL_TO_RENDERED
    )


def parse_level_expectations(text: str) -> ParsedLevelExpectations:
    lines: list[ExpectationLine] = []
    header_used = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        if not header_used and _HEADER.match(raw):
            lines.append(ExpectationLine(FIELD_HEADER, "", raw, raw))
            header_used = True
            continue
        matched = _match_prefixed(raw)
        if matched is not None:
            lines.append(matched)
            continue
        lines.append(ExpectationLine(None, "", raw, raw))
    return ParsedLevelExpectations(tuple(lines))


def patch_level_expectations(
    stored: str,
    new_level: LevelDefinition,
    canonical_changes: Iterable[str],
) -> str:
    allowed = rendered_fields_for(canonical_changes)
    parsed = parse_level_expectations(stored)
    seen: set[str] = set()
    rebuilt: list[ExpectationLine] = []
    for line in parsed.lines:
        if line.field_id is None or line.field_id not in allowed:
            rebuilt.append(line)
            if line.field_id:
                seen.add(line.field_id)
            continue
        rebuilt.append(_replacement_line(line, new_level))
        seen.add(line.field_id)
    for field_id in RENDERED_FIELDS:
        if field_id in allowed and field_id not in seen:
            rebuilt.append(_standard_line(field_id, new_level))
    return ParsedLevelExpectations(tuple(rebuilt)).render()


def field_preservation_violations(
    before_text: str,
    after_text: str,
    allowed_fields: Iterable[str],
) -> tuple[str, ...]:
    allowed = set(allowed_fields)
    before = parse_level_expectations(before_text)
    after = parse_level_expectations(after_text)
    violations: list[str] = []
    for field_id in RENDERED_FIELDS:
        if field_id in allowed:
            continue
        if before.raw_for(field_id) != after.raw_for(field_id):
            violations.append(f"Unchanged rendered field {field_id!r} was rewritten")
    return tuple(violations)


def _match_prefixed(raw: str) -> ExpectationLine | None:
    lowered = raw.lower()
    for field_id, prefix in _FIELD_PREFIXES:
        if lowered.startswith(prefix.lower()):
            original_prefix = raw[: len(prefix)]
            rest = raw[len(prefix) :]
            stripped = rest.lstrip(" ")
            spacing = rest[: len(rest) - len(stripped)]
            return ExpectationLine(field_id, original_prefix + spacing, stripped, raw)
    return None


def _replacement_line(line: ExpectationLine, new_level: LevelDefinition) -> ExpectationLine:
    if line.field_id == FIELD_HEADER:
        raw = f"{new_level.label} (definition version {new_level.version})"
        return ExpectationLine(FIELD_HEADER, "", raw, raw)
    value = _field_value(line.field_id or "", new_level)
    raw = f"{line.prefix}{value}"
    return ExpectationLine(line.field_id, line.prefix, value, raw)


def _standard_line(field_id: str, new_level: LevelDefinition) -> ExpectationLine:
    if field_id == FIELD_HEADER:
        raw = f"{new_level.label} (definition version {new_level.version})"
        return ExpectationLine(FIELD_HEADER, "", raw, raw)
    prefix = _STANDARD_PREFIX[field_id]
    value = _field_value(field_id, new_level)
    raw = f"{prefix}{value}"
    return ExpectationLine(field_id, prefix, value, raw)


def _field_value(field_id: str, level: LevelDefinition) -> str:
    if field_id == FIELD_SCOPE:
        return level.scope
    if field_id == FIELD_AUTONOMY:
        return level.decision_authority or level.autonomy
    if field_id == FIELD_COMPLEXITY:
        return level.complexity or "Matches the published complexity of this level."
    if field_id == FIELD_IMPACT:
        return level.impact
    if field_id == FIELD_LEADERSHIP:
        return level.leadership
    if field_id == FIELD_PEOPLE:
        return level.people_management or "None"
    raise ValueError(f"Unknown rendered field {field_id}")
