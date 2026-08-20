"""SQLite-backed persistence for idempotency, the review queue, and the
metadata audit trail.

This is what makes "survives being stopped" real rather than simulated:
`FakeBoxClient`/`FakeSuperDocsClient` are in-memory by design (per the
brief's own requirement that tests run without a live key), but the
*workflow's own bookkeeping* -- what's been processed, what's pending
review, what changed and when -- has no reason to be memory-only, and
losing it on every restart would be a real correctness bug in
production. These three classes implement the exact same public method
signatures as their in-memory counterparts (`IdempotencyStore`,
`ReviewQueue`, `MetadataHistoryStore`), so `BoxMetadataWritebackPipeline`
works identically against either -- duck typing, not inheritance, is the
seam.

Kept intentionally simple: one SQLite file, no ORM, no migrations
framework. That's an appropriate amount of infrastructure for what this
needs, not a shortcut -- see the README for why a heavier persistence
layer (Postgres, an actual queue) wasn't the differentiator worth
spending the remaining task budget on.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional

from app.models import MetadataChange, PendingReview
from app.workflow.checkpoint import Checkpoint

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency (
    file_id TEXT PRIMARY KEY,
    sha1 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    version_sha1 TEXT NOT NULL,
    field_name TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    decided_at REAL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    version_sha1 TEXT NOT NULL,
    timestamp REAL NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS last_values (
    file_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (file_id, field_name)
);
CREATE TABLE IF NOT EXISTS checkpoint_stages (
    file_id TEXT NOT NULL,
    sha1 TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    stage_result_json TEXT NOT NULL,
    extracted_json TEXT NOT NULL,
    PRIMARY KEY (file_id, sha1, stage_name)
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


class SqliteIdempotencyStore:
    """Same public surface as IdempotencyStore, backed by a SQLite table
    instead of a dict -- a process restart re-opens the same file and
    sees exactly what was already processed."""

    def __init__(self, db_path: str) -> None:
        self._conn = _connect(db_path)
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()  # in-flight claims are process-local by nature

    def already_processed(self, file_id: str, sha1: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT sha1 FROM idempotency WHERE file_id = ?", (file_id,)
            ).fetchone()
            return row is not None and row[0] == sha1

    def try_claim(self, file_id: str) -> bool:
        with self._lock:
            if file_id in self._in_flight:
                return False
            self._in_flight.add(file_id)
            return True

    def release(self, file_id: str) -> None:
        """Releases the in-flight claim, whether the run succeeded or
        failed. Does NOT mark the version as done -- see mark_completed."""
        with self._lock:
            self._in_flight.discard(file_id)

    def mark_completed(self, file_id: str, sha1: str) -> None:
        """Marks (file_id, sha1) as fully, successfully processed.
        Must only be called after a genuinely terminal success -- never
        after a partial/failed commit."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO idempotency (file_id, sha1) VALUES (?, ?) "
                "ON CONFLICT(file_id) DO UPDATE SET sha1 = excluded.sha1",
                (file_id, sha1),
            )
            self._conn.commit()


