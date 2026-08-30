"""Style / tone agent.

Rule-based readability and tone heuristics that run with no
external dependency. A real LLM refinement pass plugs in later
through llm_client.py without changing this agent's interface.
"""
from __future__ import annotations

import re

from .base import AgentResult, BaseAgent, DocumentContext, Suggestion

_PASSIVE = re.compile(r"\b(is|are|was|were|be|been|being)\s+\w+ed\b", re.IGNORECASE)
_FILLER = ("very", "really", "just", "actually", "basically")


class StyleToneAgent(BaseAgent):
    name = "style_tone"
    triggers = ("style", "tone", "rewrite", "clarity", "readability")

    async def run(self, ctx: DocumentContext) -> AgentResult:
        text = ctx.selected_text
        suggestions: list[Suggestion] = []

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        for sentence in sentences:
            words = sentence.split()
            if len(words) > 32:
                suggestions.append(
                    Suggestion(
                        kind="style:long_sentence",
                        message=f"{len(words)}-word sentence -- consider splitting it",
                        original=sentence,
                        confidence=0.6,
                    )
                )
            if _PASSIVE.search(sentence):
                suggestions.append(
                    Suggestion(
                        kind="style:passive_voice",
                        message="Passive construction -- consider an active rewrite",
                        original=sentence,
                        confidence=0.5,
                    )
                )
            for filler in _FILLER:
                if re.search(rf"\b{filler}\b", sentence, re.IGNORECASE):
                    suggestions.append(
                        Suggestion(
                            kind="style:filler_word",
                            message=f"Filler word '{filler}' adds little",
                            original=sentence,
                            confidence=0.4,
                        )
                    )
                    break

        summary = f"{len(suggestions)} style suggestion(s) from heuristics."
        return AgentResult(agent_name=self.name, ok=True, suggestions=suggestions, summary=summary)
