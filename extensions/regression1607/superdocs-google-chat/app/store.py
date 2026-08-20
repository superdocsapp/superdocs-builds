"""In-memory review + digest state, keyed by Chat space so spaces stay isolated.

Google Chat CARD_CLICKED events are stateless, so item-by-item approvals need a
place to remember each change's decision between clicks. A review holds the job's
proposed changes and the reviewer's per-change decisions; the daily digest reads
what each space produced and what is still waiting so nothing sits silently.

A real deployment swaps this for a database; the interface is deliberately tiny
and every mutation is taken under a lock so two runs at once cannot corrupt it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class Change:
    change_id: str
    operation: str
    summary: str
    decision: str | None = None  # "approved" | "rejected" | None (undecided)


@dataclass
class Review:
    doc_title: str
    session_id: str
    job_id: str
    request: str
    changes: list[Change] = field(default_factory=list)
    state: str = "pending review"  # "pending review" | "applied" | "no changes"
    applied: int = 0
    rejected: int = 0
    durable_id: str | None = None  # File id of the produced doc, for later reference

    def decided(self) -> bool:
        return all(c.decision is not None for c in self.changes)


@dataclass
class _SpaceState:
    reviews: dict[str, Review] = field(default_factory=dict)  # keyed by session_id


class Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spaces: dict[str, _SpaceState] = {}

    def _space(self, space: str) -> _SpaceState:
        return self._spaces.setdefault(space, _SpaceState())

    def spaces(self) -> list[str]:
        with self._lock:
            return list(self._spaces.keys())

    def open_review(self, space: str, session_id: str, job_id: str, doc_title: str,
                    request: str, changes: list) -> Review:
        """``changes`` is a list of objects with change_id/operation/summary."""
        review = Review(
            doc_title=doc_title, session_id=session_id, job_id=job_id, request=request,
            changes=[Change(c.change_id, c.operation, c.summary) for c in changes],
        )
        with self._lock:
            self._space(space).reviews[session_id] = review
        return review

    def review(self, space: str, session_id: str) -> Review | None:
        with self._lock:
            return self._space(space).reviews.get(session_id)

    def recent_session(self, space: str) -> Review | None:
        """The space's most recently opened review — the session a follow-up
        ("revise it") should reuse for genuine document continuity."""
        with self._lock:
            reviews = list(self._space(space).reviews.values())
        return reviews[-1] if reviews else None

    def recent_source(self, space: str) -> Review | None:
        """The most recent produced document that has a durable File id — the one
        a "using last year's" request can open as a reference tab."""
        with self._lock:
            reviews = list(self._space(space).reviews.values())
        for r in reversed(reviews):
            if r.durable_id:
                return r
        return None

    def set_durable(self, space: str, session_id: str, durable_id: str | None) -> None:
        if not durable_id:
            return
        with self._lock:
            review = self._space(space).reviews.get(session_id)
            if review:
                review.durable_id = durable_id

    def set_decision(self, space: str, session_id: str, change_id: str, approved: bool) -> Review | None:
        with self._lock:
            review = self._space(space).reviews.get(session_id)
            if not review:
                return None
            for c in review.changes:
                if c.change_id == change_id:
                    c.decision = "approved" if approved else "rejected"
            return review

    def decide_all(self, space: str, session_id: str, approved: bool) -> Review | None:
        with self._lock:
            review = self._space(space).reviews.get(session_id)
            if not review:
                return None
            for c in review.changes:
                c.decision = "approved" if approved else "rejected"
            return review

    def mark_applied(self, space: str, session_id: str, applied: int, rejected: int,
                     state: str = "applied") -> None:
        with self._lock:
            review = self._space(space).reviews.get(session_id)
            if review:
                review.applied, review.rejected, review.state = applied, rejected, state

    def digest(self, space: str) -> tuple[list[dict], list[dict]]:
        with self._lock:
            reviews = list(self._space(space).reviews.values())
        produced, pending = [], []
        for r in reviews:
            if r.state == "pending review":
                undecided = sum(1 for c in r.changes if c.decision is None)
                pending.append({"title": r.doc_title,
                                "state": f"{undecided} change(s) awaiting review"})
            else:
                summary = ("ready — nothing to review" if r.state == "no changes"
                           else f"{r.applied} applied, {r.rejected} rejected")
                produced.append({"title": r.doc_title, "state": summary})
        return produced, pending
