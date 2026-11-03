"""
Draft versioning and redraft-with-feedback.

Before this module, a reviewer's only options for a drafted section were
approve or reject -- rejecting with feedback recorded the feedback in the
audit trail (see audit.py) but never actually sent that feedback back to
SuperDocs to produce a revised draft. This closes that loop: a reviewer
can ask for a specific section to be redrafted with their feedback, get
back a new version, and see a line-level diff against what it looked
like before -- without losing the previous version.

`VersionStore` persists every version of every item's drafted text (SQLAlchemy,
same engine-sharing pattern as `review_store.ReviewSessionStore` and
`webapp/jobs.JobStore` -- one database to provision, not three) so a
reviewer can redraft a section multiple times and still see the full
history, not just before/after.

`redraft_item()` sends the feedback as a new chat turn on the SAME
drafting session (unlike `judge.grade_draft`, which deliberately uses a
separate session -- redrafting is supposed to be part of the document's
own editing history, not isolated from it) and reuses
`review._interpret_job`'s parsing so a redraft's response is interpreted
identically to an initial draft.
"""
from __future__ import annotations

import difflib
import logging
import os
import time
from dataclasses import dataclass

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import Engine

from .superdocs_client import SuperDocsClient, SuperDocsError

logger = logging.getLogger("rfe_response_builder.versioning")

DEFAULT_VERSION_TTL_S = int(os.environ.get("VERSION_TTL_S", str(30 * 24 * 3600)))  # 30 days

_metadata = MetaData()

draft_versions = Table(
    "draft_versions",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("review_id", String(64), nullable=False),
    Column("request_id", String(32), nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("reply_text", String, nullable=False),
    Column("feedback", String, nullable=True),  # feedback that produced THIS version, if any (None for version 1)
    Column("created", Float, nullable=False),
)


@dataclass
class DraftVersion:
    id: int
    review_id: str
    request_id: str
    version_number: int
    reply_text: str
    feedback: str | None
    created: float


class VersionStore:
    def __init__(self, engine: Engine, ttl_s: int = DEFAULT_VERSION_TTL_S):
        self.engine = engine
        self.ttl_s = ttl_s
        _metadata.create_all(self.engine, tables=[draft_versions])

    def record(self, review_id: str, request_id: str, reply_text: str, feedback: str | None = None) -> int:
        """Appends a new version and returns its version_number (1-indexed,
        incrementing per (review_id, request_id))."""
        self._prune()
        existing = self.list_versions(review_id, request_id)
        version_number = len(existing) + 1
        with self.engine.begin() as conn:
            conn.execute(insert(draft_versions).values(
                review_id=review_id, request_id=request_id, version_number=version_number,
                reply_text=reply_text, feedback=feedback, created=time.time(),
            ))
        return version_number

    def _prune(self) -> None:
        """Deletes version rows older than `ttl_s` -- unlike
        `ReviewSessionStore`/`JobStore`, this table previously had no TTL
        at all, so a case redrafted many times (or many cases over a long
        deployment lifetime) accumulated rows indefinitely. Called on
        every `record()`, same "prune on write" pattern as
        `ReviewSessionStore.put`, so no separate cron/scheduler is needed."""
        cutoff = time.time() - self.ttl_s
        with self.engine.begin() as conn:
            conn.execute(delete(draft_versions).where(draft_versions.c.created < cutoff))

    def list_versions(self, review_id: str, request_id: str) -> list[DraftVersion]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(draft_versions)
                .where(draft_versions.c.review_id == review_id, draft_versions.c.request_id == request_id)
                .order_by(draft_versions.c.version_number)
            ).fetchall()
        return [DraftVersion(*row) for row in rows]

    def latest_version(self, review_id: str, request_id: str) -> DraftVersion | None:
        versions = self.list_versions(review_id, request_id)
        return versions[-1] if versions else None


def diff_versions(old_text: str, new_text: str) -> list[str]:
    """Line-level unified diff between two versions of a drafted section.
    Returns a plain list of diff lines (no HTML) -- the webapp template
    is responsible for rendering (color-coding +/- lines), keeping this
    function reusable from the CLI too. Empty list if the two texts are
    identical."""
    old_lines = old_text.splitlines(keepends=False)
    new_lines = new_text.splitlines(keepends=False)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    # Drop the two header lines (---/+++) when there's no actual content
    # difference -- unified_diff always emits headers even for identical
    # input if line counts differ trivially; an empty semantic diff
    # should read as "no changes", not two header lines with nothing
    # underneath.
    content_lines = [ln for ln in diff if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    return diff if content_lines else []


def redraft_item(client: SuperDocsClient, session_id: str, request_id: str, response_section: str,
                  feedback: str) -> tuple[str, str, str | None]:
    """Sends the reviewer's feedback back to SuperDocs as a new chat turn
    on the SAME drafting session, asking for a revision of one specific
    section. Returns (reply_text, status, chunk_id) using the exact same
    interpretation as `review._interpret_job` / `review.start_review`'s
    initial draft, so a redrafted item is handled identically to an
    initial one by the rest of the review flow.

    Raises `SuperDocsError` on a persistent failure (after
    `SuperDocsClient`'s own retry/backoff) -- unlike the grounding/quality
    checks, a failed redraft has no sensible "degrade gracefully" default;
    the caller must tell the reviewer the redraft didn't happen so they
    don't mistake the old version for a new one.
    """
    # Imported here (not at module load) to avoid a circular import --
    # review.py imports this module for VersionStore/diff_versions, and
    # this function needs review.py's job-interpretation helper.
    from .review import STATUS_PENDING_REVIEW, _interpret_job

    instruction = (
        f"Revise your previous draft for \"{response_section}\" based on this reviewer feedback: "
        f"\"{feedback}\"\n\nKeep the revision grounded in the same source material you were given "
        f"originally -- do not invent new facts, evidence, or citations to satisfy the feedback."
    )
    job_id = client.chat_async(session_id=session_id, message=instruction, approval_mode="ask_every_time")
    job = client.wait_for_job(job_id)
    reply_text, status, chunk_id = _interpret_job(job)
    if status != STATUS_PENDING_REVIEW:
        logger.warning("redraft for session %s did not return a pending-approval change (status=%s)",
                        session_id, status)
    return reply_text, status, chunk_id
