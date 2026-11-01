"""Security / PII agent.

Fully deterministic, no LLM call required -- pattern-based
detection of emails, phone numbers, card-like numbers, and common
secret/API-key shapes. Real logic, not a stub: this is exactly the
kind of check that should never depend on a model being available.
"""
from __future__ import annotations

import re

from .base import AgentResult, BaseAgent, DocumentContext, Suggestion

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("phone", re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("card_like", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("api_key", re.compile(r"\b(?:sk|pk|api|key)[_-][A-Za-z0-9]{16,}\b", re.IGNORECASE)),
]


class SecurityPIIAgent(BaseAgent):
    name = "security_pii"
    triggers = ("pii", "security", "redact", "sensitive", "scan")

    async def run(self, ctx: DocumentContext) -> AgentResult:
        text = ctx.selected_text
        suggestions: list[Suggestion] = []
        for label, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                suggestions.append(
                    Suggestion(
                        kind=f"pii:{label}",
                        message=f"Possible {label.replace('_', ' ')} found",
                        original=match.group(0),
                        replacement="[REDACTED]",
                        confidence=0.85,
                        span=(match.start(), match.end()),
                    )
                )
        summary = (
            f"Found {len(suggestions)} possible sensitive value(s)."
            if suggestions
            else "No sensitive patterns detected."
        )
        return AgentResult(agent_name=self.name, ok=True, suggestions=suggestions, summary=summary)
