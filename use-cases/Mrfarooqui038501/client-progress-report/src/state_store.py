"""
Tiny JSON-backed state store mapping client_id -> SuperDocs session_id.

This is what makes "the same client's second and third reports extend one
document coherently" possible: we re-open the same session_id every run for
a given client, so SuperDocs treats it as the same durable document rather
than creating a new one each time. See docs/concepts/sessions.md: "Sessions
persist conversation history and document state across requests. You choose
the session ID" -- we choose session_id = f"client-progress-{client_id}"
deterministically so no lookup table would even be required, but we keep an
explicit store anyway so a human can audit which clients have been run and
when, and so a crash mid-batch can resume without re-processing finished
clients (see batch_runner.run_batch's checkpointing).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def session_id_for(self, client_id: str) -> str:
        """Deterministic session id -- stable even if the state file is lost."""
        return f"client-progress-{client_id}"

    def get_record(self, client_id: str) -> Optional[dict]:
        return self._data.get(client_id)

    def mark_run(self, client_id: str, *, assessment_index: int, version_id: Optional[str],
                 export_path: Optional[str]) -> None:
        self._data[client_id] = {
            "session_id": self.session_id_for(client_id),
            "last_assessment_index": assessment_index,
            "last_version_id": version_id,
            "last_export_path": export_path,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def already_processed(self, client_id: str, assessment_index: int) -> bool:
        """Idempotency check: don't re-run a client for an assessment index
        we've already committed, so re-running a crashed batch doesn't
        duplicate work or spend operations twice on the same report.
        """
        rec = self._data.get(client_id)
        return bool(rec and rec.get("last_assessment_index") == assessment_index)

    def _save(self) -> None:
        # Write atomically so a crash mid-write never corrupts the state file.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
