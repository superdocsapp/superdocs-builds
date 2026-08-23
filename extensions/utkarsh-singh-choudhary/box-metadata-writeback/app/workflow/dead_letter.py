"""Holds runs that permanently failed -- retries exhausted, or the
circuit breaker was open -- so an ops team has a real worklist to
triage instead of a run silently sitting in a bad `extraction_notes`
state with nothing pointing at it.

This is distinct from the graceful-degradation path already in
pipeline.py (a single failed stage still commits whatever honest
partial metadata it has). A dead-letter entry means the *run* could not
make forward progress at all this attempt -- SuperDocs was unreachable
long enough to exhaust retries, or the breaker was open -- and a human
or a scheduled retry job should look at it.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeadLetterEntry:
    entry_id: str
    file_id: str
    version_sha1: str
    stage: str
    reason: str
    created_at: float
    attempts: int = 0
    resolved: bool = False
    resolved_at: Optional[float] = None
    resolution: Optional[str] = None  # "reprocessed" | "manually_closed"


class DeadLetterQueue:
    """In-memory by default; same public surface is implemented by
    SqliteDeadLetterQueue for the durable path, matching every other
    store in this codebase (IdempotencyStore/ReviewQueue/etc.)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, DeadLetterEntry] = {}

    def add(self, file_id: str, version_sha1: str, stage: str, reason: str, attempts: int) -> DeadLetterEntry:
        entry = DeadLetterEntry(
            entry_id=f"dlq-{uuid.uuid4().hex[:8]}",
            file_id=file_id,
            version_sha1=version_sha1,
            stage=stage,
            reason=reason,
            attempts=attempts,
            created_at=time.time(),
        )
        with self._lock:
            self._entries[entry.entry_id] = entry
        return entry

    def list_unresolved(self, file_id: Optional[str] = None) -> list[DeadLetterEntry]:
        with self._lock:
            items = [e for e in self._entries.values() if not e.resolved]
        if file_id:
            items = [e for e in items if e.file_id == file_id]
        return sorted(items, key=lambda e: e.created_at)

    def resolve(self, entry_id: str, resolution: str = "manually_closed") -> DeadLetterEntry:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                raise KeyError(entry_id)
            entry.resolved = True
            entry.resolved_at = time.time()
            entry.resolution = resolution
            return entry

    def get(self, entry_id: str) -> Optional[DeadLetterEntry]:
        with self._lock:
            return self._entries.get(entry_id)
