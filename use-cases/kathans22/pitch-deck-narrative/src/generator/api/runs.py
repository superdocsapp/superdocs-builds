"""In-process generation runs — poll, never block the HTTP request on SuperDocs."""

from __future__ import annotations

import threading
import uuid
from typing import Any


class RunStore:
    """Thread-safe dict of background generate jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, dict[str, Any]] = {}

    def create(self, vertical: str, force: bool) -> str:
        run_id = uuid.uuid4().hex
        with self._lock:
            self._runs[run_id] = {
                "run_id": run_id,
                "vertical": vertical,
                "force": force,
                "status": "queued",
                "result": None,
                "error": None,
            }
        return run_id

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._runs.get(run_id)
            return dict(rec) if rec is not None else None

    def mark(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            rec = self._runs[run_id]
            rec["status"] = status
            if result is not None:
                rec["result"] = result
            if error is not None:
                rec["error"] = error


RUNS = RunStore()
