"""Deterministic clause->rule matching.

Keyword matching over normalized clause text, with headings pulling their
following body paragraphs into the same clause. Deterministic on purpose: the
AI decides what the clause should say; code decides which clause a rule
governs, so the mapping is reproducible and auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .document import Chunk
from .playbook import Playbook, Rule

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

INJECTION_PATTERNS = [
    r"automated .{0,40}(review|system|agent)",
    r"\bai\b.{0,60}(approve|ignore|disregard)",
    r"(approve|accept) (this|the) agreement without",
    r"(ignore|disregard|override) .{0,40}(instruction|review|rule)",
    r"(review systems?|reviewing systems?|language model).{0,60}(approve|skip|disregard)",
]


@dataclass
class ClauseGroup:
    """A heading plus its body chunks — the unit a rule governs."""

    heading: Chunk | None
    body: list[Chunk] = field(default_factory=list)

    @property
    def chunks(self) -> list[Chunk]:
        return ([self.heading] if self.heading else []) + self.body

    @property
    def norm_text(self) -> str:
        return " ".join(c.norm_text for c in self.chunks)

    @property
    def label(self) -> str:
        return self.heading.text if self.heading else (self.body[0].text[:60] + "…" if self.body else "(empty)")


def group_clauses(chunks: list[Chunk]) -> list[ClauseGroup]:
    groups: list[ClauseGroup] = []
    current: ClauseGroup | None = None
    for chunk in chunks:
        if chunk.tag in HEADING_TAGS:
            if current:
                groups.append(current)
            current = ClauseGroup(heading=chunk)
        else:
            if current is None:
                current = ClauseGroup(heading=None)
            current.body.append(chunk)
    if current:
        groups.append(current)
    return groups


def match_rules(playbook: Playbook, groups: list[ClauseGroup]) -> tuple[dict[str, list[int]], list[Rule]]:
    """Returns (rule_id -> indices of governed clause groups, rules with no match)."""
    matched: dict[str, list[int]] = {}
    missing: list[Rule] = []
    for rule in playbook.rules:
        hits = [i for i, g in enumerate(groups) if any(kw in g.norm_text for kw in rule.clause_keywords)]
        if hits:
            matched[rule.id] = hits
        else:
            missing.append(rule)
    return matched, missing


def scan_for_embedded_instructions(chunks: list[Chunk]) -> list[dict]:
    findings = []
    for chunk in chunks:
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, chunk.norm_text):
                findings.append({"chunk_id": chunk.chunk_id, "pattern": pattern, "text": chunk.text})
                break
    return findings
