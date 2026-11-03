"""Stage-level checkpointing.

IdempotencyStore (idempotency.py) only ever answers "has this exact file
version already been fully processed" -- true/false, whole-run. That's
correct for skipping a redundant webhook delivery, but it means a process
killed midway through classify -> extract -> companion -> normalize
restarts from classify on the next run: none of the finished stage work
is lost (nothing partial ever reaches Box, since a mid-run write only
happens in _commit_partial/_commit_final), but SuperDocs calls that
already succeeded get redone, and "continues from where it left off" in
the literal stage-by-stage sense wasn't true.

CheckpointStore closes that gap: it persists, per (file_id, sha1), which
stages have already completed and the ExtractedFields state as of the
last completed stage. On restart, process() replays completed stages as
zero-cost "resumed" StageResults instead of re-invoking SuperDocs, and
only runs the stages that never finished.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Checkpoint:
    file_id: str
    sha1: str
    # stage name -> the StageResult dict that was recorded for it
    completed_stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    # ExtractedFields.model_dump() as of the last completed stage
    extracted: dict[str, Any] = field(default_factory=dict)


class CheckpointStore:
    """In-memory stage-level checkpoint store, keyed on (file_id, sha1).
    Swappable for a persisted backend the same way IdempotencyStore,
    ReviewQueue, and MetadataHistoryStore are (see
    app/storage/sqlite_backend.py)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._checkpoints: dict[tuple[str, str], Checkpoint] = {}

    def get(self, file_id: str, sha1: str) -> Optional[Checkpoint]:
        with self._lock:
            cp = self._checkpoints.get((file_id, sha1))
            if cp is None:
                return None
            # return a defensive copy so callers can't mutate our state
            # without going through save_stage()
            return Checkpoint(
                file_id=cp.file_id,
                sha1=cp.sha1,
                completed_stages=dict(cp.completed_stages),
                extracted=dict(cp.extracted),
            )

    def save_stage(
        self,
        file_id: str,
        sha1: str,
        stage_name: str,
        stage_result: dict[str, Any],
        extracted: dict[str, Any],
    ) -> None:
        with self._lock:
            key = (file_id, sha1)
            cp = self._checkpoints.setdefault(key, Checkpoint(file_id=file_id, sha1=sha1))
            cp.completed_stages[stage_name] = stage_result
            cp.extracted = extracted

    def clear(self, file_id: str, sha1: str) -> None:
        """Called once a run reaches a terminal state (committed final,
        or a stage fails terminally and partial state is committed) --
        a checkpoint for a version that will never be reprocessed as-is
        shouldn't linger forever."""
        with self._lock:
            self._checkpoints.pop((file_id, sha1), None)
