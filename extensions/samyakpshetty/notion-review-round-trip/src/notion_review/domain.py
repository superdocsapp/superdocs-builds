"""The typed domain for a review round.

A *review round* is the durable object at the centre of everything: a Notion page went out
as a Word document, came back marked up, and each reviewer change is now a :class:`ProposedChange`
moving through a human gate on its way back onto a specific Notion block.

The :class:`BlockMap` is the spine of the whole integration — it ties each Notion block to the
SuperDocs chunk that represents it, so an approved change lands on the *exact* block it came from
and nothing else is touched.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ChangeOperation(StrEnum):
    """How a change edits its block — mirrors SuperDocs' chunk-diff operations."""

    REPLACE = "replace"
    INSERT = "insert"
    INSERT_AFTER = "insert_after"
    DELETE = "delete"


class ChangeSource(StrEnum):
    """Where in the Word markup a change originated."""

    TRACKED_CHANGE = "tracked_change"  # a w:ins / w:del revision — the reviewer's exact text
    COMMENT_INTENT = "comment_intent"  # a comment SuperDocs' AI turned into a concrete edit
    COMMENT = "comment"  # a reviewer comment kept as an attributed Notion comment (fallback)


class ProposalStatus(StrEnum):
    PENDING = "pending"  # proposed by SuperDocs, awaiting the human gate
    APPROVED = "approved"  # human approved; queued for write-back
    REJECTED = "rejected"  # human rejected; never written
    APPLIED = "applied"  # written back to Notion and verified
    FAILED = "failed"  # write-back failed; round is resumable
    CONFLICT = "conflict"  # target block drifted; needs human resolution (Phase 2)


class RoundStatus(StrEnum):
    CREATED = "created"
    SENT = "sent"  # exported to Word, out with reviewers
    INGESTING = "ingesting"  # parsing returned markup / proposing changes
    AWAITING_APPROVAL = "awaiting_approval"  # at the item-by-item gate
    APPLYING = "applying"  # writing approved changes back to Notion
    COMPLETED = "completed"
    PARKED = "parked"  # budget/quota tripped; resumable
    FAILED = "failed"


class BlockMapEntry(BaseModel):
    """One Notion block ⇄ one SuperDocs chunk. The reversible link for write-back."""

    notion_block_id: str
    notion_page_id: str = ""  # which page in a multi-page packet this block belongs to
    block_type: str  # notion block type: paragraph, heading_1, toggle, callout, table_row...
    anchor: str  # our stable marker embedded in the HTML, survives the SuperDocs round-trip
    chunk_id: str | None = None  # SuperDocs data-chunk-id, filled after upload
    original_html: str = ""
    original_text: str = ""
    # Table rows only: the cell texts, in column order. A row is one chunk and one Notion
    # block, but Word gives each cell its own paragraph, so a reviewer edits a *cell*. Keeping
    # the cells here is what lets an edited cell be matched back to its row and column.
    cells: list[str] = Field(default_factory=list)


class Submission(BaseModel):
    """One returned copy of the review document, from one reviewer.

    A round goes out to several reviewers and each returns their own marked-up copy, so the unit
    of intake is the *submission*, not the round. The key is a content hash of the returned file:
    the same file arriving twice is a duplicate to ignore, while a different file for the same
    round is another reviewer whose changes must be taken in and merged.
    """

    key: str  # content hash of the returned .docx — the submission's identity
    filename: str = ""
    received_at: datetime = Field(default_factory=_now)
    reviewers: list[str] = Field(default_factory=list)  # who marked up this copy
    matched: int = 0  # changes located on a block
    unmatched: int = 0  # changes that could not be located, surfaced rather than guessed


