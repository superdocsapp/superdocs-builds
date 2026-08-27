"""Email is the most hostile input surface there is.

Anyone can send a message containing text aimed at whatever automated system reads it
next. This build's structural defence is that thread content never reaches a
decision-making position: the prompt fences it and calls it evidence, the letter is built
from *confirmed commitments* rather than from the thread, and a human confirms them.

This detector is the second layer — it names the attempt so it appears in the report
instead of passing silently. Neither layer is asked to do the other's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction-override", re.compile(
        r"ignore\s+(?:all\s+)?(?:your\s+|the\s+)?previous\s+instructions?|"
        r"disregard\s+(?:all\s+)?(?:previous|prior|earlier)\s+", re.I)),
    ("false-authority", re.compile(
        r"system\s+(?:instruction|prompt)|^\s*system\s*:|overrides?\s+your", re.I | re.M)),
    ("forged-commitment", re.compile(
        r"(?:record|add|include)\s+(?:the\s+)?following\s+(?:as\s+)?commitment|"
        r"treat\s+this\s+as\s+(?:a\s+)?(?:firm\s+)?commitment", re.I)),
    ("report-suppression", re.compile(
        r"do\s+not\s+(?:report|mention|include)\s+this|omit\s+this\s+from", re.I)),
    ("mode-switch", re.compile(
        r"you\s+are\s+now\s+(?:operating\s+)?in\s+\w+\s+mode", re.I)),
)


@dataclass(frozen=True)
class Finding:
    kind: str
    where: str
    excerpt: str

    def render(self) -> str:
        return f"[{self.kind}] {self.where}: {self.excerpt}"


def scan_thread(thread: object) -> list[Finding]:
    """Look for instruction-shaped text in every message. Reports; obeys nothing."""
    findings: list[Finding] = []
    for message in getattr(thread, "messages", ()):  # duck-typed for testability
        for kind, pattern in _PATTERNS:
            match = pattern.search(message.body or "")
            if match:
                findings.append(Finding(
                    kind=kind,
                    where=f"message {message.index} ({message.sender})",
                    excerpt=_excerpt(message.body, match),
                ))
    return findings


def _excerpt(text: str, match: re.Match[str]) -> str:
    start, end = max(0, match.start() - 40), min(len(text), match.end() + 60)
    snippet = " ".join(text[start:end].split())
    return f"{'…' if start else ''}{snippet}{'…' if end < len(text) else ''}"
