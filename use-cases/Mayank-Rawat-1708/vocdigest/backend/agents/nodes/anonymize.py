"""
@file: backend/agents/nodes/anonymize.py
@description: Selects representative quotes per theme and anonymizes them. Picks quotes
    by diversity (nearest to centroid, plus the most and least severe) so the digest
    shows range rather than three phrasings of the same complaint. Anything the
    anonymizer was unsure about is preserved as [POSSIBLE-NAME] and surfaced for review.
@flow: run() -> for each theme select up to N candidate conversations -> anonymize each
    quote (regex then LLM) -> store on Theme.representative_quotes with its redaction
    list and needs_review flag -> count how many need human eyes.
@dependencies:
    - backend.services.anonymizer.Anonymizer: the two-pass redactor
    - backend.services.vector_store.cosine_similarity: centroid-proximity selection
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from backend.agents.nodes.base import BaseNode, NodeInputMissing
from backend.agents.state import DigestState
from backend.config import settings
from backend.db.database import session_scope
from backend.models import Conversation, RunStatus, Theme
from backend.services.anonymizer import Anonymizer
from backend.services.groq_client import GroqClient
from backend.services.llm_gate import groq_available
from backend.services.vector_store import cosine_similarity

logger = logging.getLogger(__name__)

QUOTES_PER_THEME = 3
# Quotes shorter than this are usually fragments ("still broken") and carry no signal
# for a reader, so they are skipped in favour of a fuller one.
MIN_QUOTE_CHARS = 40


class AnonymizeNode(BaseNode):
    stage = "anonymize"
    running_status = RunStatus.ANONYMIZING
    requires = ("theme",)

    async def run(self, state: DigestState, run_id: uuid.UUID) -> DigestState:
        async with session_scope() as session:
            themes = list(
                (
                    await session.execute(select(Theme).where(Theme.run_id == run_id))
                ).scalars()
            )
            if not themes:
                raise NodeInputMissing(
                    "No themes to draw quotes from. The theme stage produced nothing, "
                    "so there are no quotes to anonymize and nothing to publish.",
                    upstream_stage="theme",
                )

            # Regex redaction (emails, phones, URLs, ids) needs no model and must never
            # be lost to an outage — those are the highest-confidence redactions and
            # losing them silently would be a privacy failure, not a quality one. Only
            # name/company detection depends on the LLM.
            use_llm = groq_available()
            groq = GroqClient() if use_llm else None
            anonymizer = Anonymizer(groq)
            total = 0
            needing_review = 0
            degraded = not use_llm

            try:
                # Select quotes for every theme first, then anonymize theme-by-theme
                # with one LLM call per theme and several themes in flight at once.
                # The previous shape was one sequential call per quote — on a
                # 200-conversation run that meant ~144 round trips and minutes of wall
                # clock for work that is entirely parallelisable.
                selections: list[tuple[Theme, list[Conversation]]] = []
                for theme in themes:
                    members = list(
                        (
                            await session.execute(
                                select(Conversation).where(
                                    Conversation.theme_id == theme.id
                                )
                            )
                        ).scalars()
                    )
                    selections.append((theme, self._select_quotes(theme, members)))

                # Bounded concurrency: enough to hide latency, low enough not to trip
                # the provider's rate limit, which would cost more in backoff than the
                # parallelism saves.
                semaphore = asyncio.Semaphore(settings.anonymize_concurrency)

                async def _process(convs: list[Conversation]):
                    async with semaphore:
                        return await anonymizer.anonymize_many(
                            [c.raw_text for c in convs], use_llm=use_llm
                        )

                batches = await asyncio.gather(
                    *(_process(convs) for _, convs in selections)
                )

                for (theme, convs), results in zip(selections, batches):
                    quotes = []
                    for conv, result in zip(convs, results):
                        self.usage.merge(result.usage)
                        total += 1
                        if result.needs_review:
                            needing_review += 1
                        quotes.append(
                            {
                                "conversation_id": str(conv.id),
                                "citation": conv.citation,
                                "date": conv.occurred_at.date().isoformat()
                                if conv.occurred_at
                                else None,
                                "anonymized": result.anonymized,
                                "redaction_count": len(result.redactions),
                                "redactions": [r.to_dict() for r in result.redactions],
                                "uncertain_spans": result.uncertain_spans,
                                "needs_review": result.needs_review,
                            }
                        )
                    theme.representative_quotes = quotes
            finally:
                if groq is not None:
                    await groq.aclose()

            await session.flush()

        await self.log_decision(
            run_id,
            "ANONYMIZED",
            f"Anonymized {total} quotes across {len(themes)} themes; "
            f"{needing_review} flagged for human review",
            {"total": total, "needing_review": needing_review},
        )
        if needing_review:
            # Explicitly not claiming guaranteed PII removal — the gate is the control.
            await self.log_decision(
                run_id,
                "UNCERTAIN_REDACTION",
                f"{needing_review} quote(s) contain spans the anonymizer could not "
                f"classify with confidence; marked [POSSIBLE-NAME] for reviewer decision",
                {"count": needing_review},
            )

        if degraded:
            note = (
                "Name and company detection was unavailable (no language model), so only "
                "pattern-based redaction ran. Emails, phone numbers, URLs and identifiers "
                "were still removed, but personal names may remain."
            )
            await self.log_decision(
                run_id, "DEGRADED",
                f"Anonymization ran pattern-only. {note}",
                {"caveats": [note]},
            )
            state["degraded_stages"] = sorted(
                set(state.get("degraded_stages") or []) | {"anonymize"}
            )
            state["degraded_caveats"] = list(
                dict.fromkeys((state.get("degraded_caveats") or []) + [note])
            )

        state["quotes_anonymized"] = total
        state["quotes_needing_review"] = needing_review
        return state

    @staticmethod
    def _select_quotes(
        theme: Theme, members: list[Conversation]
    ) -> list[Conversation]:
        """Pick quotes that show the theme's range, not three copies of one complaint."""
        usable = [c for c in members if len(c.raw_text) >= MIN_QUOTE_CHARS]
        if not usable:
            usable = list(members)
        if len(usable) <= QUOTES_PER_THEME:
            return usable

        # Most representative: closest to the theme centroid.
        if theme.embedding is not None:
            centroid_vec = list(theme.embedding)
            usable.sort(
                key=lambda c: cosine_similarity(list(c.embedding or []), centroid_vec),
                reverse=True,
            )

        picked = [usable[0]]
        # Add the highest-severity and a distinct middle example for range.
        by_severity = sorted(
            usable[1:],
            key=lambda c: {"high": 0, "medium": 1, "low": 2}.get(
                str((c.extracted_facts or {}).get("severity", "low")), 3
            ),
        )
        for conv in by_severity:
            if len(picked) >= QUOTES_PER_THEME:
                break
            if conv.id not in {p.id for p in picked}:
                picked.append(conv)
        return picked[:QUOTES_PER_THEME]