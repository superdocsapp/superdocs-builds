"""Per-file-version idempotency tracking.

The brief requires: "Processing is idempotent per file version." A Box
upload event and a Box metadata-change event can both land for the same
version (e.g. our own metadata write triggers a second webhook), and two
webhook deliveries can race for the same version too. We key on
(file_id, version_sha1) rather than just file_id, so re-processing the
same bytes is a safe no-op but a genuine new version is reprocessed.
"""
from __future__ import annotations

import threading
from typing import Optional


class IdempotencyStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done: dict[str, str] = {}  # file_id -> last processed sha1
        self._in_flight: set[str] = set()  # file_id currently being processed

    def already_processed(self, file_id: str, sha1: str) -> bool:
        with self._lock:
            return self._done.get(file_id) == sha1

    def try_claim(self, file_id: str) -> bool:
        """Returns True if this call claimed the right to process file_id
        now (no other concurrent run holds it), False if another run is
        already in flight for the same file -- the caller should skip
        rather than double-process."""
        with self._lock:
            if file_id in self._in_flight:
                return False
            self._in_flight.add(file_id)
            return True

    def release(self, file_id: str) -> None:
        """Releases the in-flight claim on file_id, whether the run
        succeeded or failed. Does NOT mark the version as done -- a
        failed/partial run must remain retryable. Call mark_completed()
        separately once a run reaches a genuinely terminal, successfully
        committed state."""
        with self._lock:
            self._in_flight.discard(file_id)

    def mark_completed(self, file_id: str, sha1: str) -> None:
        """Marks (file_id, sha1) as fully, successfully processed so a
        future already_processed() check treats it as a safe no-op.
        Must only be called after a genuinely terminal success -- never
        after a partial/failed commit."""
        with self._lock:
            self._done[file_id] = sha1
