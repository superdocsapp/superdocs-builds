"""
@file: backend/agents/nodes/human_gate.py
@description: The approval gate. Pauses the graph, writes one ApprovalItem per thing a
    human should decide on (themes, quotes needing review, findings, section updates),
    and refuses to continue until every item has a decision. Rejecting one item never
    discards the rest — each row carries its own status and the draft is assembled from
    whatever survived.
@flow: First entry -> create ApprovalItems from the draft and themes -> if zero items
    were created the run FAILS (nothing to review means nothing to publish) -> otherwise
    raise NodePause so the run status becomes AWAITING_APPROVAL and control returns to
    the caller. Resume entry -> re-enter, find items already decided -> filter the draft
    to approved content -> continue.
@dependencies:
    - backend.models.ApprovalItem: the gate's persisted units
    - backend.agents.nodes.base.NodePause: the mechanism that suspends the graph
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from backend.agents.nodes.base import BaseNode, NodeInputMissing, NodePause
from backend.agents.state import DigestState
from backend.db.database import session_scope
from backend.models import (
    ApprovalItem,
    ApprovalItemType,
    ApprovalStatus,
    RunStatus,
    Theme,
)

logger = logging.getLogger(__name__)


class HumanGateNode(BaseNode):
    stage = "human_gate"
    running_status = RunStatus.AWAITING_APPROVAL
    requires = ("draft",)

    async def run(self, state: DigestState, run_id: uuid.UUID) -> DigestState:
        async with session_scope() as session:
            existing = list(
                (
                    await session.execute(
                        select(ApprovalItem).where(ApprovalItem.run_id == run_id)
                    )
                ).scalars()
            )

            created = 0
            if not existing:
                created = await self._create_items(session, run_id, state)
                await session.flush()
                state["approval_items_created"] = created

        if not existing:
            # "No items exist" and "no items are possible" are different states, and
            # conflating them is what made this node loop. The old test was only
            # "do items exist?" — so a gate that created zero found zero again on every
            # re-entry, created zero again, and paused again, forever: never progressing,
            # never failing, and unresolvable from the UI because there was nothing to
            # click. gate_opened records that creation has already been attempted.
            already_attempted = bool(state.get("gate_opened"))
            state["gate_opened"] = True

            if created == 0:
                # A gate with nothing in it is not a gate. There is nothing for a human
                # to approve, which means there is nothing to publish — so this is a
                # failed run, not a paused one. Pausing here presents an empty review
                # queue as though it were a normal waiting state.
                raise NodeInputMissing(
                    "The approval gate has nothing to review: no themes and no draft "
                    "sections survived the pipeline, so zero approval items could be "
                    "created. Nothing can be approved and nothing can be published. "
                    + (
                        "This gate was already opened once with nothing in it, so "
                        "re-entering cannot change the outcome. "
                        if already_attempted
                        else ""
                    )
                    + "Check the earlier stages: this state means an upstream stage "
                    "produced no output.",
                    upstream_stage="draft",
                )

            await self.log_decision(
                run_id,
                "GATE_OPENED",
                f"Created {created} items for human review. "
                f"Run paused until every item has a decision.",
                {"items": created},
            )
            # Suspend here. Everything completed so far is checkpointed, so resuming
            # re-enters this node rather than replaying the pipeline.
            raise NodePause(
                "Awaiting human approval", status=RunStatus.AWAITING_APPROVAL
            )

        pending = [i for i in existing if i.status == ApprovalStatus.PENDING]
        if pending:
            await self.log_decision(
                run_id,
                "GATE_BLOCKED",
                f"{len(pending)} of {len(existing)} approval items still undecided",
                {"pending": len(pending)},
            )
            raise NodePause(
                f"{len(pending)} approval item(s) still pending",
                status=RunStatus.AWAITING_APPROVAL,
            )

        approved = [i for i in existing if i.status == ApprovalStatus.APPROVED]
        rejected = [i for i in existing if i.status == ApprovalStatus.REJECTED]

        # Drop rejected content from the draft. Export still works with whatever remains
        # — a rejection removes a section, it does not abort the digest.
        sections = dict(state.get("draft_sections") or {})
        removed_keys: list[str] = []
        for item in rejected:
            key = (item.content or {}).get("section_key")
            if key and key in sections:
                sections.pop(key)
                removed_keys.append(key)

        state["draft_sections"] = sections
        state["approval_items_approved"] = len(approved)
        state["approval_items_rejected"] = len(rejected)
        state["gate_resolved"] = True

        await self.log_decision(
            run_id,
            "GATE_RESOLVED",
            f"{len(approved)} approved, {len(rejected)} rejected. "
            f"Removed sections: {removed_keys or 'none'}",
            {
                "approved": len(approved),
                "rejected": len(rejected),
                "removed_sections": removed_keys,
            },
        )
        return state

    async def _create_items(
        self, session, run_id: uuid.UUID, state: DigestState
    ) -> int:
        """Build the review queue.

        Item types are separated so the UI can group them: a reviewer scanning quotes
        for leaked names is doing a different job from one sanity-checking a theme.
        """
        themes = list(
            (
                await session.execute(
                    select(Theme)
                    .where(Theme.run_id == run_id)
                    .order_by(Theme.volume_count.desc())
                )
            ).scalars()
        )
        sections = state.get("draft_sections") or {}
        items: list[ApprovalItem] = []

        for idx, theme in enumerate(themes, start=1):
            items.append(
                ApprovalItem(
                    run_id=run_id,
                    item_type=ApprovalItemType.THEME,
                    content={
                        "section_key": f"theme_{idx}",
                        "theme_id": str(theme.id),
                        "name": theme.name,
                        "description": theme.description,
                        "volume": theme.volume_count,
                        "trend": theme.volume_trend.value,
                        "growth_rate": theme.growth_rate,
                        "prior_count": theme.prior_quarter_count,
                        "evidence_count": len(theme.evidence_refs or []),
                        "evidence_refs": (theme.evidence_refs or [])[:8],
                        "confidence_note": theme.confidence_note,
                    },
                )
            )

            # Only quotes the anonymizer was unsure about become their own gate item.
            # Surfacing every clean quote would bury the ones that actually need eyes.
            for quote in theme.representative_quotes or []:
                if not quote.get("needs_review"):
                    continue
                items.append(
                    ApprovalItem(
                        run_id=run_id,
                        item_type=ApprovalItemType.QUOTE,
                        content={
                            "theme_id": str(theme.id),
                            "theme_name": theme.name,
                            "anonymized": quote.get("anonymized"),
                            "citation": quote.get("citation"),
                            "uncertain_spans": quote.get("uncertain_spans", []),
                            "redactions": quote.get("redactions", []),
                            "reason": (
                                "Anonymizer could not classify one or more spans with "
                                "confidence; they are marked [POSSIBLE-NAME]."
                            ),
                        },
                    )
                )

        for key in ("executive_summary", "fastest_growing", "what_changed", "methodology"):
            if key in sections:
                items.append(
                    ApprovalItem(
                        run_id=run_id,
                        item_type=ApprovalItemType.FINDING
                        if key != "what_changed"
                        else ApprovalItemType.UPDATE,
                        content={
                            "section_key": key,
                            "title": key.replace("_", " ").title(),
                            "instruction_preview": sections[key][:1200],
                        },
                    )
                )

        session.add_all(items)
        return len(items)
