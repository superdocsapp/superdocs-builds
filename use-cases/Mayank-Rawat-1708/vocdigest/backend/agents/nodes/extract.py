"""
@file: backend/agents/nodes/extract.py
@description: Extracts structured facts from each relevant conversation (issue summary,
    product area, sentiment, whether the customer was blocked) and embeds the text into
    pgvector so the theming stage can cluster by meaning.
@flow: run() -> batch relevant conversations -> LLM extracts facts per row, content
    fenced -> write extracted_facts JSONB -> embed_conversations() fills the vector
    column -> report counts.
@dependencies:
    - backend.services.groq_client.GroqClient: fact extraction
    - backend.services.vector_store: embedding generation into pgvector
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from backend.agents.nodes.base import BaseNode, NodeInputMissing
from backend.agents.state import DigestState
from backend.config import settings
from backend.db.database import session_scope
from backend.models import Conversation, RunStatus
from backend.services.batching import indexed_json_call
from backend.services.groq_client import GroqClient
from backend.services.heuristics import heuristic_extract
from backend.services.llm_gate import run_with_fallback
from backend.services.vector_store import embed_conversations

logger = logging.getLogger(__name__)

# Completion tokens one extracted record needs: five fields, one of them a short noun
# phrase, plus JSON punctuation. Measured at 70 tokens/record on a live 8-record batch
# (556 completion tokens), so 72 left no margin at all for a record with a longer issue
# phrase — and running out mid-answer costs the whole batch, not one record. Rounded up
# on purpose; see CLASSIFY_TOKENS_PER_RECORD.
EXTRACT_TOKENS_PER_RECORD = 96

_SYSTEM = """\
You extract structured facts from customer-support conversations.

For each numbered record return:
  issue: one short noun phrase naming the core problem (e.g. "export fails silently")
  product_area: the surface involved (e.g. "export", "dashboard", "notifications",
                "mobile app", "billing", "other")
  sentiment: "frustrated" | "neutral" | "positive"
  blocked: true if the customer cannot complete their task at all
  severity: "high" | "medium" | "low"

Return ONLY:
{"results": [{"index": <int>, "issue": "...", "product_area": "...",
              "sentiment": "...", "blocked": <bool>, "severity": "..."}]}

Base every field on what the record actually says. If a field is not determinable from
the text, use "unknown" rather than guessing.
"""


class ExtractNode(BaseNode):
    stage = "extract"
    running_status = RunStatus.EXTRACTING
    requires = ("ingest", "classify")

    async def run(self, state: DigestState, run_id: uuid.UUID) -> DigestState:
        async with session_scope() as session:
            rows = list(
                (
                    await session.execute(
                        select(Conversation).where(
                            Conversation.run_id == run_id,
                            Conversation.is_relevant.is_(True),
                        )
                    )
                ).scalars()
            )

            if not rows:
                # Not a skip. Every stage after this one is built from extracted facts,
                # so "nothing to extract" is not a stage with no work — it is a run with
                # no subject. Producing an empty result here is what let a failed
                # classify walk all the way to an approval gate holding nothing.
                raise NodeInputMissing(
                    "No relevant conversations to extract facts from. Either every "
                    "ingested record was filtered out as non-support content, or the "
                    "classify stage did not complete. There is nothing to analyse, so "
                    "the run stops here rather than producing an empty digest."
                )

            pending = [c for c in rows if not c.extracted_facts]
            degraded_reason = ""
            degraded_caveats: list[str] = []
            batch_size = settings.llm_batch_size

            for start in range(0, len(pending), batch_size):
                batch = pending[start : start + batch_size]

                async def _llm(_batch=batch):
                    groq = GroqClient()
                    try:
                        outcome = await indexed_json_call(
                            groq,
                            system=_SYSTEM,
                            instruction=lambda n: (
                                f"Extract facts from these {n} records."
                            ),
                            records=[c.raw_text for c in _batch],
                            per_record_output_tokens=EXTRACT_TOKENS_PER_RECORD,
                            max_output_tokens=3072,
                        )
                        if outcome.splits:
                            logger.info(
                                "Extract sent %d requests (batch of %d split %d time(s) "
                                "to stay under the provider's token ceiling)",
                                outcome.calls, len(_batch), outcome.splits,
                            )
                        return (
                            {"results": list(outcome.results.values())},
                            outcome.usage,
                        )
                    finally:
                        await groq.aclose()

                gated = await run_with_fallback(
                    "extract", _llm,
                    lambda _b=batch: heuristic_extract([c.raw_text for c in _b]),
                )
                payload = gated.data
                self.usage.merge(gated.usage)
                if gated.degraded:
                    degraded_reason = gated.reason
                    degraded_caveats = gated.caveats

                results = {}
                if isinstance(payload, dict):
                    for item in payload.get("results", []) or []:
                        try:
                            results[int(item["index"])] = item
                        except (KeyError, TypeError, ValueError):
                            continue

                for i, conv in enumerate(batch):
                    facts = results.get(i)
                    if facts is None:
                        # Explicit unknown beats a fabricated fact.
                        conv.extracted_facts = {
                            "issue": "unknown",
                            "product_area": "unknown",
                            "sentiment": "unknown",
                            "blocked": None,
                            "severity": "unknown",
                            "note": "model returned no extraction for this record",
                        }
                        continue
                    conv.extracted_facts = {
                        "issue": str(facts.get("issue", "unknown"))[:300],
                        "product_area": str(facts.get("product_area", "unknown"))[:100],
                        "sentiment": str(facts.get("sentiment", "unknown"))[:32],
                        "blocked": facts.get("blocked"),
                        "severity": str(facts.get("severity", "unknown"))[:16],
                    }

            await session.flush()
            embedded = await embed_conversations(session, run_id)
            extracted = sum(1 for c in rows if c.extracted_facts)

        await self.log_decision(
            run_id,
            "EXTRACTED",
            f"Extracted facts from {extracted} conversations, embedded {embedded}",
            {"extracted": extracted, "embedded": embedded},
        )

        if degraded_reason:
            await self.log_decision(
                run_id, "DEGRADED",
                f"Fact extraction ran without a language model ({degraded_reason}).",
                {"caveats": degraded_caveats},
            )
            state["degraded_stages"] = sorted(
                set(state.get("degraded_stages") or []) | {"extract"}
            )
            state["degraded_caveats"] = list(
                dict.fromkeys((state.get("degraded_caveats") or []) + degraded_caveats)
            )

        state["facts_extracted"] = extracted
        state["conversations_embedded"] = embedded
        return state