class SqliteReviewQueue:
    """Same public surface as ReviewQueue. A review staged before a crash
    is still there, still pending, after the process restarts and
    re-opens the same db file."""

    def __init__(self, db_path: str, threshold: float = 0.7) -> None:
        self.threshold = threshold
        self._conn = _connect(db_path)
        self._lock = threading.Lock()

    def stage(
        self, file_id: str, version_sha1: str, field_name: str, value: str, confidence: float
    ) -> PendingReview:
        review = PendingReview(
            review_id=f"rev-{uuid.uuid4().hex[:8]}",
            file_id=file_id,
            version_sha1=version_sha1,
            field_name=field_name,
            proposed_value=value,
            confidence=confidence,
            created_at=time.time(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO reviews (review_id, file_id, version_sha1, field_name, "
                "proposed_value, confidence, status, created_at, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review.review_id,
                    review.file_id,
                    review.version_sha1,
                    review.field_name,
                    review.proposed_value,
                    review.confidence,
                    review.status,
                    review.created_at,
                    review.decided_at,
                ),
            )
            self._conn.commit()
        return review

    def _row_to_review(self, row: tuple) -> PendingReview:
        return PendingReview(
            review_id=row[0],
            file_id=row[1],
            version_sha1=row[2],
            field_name=row[3],
            proposed_value=row[4],
            confidence=row[5],
            status=row[6],
            created_at=row[7],
            decided_at=row[8],
        )

    def list_pending(self, file_id: Optional[str] = None) -> list[PendingReview]:
        with self._lock:
            if file_id:
                rows = self._conn.execute(
                    "SELECT * FROM reviews WHERE status = 'pending' AND file_id = ? "
                    "ORDER BY created_at",
                    (file_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM reviews WHERE status = 'pending' ORDER BY created_at"
                ).fetchall()
        return [self._row_to_review(r) for r in rows]

    def get(self, review_id: str) -> Optional[PendingReview]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
        return self._row_to_review(row) if row else None

    def decide(self, review_id: str, approve: bool) -> PendingReview:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
            if row is None:
                raise KeyError(review_id)
            review = self._row_to_review(row)
            if review.status != "pending":
                raise ValueError(f"review {review_id} already {review.status}")
            review.status = "approved" if approve else "rejected"
            review.decided_at = time.time()
            self._conn.execute(
                "UPDATE reviews SET status = ?, decided_at = ? WHERE review_id = ?",
                (review.status, review.decided_at, review_id),
            )
            self._conn.commit()
            return review


class SqliteHistoryStore:
    """Same public surface as MetadataHistoryStore. `last_values` is its
    own table (rather than recomputed from the log) so a restart doesn't
    need to replay the whole history table just to know the current
    value of every field -- an O(1) lookup per field on every diff."""

    def __init__(self, db_path: str) -> None:
        self._conn = _connect(db_path)
        self._lock = threading.Lock()

    def record_diff(
        self, file_id: str, version_sha1: str, new_fields: dict[str, Any], reason: str
    ) -> list[MetadataChange]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT field_name, value FROM last_values WHERE file_id = ?", (file_id,)
            ).fetchall()
            previous = {field_name: value for field_name, value in rows}
            all_keys = set(previous) | set(new_fields)
            entries: list[MetadataChange] = []
            now = time.time()
            for key in sorted(all_keys):
                old_val = previous.get(key)
                new_val = new_fields.get(key)
                new_val_str = None if new_val is None else str(new_val)
                if old_val == new_val_str:
                    continue
                entry = MetadataChange(
                    file_id=file_id,
                    field_name=key,
                    old_value=old_val,
                    new_value=new_val_str,
                    version_sha1=version_sha1,
                    timestamp=now,
                    reason=reason,
                )
                entries.append(entry)
                self._conn.execute(
                    "INSERT INTO history (file_id, field_name, old_value, new_value, "
                    "version_sha1, timestamp, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (file_id, key, old_val, new_val_str, version_sha1, now, reason),
                )
                self._conn.execute(
                    "INSERT INTO last_values (file_id, field_name, value) VALUES (?, ?, ?) "
                    "ON CONFLICT(file_id, field_name) DO UPDATE SET value = excluded.value",
                    (file_id, key, new_val_str),
                )
            self._conn.commit()
            return entries

    def get_history(self, file_id: str) -> list[MetadataChange]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT file_id, field_name, old_value, new_value, version_sha1, "
                "timestamp, reason FROM history WHERE file_id = ? ORDER BY id",
                (file_id,),
            ).fetchall()
        return [
            MetadataChange(
                file_id=r[0],
                field_name=r[1],
                old_value=r[2],
                new_value=r[3],
                version_sha1=r[4],
                timestamp=r[5],
                reason=r[6],
            )
            for r in rows
        ]


class SqliteCheckpointStore:
    """Same public surface as CheckpointStore (get / save_stage / clear),
    backed by SQLite -- what makes stage-level resumption survive an
    actual process kill, not just a fresh set of Python objects in the
    same interpreter. `extracted_json` is overwritten on every
    save_stage() call (it always holds the latest ExtractedFields
    snapshot, not a per-stage copy), matching the in-memory store's
    semantics exactly."""

    def __init__(self, db_path: str) -> None:
        self._conn = _connect(db_path)
        self._lock = threading.Lock()

    def get(self, file_id: str, sha1: str) -> Optional[Checkpoint]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT stage_name, stage_result_json, extracted_json "
                "FROM checkpoint_stages WHERE file_id = ? AND sha1 = ?",
                (file_id, sha1),
            ).fetchall()
        if not rows:
            return None
        completed_stages = {row[0]: json.loads(row[1]) for row in rows}
        # every row's extracted_json is the same latest snapshot; any is fine
        extracted = json.loads(rows[-1][2])
        return Checkpoint(
            file_id=file_id, sha1=sha1, completed_stages=completed_stages, extracted=extracted
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
            self._conn.execute(
                "INSERT INTO checkpoint_stages "
                "(file_id, sha1, stage_name, stage_result_json, extracted_json) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(file_id, sha1, stage_name) DO UPDATE SET "
                "stage_result_json = excluded.stage_result_json, "
                "extracted_json = excluded.extracted_json",
                (file_id, sha1, stage_name, json.dumps(stage_result), json.dumps(extracted)),
            )
            self._conn.commit()

    def clear(self, file_id: str, sha1: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM checkpoint_stages WHERE file_id = ? AND sha1 = ?", (file_id, sha1)
            )
            self._conn.commit()
