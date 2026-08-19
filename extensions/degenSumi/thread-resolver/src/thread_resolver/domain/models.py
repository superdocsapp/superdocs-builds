"""Core vocabulary of the resolver.

This module is pure: no network, no filesystem, no XML. Everything here is data
plus functions over that data, which keeps the rules that matter cheap to test.

All types are frozen. Pipeline state is checkpointed between stages and reloaded
on resume, so a stage that could mutate an earlier stage's data would make a
resumed run diverge from a fresh one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Disposition(StrEnum):
    """What a thread is judged to be, which decides whether an edit may be drafted.

    Exactly one is assigned per thread. Only ACTIONABLE ever reaches the editor.
    """

    ACTIONABLE = "actionable"
    """One clear intent, no unresolved disagreement. An edit may be drafted."""

    CONTESTED = "contested"
    """Participants disagree. Surfaced for a person; never resolved automatically."""

    UNCLEAR = "unclear"
    """Intent could not be established. Distinct from CONTESTED, which is a
    positive finding of disagreement; this one claims nothing beyond its own
    uncertainty. Also surfaced for a person."""

    QUESTION = "question"
    """Asks something rather than requesting a change. No edit is implied."""

    UNANCHORED = "unanchored"
    """The commented passage is no longer present. No edit can be grounded in it."""

    QUARANTINED = "quarantined"
    """Comment text attempts to instruct the system. Reported, never obeyed."""


class Decision(StrEnum):
    """A person's ruling on one review item."""

    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    """Left open: neither applied nor closed."""


@dataclass(frozen=True, slots=True)
class Comment:
    """A single comment. Threads are built from one root plus its replies."""

    comment_id: str
    """Word's w:id for the comment, unique within the document."""

    para_id: str | None
    """w14:paraId, the durable identity used to link a reply to its parent.

    None for documents written by tools that omit the extended comment part,
    in which case reply structure cannot be recovered.
    """

    author: str
    text: str
    created: datetime | None = None

    def __post_init__(self) -> None:
        if not self.comment_id:
            raise ValueError("comment_id is required")


@dataclass(frozen=True, slots=True)
class Anchor:
    """The passage a thread is attached to.

    `text` is captured at read time. It is compared against the live document
    before an edit is drafted, because a comment whose passage has since been
    deleted or rewritten cannot be grounded in the source.
    """

    text: str
    paragraph_index: int
    """Zero-based position of the anchored paragraph in body order."""

    chunk_id: str | None = None
    """Identifier assigned by the editing service, once the document is uploaded."""

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class Thread:
    """A root comment with its ordered replies, and the passage it points at."""

    root: Comment
    replies: tuple[Comment, ...] = ()
    anchor: Anchor | None = None
    resolved: bool = False
    """Mirrors w15:done. Resolved threads are skipped rather than reprocessed."""

    @property
    def thread_id(self) -> str:
        return self.root.comment_id

    @property
    def is_open(self) -> bool:
        return not self.resolved

    @property
    def comments(self) -> tuple[Comment, ...]:
        return (self.root, *self.replies)

    @property
    def participants(self) -> frozenset[str]:
        return frozenset(c.author for c in self.comments)

    @property
    def has_replies(self) -> bool:
        return bool(self.replies)

    def transcript(self) -> str:
        """The thread rendered as plain text, for classification.

        Authors are included because who said what carries the disagreement:
        one person asking for a cut and another objecting is the case that must
        never be resolved automatically.
        """
        return "\n".join(f"{c.author}: {c.text}" for c in self.comments)

    def content_hash(self) -> str:
        """Stable identity for the thread's content.

        Used to skip work already done for identical input, so that re-running
        after an interruption does not spend a second operation on a thread
        whose text has not changed.
        """
        material = "␟".join(
            (
                self.thread_id,
                *(f"{c.comment_id}:{c.author}:{c.text}" for c in self.comments),
                self.anchor.text if self.anchor else "",
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class DocumentPayload:
    """The document as bytes, ready to hand to an editing service."""

    filename: str
    data: bytes

    def __post_init__(self) -> None:
        if not self.filename:
            raise ValueError("filename is required")


@dataclass(frozen=True, slots=True)
class Classification:
    """The judgement made about one thread, and the reasoning behind it."""

    disposition: Disposition
    reason: str
    """Human-readable justification, shown in the review gate."""

    decided_by: str
    """Which classifier settled it, e.g. "rule:injection" or "model"."""

    instruction: str | None = None
    """The edit to request, present only when the disposition is ACTIONABLE."""

    def __post_init__(self) -> None:
        if self.disposition is Disposition.ACTIONABLE and not self.instruction:
            raise ValueError("an actionable thread must carry an instruction")
        if self.disposition is not Disposition.ACTIONABLE and self.instruction:
            raise ValueError(f"{self.disposition} must not carry an instruction")


@dataclass(frozen=True, slots=True)
class ProposedEdit:
    """One change the editing service offers, awaiting a person's decision."""

    change_id: str
    chunk_id: str | None
    operation: str
    old_html: str
    new_html: str
    explanation: str

    @property
    def is_noop(self) -> bool:
        return self.old_html == self.new_html


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """A thread as it is put in front of a person: judgement, edit, decision.

    Non-actionable threads appear here too, carrying no edit. They are decisions
    to make rather than changes to apply, which is what keeps disagreement
    visible instead of silently dropped.
    """

    thread: Thread
    classification: Classification
    proposed_edits: tuple[ProposedEdit, ...] = ()
    decision: Decision | None = None
    job_id: str | None = None
    session_id: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def thread_id(self) -> str:
        return self.thread.thread_id

    @property
    def is_decided(self) -> bool:
        return self.decision is not None

    @property
    def closes_thread(self) -> bool:
        """Whether applying this item should mark the thread resolved.

        Only an approved edit closes a thread. Rejecting an edit, or approving a
        finding that carries no edit, leaves the thread open for a person.
        """
        return self.decision is Decision.APPROVE and bool(self.proposed_edits)

    def with_decision(self, decision: Decision) -> ReviewItem:
        """Return a copy carrying the decision; the original is left untouched."""
        return ReviewItem(
            thread=self.thread,
            classification=self.classification,
            proposed_edits=self.proposed_edits,
            decision=decision,
            job_id=self.job_id,
            session_id=self.session_id,
            notes=self.notes,
        )
