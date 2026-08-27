"""The review surface.

One FastAPI app and one self-contained HTML page: no build step, no npm, nothing to
install beyond the project's own dependencies. A stranger with the repo and ``uv`` is
looking at the review UI in one command.

The UI decides nothing on its own. It reads proposals out of the ledger and writes
decisions back into it through exactly the same function the CLI and the MCP server use
(:func:`longhaul.gate.record_decisions`), so the three surfaces cannot drift apart. A
background worker runs the job with a deferred gate: it advances until something needs a
decision, stops, and picks up again when one is recorded.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .client import SuperDocsClient, SuperDocsError
from .config import load_settings
from .gate import DeferredGate, record_decisions
from .ledger import Ledger, LeaseLost
from .model import TERMINAL_STATES
from .planner import load_spec, plan_run
from .report import build
from .runner import Runner

_PAGE = Path(__file__).parent / "review.html"


class ReviewService:
    """Owns the run: one worker thread, one ledger, no shared mutable state elsewhere."""

    def __init__(self, spec_path: str, run_id: str | None, state_dir: str | None) -> None:
        self.spec = load_spec(spec_path)
        self.settings = load_settings(state_dir=state_dir)
        self.ledger = Ledger(self.settings.ledger_path)
        self.run_id = run_id or self._resolve_run()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._last: dict[str, Any] = {"status": "idle", "steps": []}
        self._error: str | None = None
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def _resolve_run(self) -> str:
        existing = [
            r for r in self.ledger.list_runs()
            if r.spec_hash == self.spec.spec_hash and r.status != "completed"
        ]
        if existing:
            return existing[0].run_id
        return plan_run(self.ledger, self.spec).run_id

    # --- the worker -------------------------------------------------------

    def _loop(self) -> None:
        self._wake.set()  # advance once on startup so the first proposals appear
        while True:
            self._wake.wait()
            self._wake.clear()
            try:
                self._advance()
            except Exception as exc:  # noqa: BLE001 - surfaced to the page, never swallowed
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"

    def _advance(self) -> None:
        if not self.settings.api_key:
            with self._lock:
                self._error = (
                    "No API key. Set SUPERDOCS_API_KEY in your environment or .env file."
                )
            return
        with SuperDocsClient(self.settings.api_key, self.settings.base_url) as client:
            runner = Runner(self.ledger, client, self.spec, DeferredGate())
            try:
                outcome = runner.run(self.run_id)
            except LeaseLost as exc:
                with self._lock:
                    self._error = str(exc)
                return
            except SuperDocsError as exc:
                with self._lock:
                    self._error = str(exc)
                return
            report = build(self.ledger, outcome)
        with self._lock:
            self._last = report
            self._error = None

    # --- reads ------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        run = self.ledger.get_run(self.run_id)
        steps = self.ledger.get_steps(self.run_id)
        pending = []
        for step in steps:
            proposals = self.ledger.get_proposals(self.run_id, step.step_index)
            decided = {d.change_id for d in self.ledger.get_decisions(self.run_id, step.step_index)}
            waiting = [p.to_public() for p in proposals if p.change_id not in decided]
            if waiting:
                pending.append({
                    "step_index": step.step_index,
                    "step_id": step.step_id,
                    "document": step.doc_slug,
                    "changes": waiting,
                })
        with self._lock:
            report, error = dict(self._last), self._error
        return {
            "run_id": self.run_id,
            "job": self.spec.name,
            "description": self.spec.description,
            "status": run.status if run else "unknown",
            "error": error,
            "busy": self._wake.is_set(),
            "steps": [
                {"index": s.step_index, "id": s.step_id, "document": s.doc_slug,
                 "state": s.state, "evidence": s.evidence,
                 "terminal": s.state in TERMINAL_STATES}
                for s in steps
            ],
            "pending": pending,
            "totals": report.get("totals", {}),
            "findings": report.get("findings", []),
        }

    def decide(self, step_index: int, changes: list[dict[str, Any]]) -> int:
        verdicts = {
            c["change_id"]: (bool(c["approved"]), c.get("feedback") or None)
            for c in changes
        }
        if not verdicts:
            raise ValueError("no decisions supplied")
        record_decisions(self.ledger, self.run_id, step_index, verdicts, decided_by="web")
        self._wake.set()
        return len(verdicts)


def create_app(spec_path: str, run_id: str | None, state_dir: str | None) -> FastAPI:
    service = ReviewService(spec_path, run_id, state_dir)
    app = FastAPI(title="longhaul review")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE.read_text(encoding="utf-8")

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return service.state()

    @app.post("/api/decide")
    def decide(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            count = service.decide(int(payload["step_index"]), payload["changes"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return {"recorded": count}

    @app.post("/api/resume")
    def resume() -> dict[str, Any]:
        service._wake.set()
        return {"ok": True}

    @app.exception_handler(HTTPException)
    def _err(_r: Any, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app
