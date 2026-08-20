"""Single-worker durable recovery loop; no state transition is fire-and-forget."""
from __future__ import annotations
import json
from typing import Callable, Any
from .storage import Store

class DurableWorker:
    def __init__(self, store: Store, handler: Callable[[dict[str, Any]], dict[str, Any]], worker_id: str = "worker-1"):
        self.store, self.handler, self.worker_id = store, handler, worker_id
        self._claimed = False

    def start(self) -> None:
        self.store.claim_worker(self.worker_id); self._claimed = True

    def run_once(self) -> int:
        if not self._claimed: self.start()
        count = 0
        for job in self.store.recoverable_jobs():
            try:
                result = self.store.record_effect(job["id"], "handler", self.handler(job))
                fresh = self.store.get_job(job["id"])
                if fresh: self.store.transition(job["id"], fresh["revision"], result.get("state", "COMPLETED"), event="worker_completed", payload=result)
            except Exception as exc:
                fresh = self.store.get_job(job["id"])
                if fresh:
                    self.store.transition(job["id"], fresh["revision"], "BLOCKED", event="worker_blocked", payload={"error": type(exc).__name__, "message": str(exc)})
            count += 1
        return count

    def stop(self) -> None:
        if self._claimed: self.store.release_worker(self.worker_id); self._claimed = False

    def reconcile(self, upstream_jobs: list[dict[str, Any]]) -> int:
        """Persist upstream pending review state after a process restart."""
        count = 0
        for upstream in upstream_jobs:
            job_id = upstream.get("job_id") or upstream.get("id")
            if not job_id: continue
            local = self.store.get_job(job_id)
            if local is None: self.store.create_job(job_id, {"upstream": upstream}, "AWAITING_REVIEW")
            count += 1
        return count
