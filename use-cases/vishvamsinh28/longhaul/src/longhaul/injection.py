"""Detecting document content that is trying to give orders.

A source document is data to report on, never a command to obey. Longhaul's structural
defence is that document text never reaches a decision-making position: the plan comes
from the job spec, the gate decisions come from a policy or a human, and neither reads
document content as instructions. This module is the second layer — a deliberate,
hard-coded detector that *names* the attempt so it appears in the report instead of
passing through silently.

Two layers on purpose. The structural one is what makes the system safe; the detector is
what makes the attempt visible. Neither is asked to do the other's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Phrasings that only ever appear when text is addressing an automated reader.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction-override", re.compile(
        r"ignore\s+(?:all\s+)?(?:your\s+|the\s+)?previous\s+instructions?", re.I)),
    ("instruction-override", re.compile(
        r"disregard\s+(?:all\s+)?(?:your\s+|the\s+)?(?:previous|prior|earlier)\s+", re.I)),
    ("false-authority", re.compile(
        r"system\s+instruction|^\s*system\s*:|pre-?authoris?zed|overrides?\s+your", re.I | re.M)),
    ("gate-bypass", re.compile(
        r"approve\s+(?:every|all)\b|skip\s+the\s+(?:human\s+)?(?:approval\s+)?gate|"
        r"without\s+review", re.I)),
    ("state-forgery", re.compile(
        r"mark\s+all\s+(?:remaining\s+)?steps?\s+as\s+(?:already\s+)?complete", re.I)),
    ("report-suppression", re.compile(
        r"do\s+not\s+report\s+this|state\s+that\s+no\s+findings", re.I)),
    ("mode-switch", re.compile(
        r"you\s+are\s+now\s+(?:operating\s+)?in\s+\w+\s+mode|maintenance\s+mode", re.I)),
)


@dataclass(frozen=True)
class Finding:
    """One place a document tried to issue an instruction."""

    kind: str
    excerpt: str
    where: str

    def render(self) -> str:
        return f"[{self.kind}] {self.where}: {self.excerpt}"


def scan(text: str, *, where: str = "document") -> list[Finding]:
    """Find instruction-shaped text. Returns findings; obeys nothing."""
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            key = (kind, match.start() // 200)
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(kind=kind, excerpt=_excerpt(text, match), where=where))
    return findings


def _excerpt(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 60)
    snippet = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def scan_file(path: str, slug: str) -> list[Finding]:
    from pathlib import Path

    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return scan(text, where=slug)
