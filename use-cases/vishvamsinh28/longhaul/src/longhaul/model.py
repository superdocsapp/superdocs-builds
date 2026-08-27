"""Core data model.

Every value here is something that survives a SIGKILL, so everything is either a
plain dataclass loaded from the ledger or a string constant written into it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


# --- Step lifecycle -------------------------------------------------------
#
# PLANNED -> ISSUING -> ISSUED -> PROPOSED -> GATED -> COMMITTING -> COMMITTED -> DONE
#
# The two windows that can lose an answer to a crash are ISSUING->ISSUED (unsafe
# to retry blindly: it applies a second edit) and COMMITTING->COMMITTED (safe to
# retry: an approve names changes that already exist). See CONTRACT.md.

PLANNED = "planned"
ISSUING = "issuing"
ISSUED = "issued"
PROPOSED = "proposed"
GATED = "gated"
COMMITTING = "committing"
COMMITTED = "committed"
DONE = "done"
REJECTED = "rejected"
FAILED = "failed"
ADJUDICATE = "adjudicate"

TERMINAL_STATES = frozenset({DONE, REJECTED, FAILED, ADJUDICATE})
#: States where a crash leaves an unanswered question on the wire.
IN_FLIGHT_STATES = frozenset({ISSUING, ISSUED, COMMITTING})

# Ordered, so the runner can tell "further along" from "further back".
STATE_ORDER = [
    PLANNED, ISSUING, ISSUED, PROPOSED, GATED, COMMITTING, COMMITTED, DONE,
]


# --- Dispositions (what the honest report says about a step) --------------

EXECUTED = "executed"
SKIPPED_LEDGER = "skipped: already-done (ledger)"
SKIPPED_RECONCILED = "skipped: already-done (reconciled)"
ADJUDICATE_DISPOSITION = "adjudicate"


# --- Run status -----------------------------------------------------------

RUN_PLANNED = "planned"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_BLOCKED = "blocked"
RUN_FAILED = "failed"


@dataclass(frozen=True)
class Document:
    """One document in the run's set, tracked from local file to SuperDocs id."""

    run_id: str
    slug: str
    source_path: str
    source_sha256: str
    title: str
    document_id: str | None = None
    state: str = "pending"


@dataclass
class Step:
    """One planned edit. The unit of durability."""

    run_id: str
    step_index: int
    step_id: str
    doc_slug: str
    instruction: str
    token: str
    state: str = PLANNED
    attempt: int = 0
    job_id: str | None = None
    disposition: str | None = None
    evidence: str | None = None
    pre_hash: str | None = None
    post_hash: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    billable_ops: int = 0
    duration_ms: int = 0
    error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


@dataclass(frozen=True)
class Proposal:
    """A change SuperDocs proposed, stored verbatim so the gate survives a crash."""

    run_id: str
    step_index: int
    change_id: str
    operation: str
    chunk_id: str | None
    document_id: str | None
    old_html: str
    new_html: str
    ai_explanation: str

    def to_public(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "operation": self.operation,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "old_html": self.old_html,
            "new_html": self.new_html,
            "ai_explanation": self.ai_explanation,
        }


@dataclass(frozen=True)
class Decision:
    """A human's (or a policy's) call on one proposed change."""

    run_id: str
    step_index: int
    change_id: str
    approved: bool
    feedback: str | None
    decided_by: str
    decided_at: float


@dataclass(frozen=True)
class Commit:
    """Append-only proof that one change was committed. The byte-identity oracle.

    Two runs of the same plan must produce the same ordered commit log, no matter
    how many times one of them was killed. Compared by :meth:`identity`, which
    deliberately excludes wall-clock fields.
    """

    seq: int
    run_id: str
    step_index: int
    change_id: str
    approved: bool
    document_id: str | None
    version: str | None
    at: float

    def identity(self) -> tuple[int, str, bool, str | None]:
        return (self.step_index, self.change_id, self.approved, self.document_id)


@dataclass
class Run:
    run_id: str
    spec_path: str
    spec_hash: str
    session_id: str
    status: str = RUN_PLANNED
    created_at: float = 0.0
    updated_at: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


def step_token(run_id: str, step_index: int) -> str:
    """The idempotency token carried inside the instruction text.

    Deterministic in ``(run_id, step_index)`` so it can be recomputed after a crash
    without reading anything, and distinctive enough to find by substring search in
    a session transcript. This token is what makes at-most-once possible: the act of
    the request landing echoes it into SuperDocs' own durable state, so after a crash
    the server can be asked whether the turn happened. See CONTRACT.md, window W1.
    """
    digest = hashlib.sha256(f"{run_id}\x00{step_index}".encode()).hexdigest()[:12]
    return f"[longhaul:{step_index:04d}:{digest}]"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
