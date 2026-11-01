"""Base interface every specialist agent implements.

An agent receives a DocumentContext (the selected text, the user's
command, and any surrounding document text) and returns an
AgentResult: a verdict plus zero or more suggested edits. Agents
never touch the document directly -- the orchestrator applies
approved edits, and SuperDocs' own approve/reject/revert layer
(see redline-review) owns final application.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentContext:
    selected_text: str
    command: str
    surrounding_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Suggestion:
    kind: str
    message: str
    original: str
    replacement: str | None = None
    confidence: float = 1.0
    span: tuple[int, int] | None = None


@dataclass
class AgentResult:
    agent_name: str
    ok: bool
    suggestions: list[Suggestion] = field(default_factory=list)
    summary: str = ""
    error: str | None = None


class BaseAgent:
    """All specialist agents subclass this."""

    name: str = "base"
    #: keywords/commands this agent responds to; the orchestrator's
    #: router uses this for v0 intent matching (swap for an
    #: LLM-based classifier later without changing any agent).
    triggers: tuple[str, ...] = ()

    def handles(self, ctx: DocumentContext) -> bool:
        command = ctx.command.lower()
        return any(t in command for t in self.triggers)

    async def run(self, ctx: DocumentContext) -> AgentResult:
        raise NotImplementedError
