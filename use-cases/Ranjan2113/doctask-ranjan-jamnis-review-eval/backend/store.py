"""Persistence for the study: batches in, decision events out.

Two hard rules, both from GROUND_TRUTH_SAFETY.md:

  * `build_reviewer_view` is the only way batch data leaves this process
    towards a reviewer (GT-1). No endpoint may hand out a raw batch.
  * The event log stores what a reviewer did, never whether it was right
    (GT-6). Scoring happens in analysis, by joining on change_id.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ground_truth import build_reviewer_view, verify_ground_truth  # noqa: E402

STUDY_DATA = REPO / "study_data"
BATCHES_PATH = STUDY_DATA / "batches.json"
EVENTS_PATH = STUDY_DATA / "raw_events.jsonl"
ASSIGNMENT_PATH = STUDY_DATA / "assignment.json"


class StudyStore:
    """Loads batches once, appends events durably.

    Events are appended under a lock and flushed to disk immediately. The study
    can be interrupted at any point -- a reviewer closing the tab mid-session
    is a normal occurrence, not an error -- and every decision made before that
    point must survive it.
    """

    def __init__(
        self,
        batches_path: Path = BATCHES_PATH,
        events_path: Path = EVENTS_PATH,
        assignment_path: Path = ASSIGNMENT_PATH,
    ) -> None:
        self.batches_path = batches_path
        self.events_path = events_path
        self.assignment_path = assignment_path
        self._lock = threading.Lock()
        self._batches: dict[str, dict[str, Any]] = {}
        self._excluded: set[str] = set()
        self.reload()

    @property
    def excluded_batch_ids(self) -> list[str]:
        """Batches present on disk but withheld from the study. For /api/health."""
        return sorted(self._excluded)

    def reload(self) -> None:
        self._excluded = set()
        if not self.batches_path.exists():
            self._batches = {}
            return
        payload = json.loads(self.batches_path.read_text(encoding="utf-8"))
        batches = {}
        for batch in payload.get("batches", []):
            # Refuse to serve a corpus whose answer key drifted since
            # pre-registration (GT-4). Better to fail loudly at startup than to
            # collect a day of data against a key we cannot vouch for.
            verify_ground_truth(batch)
            if batch.get("exclude_from_study"):
                # Retained on disk for reference, never assignable. doc01's
                # answer key was shown to the designer, who is also the sole
                # reviewer this round; serving it would measure their memory.
                self._excluded.add(batch["batch_id"])
                continue
            batches[batch["batch_id"]] = batch
        self._batches = batches

    @property
    def batch_ids(self) -> list[str]:
        return sorted(self._batches)

    def reviewer_view(self, batch_id: str) -> dict[str, Any] | None:
        """The ONLY path from a batch to a reviewer (GT-1)."""
        batch = self._batches.get(batch_id)
        if batch is None:
            return None
        return build_reviewer_view(batch)

    def raw_batch(self, batch_id: str) -> dict[str, Any] | None:
        """Ground-truth-bearing batch. For analysis only -- never for an endpoint."""
        return self._batches.get(batch_id)

    def change_ids_for(self, batch_id: str) -> set[str]:
        batch = self._batches.get(batch_id)
        if batch is None:
            return set()
        return {c["id"] for c in batch.get("changes", [])}

    def append_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
                fh.flush()

    def read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def load_assignment(self) -> dict[str, Any]:
        if not self.assignment_path.exists():
            return {}
        return json.loads(self.assignment_path.read_text(encoding="utf-8"))

    def save_assignment(self, payload: dict[str, Any]) -> None:
        self.assignment_path.parent.mkdir(parents=True, exist_ok=True)
        self.assignment_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
