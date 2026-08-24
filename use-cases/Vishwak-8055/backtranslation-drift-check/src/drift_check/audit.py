"""Append-only audit trail.

Every event is a plain dict of JSON-serializable values, written as one line
of JSONL per event as soon as it happens — not batched and flushed at the
end, so a crash mid-run still leaves a readable partial trail. This module
has no opinion about *what* counts as auditable; pipeline.py decides that by
what it chooses to log.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from drift_check.models import AuditEvent, utc_now_iso


class AuditLog:
    def __init__(self, run_id: str, path: Path | None = None) -> None:
        self.run_id = run_id
        self._path = path
        self.events: list[AuditEvent] = []
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **details: object) -> AuditEvent:
        evt = AuditEvent(run_id=self.run_id, event=event, timestamp=utc_now_iso(), details=details)
        self.events.append(evt)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(evt), default=str) + "\n")
        return evt

    def as_list(self) -> list[dict[str, object]]:
        return [asdict(e) for e in self.events]