class ProposedChange(BaseModel):
    """A single reviewer change, gated on its way back onto a Notion block."""

    id: str = Field(default_factory=lambda: _new_id("chg"))
    chunk_id: str
    change_id: str = ""  # SuperDocs' change id — what `approve` keys on
    notion_block_id: str
    notion_page_id: str = ""  # the page this change writes back to (multi-page packets)
    block_type: str = "paragraph"
    cell_index: int | None = None  # table rows: which column this change rewrites
    job_id: str = ""  # the SuperDocs chat job that proposed this change (needed to approve it)
    operation: ChangeOperation
    old_html: str = ""
    new_html: str = ""
    source: ChangeSource = ChangeSource.TRACKED_CHANGE
    reviewer_name: str = "Unknown reviewer"
    reviewer_comment: str = ""
    ai_explanation: str = ""  # SuperDocs' note when its AI authored the edit (comment-intent)
    links: list[str] = Field(default_factory=list)  # URLs the edit introduces; shown at the gate
    relayed: bool = False  # this decision has been sent to SuperDocs' approve (never sent twice)
    queue_row_id: str = ""  # the Notion review-queue row the owner decides this change in
    queue_row_url: str = ""  # link to that row, so the comment on the line is one click from it
    competing_notified: bool = False  # its row already says another reviewer rewrote this line
    discussion_id: str = ""  # the comment thread on the block, where the owner can reply instead
    status: ProposalStatus = ProposalStatus.PENDING
    error: str | None = None

    def content_key(self) -> str:
        """Stable idempotency key.

        Two proposals with the same target, operation, and resulting content are the *same*
        change: we never re-send one to SuperDocs or re-apply it to Notion. Normalised so
        insignificant whitespace never splits one change into two ops.
        """
        norm = " ".join(self.new_html.split())
        material = f"{self.notion_block_id}|{self.operation}|{norm}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class ReviewRound(BaseModel):
    """The durable centre of the workflow; persisted so a days-long round survives anything."""

    id: str = Field(default_factory=lambda: _new_id("round"))
    notion_page_id: str
    session_id: str = Field(default_factory=lambda: _new_id("sess"))
    status: RoundStatus = RoundStatus.CREATED
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    version: int = 1  # optimistic-concurrency guard: a stale write is rejected, never lost

    sent_version_id: str | None = None  # SuperDocs version exported to Word
    block_map: list[BlockMapEntry] = Field(default_factory=list)
    proposals: list[ProposedChange] = Field(default_factory=list)
    submissions: list[Submission] = Field(default_factory=list)  # each reviewer's returned copy

    ops_spent: int = 0  # SuperDocs operations consumed by this round
    review_url: str | None = None  # the round's queue in Notion — the page's link back to it
    queue_database_id: str = ""  # the in-Notion review queue the owner approves changes in
    bot_user_id: str = ""  # our own Notion identity, so a human's reply is told from our comment
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)  # where the time went

    def touch(self) -> None:
        self.updated_at = _now()

    def cost_summary(self) -> str:
        """A one-line account of what the round spent and where the time went (behaviour 10)."""
        stages = ", ".join(f"{name} {ms:.0f}ms" for name, ms in self.stage_timings_ms.items())
        ops = f"{self.ops_spent} SuperDocs op(s)"
        return f"{ops}; {stages}" if stages else ops

    def block_for_chunk(self, chunk_id: str) -> BlockMapEntry | None:
        return next((b for b in self.block_map if b.chunk_id == chunk_id), None)

    def page_ids(self) -> list[str]:
        """Every distinct page in this review packet, in first-seen order."""
        seen: dict[str, None] = {}
        for entry in self.block_map:
            seen.setdefault(entry.notion_page_id or self.notion_page_id, None)
        return list(seen)

    def pending(self) -> list[ProposedChange]:
        return [p for p in self.proposals if p.status == ProposalStatus.PENDING]

    def approved(self) -> list[ProposedChange]:
        return [p for p in self.proposals if p.status == ProposalStatus.APPROVED]

    def has_submission(self, key: str) -> bool:
        """Whether this exact returned file has already been taken in."""
        return any(s.key == key for s in self.submissions)

    def contested(self) -> dict[str, list[ProposedChange]]:
        """Pending changes competing for the same block — two reviewers rewriting one line.

        Only rewrites compete: a proposal that just carries a reviewer's comment does not change
        the block, so it contests nothing. Two reviewers who made the *identical* edit never reach
        here — :meth:`ProposedChange.content_key` collapses them into one proposal on the way in —
        so any block holding more than one pending rewrite holds genuinely different results.

        Applying one of them makes the block no longer read as it did when it went out, so the
        drift guard would refuse the others. Knowing that *before* deciding is the point: the
        owner is told these compete rather than discovering it from a conflict afterwards.
        """
        by_block: dict[str, list[ProposedChange]] = {}
        for proposal in self.pending():
            if proposal.source == ChangeSource.COMMENT:
                continue
            by_block.setdefault(proposal.notion_block_id, []).append(proposal)
        return {block: group for block, group in by_block.items() if len(group) > 1}
