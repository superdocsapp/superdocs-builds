"""Structure / dependency agent.

v0 interface stub. This is where SuperDocs' proposed "Document OS"
concept plugs in -- semantic twin, dependency graph, and
impact/scenario analysis. Wire the real analyzer in behind this
same interface; for now it returns a well-formed review flag so
the orchestrator always gets a valid AgentResult back even before
the analyzer exists.
"""
from __future__ import annotations

from .base import AgentResult, BaseAgent, DocumentContext, Suggestion


class StructureDependencyAgent(BaseAgent):
    name = "structure_dependency"
    triggers = ("dependency", "impact", "structure", "cross-reference")

    async def run(self, ctx: DocumentContext) -> AgentResult:
        suggestion = Suggestion(
            kind="structure:needs_review",
            message="Flag for manual dependency/impact review -- analyzer not yet wired in",
            original=ctx.selected_text,
            confidence=0.3,
        )
        return AgentResult(
            agent_name=self.name,
            ok=True,
            suggestions=[suggestion],
            summary="Structural analysis is a v0 stub -- see README's Document OS notes.",
        )
