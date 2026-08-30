"""Evidence / fact-check agent.

v0 interface stub -- the provenance/citation-grounding half of the
Document OS concept. Same pattern as structure_dependency.py: a
well-formed result today, a real grounding pipeline (e.g. RAG over
the document's cited sources) plugs in behind the same interface.
"""
from __future__ import annotations

from .base import AgentResult, BaseAgent, DocumentContext, Suggestion


class EvidenceFactCheckAgent(BaseAgent):
    name = "evidence_factcheck"
    triggers = ("evidence", "citation", "fact-check", "source", "verify")

    async def run(self, ctx: DocumentContext) -> AgentResult:
        suggestion = Suggestion(
            kind="evidence:needs_review",
            message="Flag for manual citation/evidence review -- grounding pipeline not yet wired in",
            original=ctx.selected_text,
            confidence=0.3,
        )
        return AgentResult(
            agent_name=self.name,
            ok=True,
            suggestions=[suggestion],
            summary="Evidence grounding is a v0 stub -- see README for the RAG integration point.",
        )
