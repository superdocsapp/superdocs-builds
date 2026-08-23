"""The review, in memory. It does not survive a restart, and that is the design.

The pane holds names, diagnoses, account numbers. Writing them to a database to
read back tomorrow is a liability — the review lasts as long as the pane is open.
What survives is the log in `store.py`: who removed what, from where, in which
document, and deliberately nothing else.

Sessions are capped and evicted oldest-first, so a reload abandons the old one
rather than accumulating every document ever scanned.

See extensions/redaction-pane/README.md § "What is stored, and what is not".
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock

MAX_SESSIONS = 8
"""One reviewer, one document at a time, plus room for a few abandoned reloads.
Small on purpose: this is a single-user task pane, not a service."""


@dataclass
class Candidate:
    """One thing to ask a human about. Mutable — the answer is recorded on it."""

    id: str
    key: str
    chunk_id: str
    part_type: str
    category: str
    kind: str
    detector: str
    confidence: float
    text: str
    char_start: int
    char_end: int
    sentence: str
    marker: str
    """What Word writes in its place. Computed once, here, so the pane, the
    document and the log cannot disagree about what was left behind."""
    status: str = "pending"


@dataclass
class Session:
    id: str
    filename: str
    document_hash: str
    reviewer: str
    candidates: OrderedDict[str, Candidate] = field(default_factory=OrderedDict)
    """Keyed by candidate id, insertion-ordered — which is document order within
    a scan, and scan order across them."""


class Review:
    """Every open review in this process. One lock, because a task pane can and
    does fire two decisions before the first response lands."""

    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._max = max_sessions
        self._lock = Lock()

    def open(self, *, filename: str, document_hash: str, reviewer: str) -> Session:
        session = Session(
            id=str(uuid.uuid4()),
            filename=filename,
            document_hash=document_hash,
            reviewer=reviewer,
        )
        with self._lock:
            self._sessions[session.id] = session
            while len(self._sessions) > self._max:
                self._sessions.popitem(last=False)
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                self._sessions.move_to_end(session_id)
            return session

    def candidate(self, candidate_id: str) -> tuple[Session, Candidate] | None:
        """Ids are UUIDs, so one lookup across sessions is unambiguous and the
        pane never has to send a session id with a decision."""
        with self._lock:
            for session in self._sessions.values():
                found = session.candidates.get(candidate_id)
                if found is not None:
                    return session, found
        return None

    def add(self, session: Session, found: list[Candidate]) -> list[Candidate]:
        """Insert what is new, leave answered candidates alone. On a re-scan the
        same candidates come back beside the new one; replacing them would reset
        decisions a person already made."""
        with self._lock:
            known = {candidate.key for candidate in session.candidates.values()}
            fresh = [candidate for candidate in found if candidate.key not in known]
            for candidate in fresh:
                session.candidates[candidate.id] = candidate
        return fresh

    def decide(self, candidate: Candidate, status: str) -> Candidate:
        with self._lock:
            candidate.status = status
        return candidate
