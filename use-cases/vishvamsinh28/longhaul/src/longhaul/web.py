"""The operator console.

A durable runner is only useful if a person can watch it work, decide what it proposes,
and get the files out. That is what this is: one FastAPI app and one self-contained page,
no build step and no npm.

Two things it deliberately does that a status page would not:

* **It shows every call it makes to SuperDocs** — method, path, status, duration, and
  whether it was billable. The integration is visible rather than asserted.
* **It never runs on its own.** Operations cost money, so the console opens idle and does
  nothing until an operator presses Run. The budget is set in the same click.

Decisions are written through :func:`longhaul.gate.record_decisions`, the same function
the CLI and the MCP server use, so the three surfaces cannot drift apart.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .budget import OperationBudget
from .client import CallLog, SuperDocsClient, SuperDocsError
from .config import load_settings
from .gate import DeferredGate, record_decisions
from .ledger import Ledger, LeaseLost
from .model import TERMINAL_STATES
from .verify import is_alarming
from .planner import load_spec, plan_run
from .report import build
from .runner import Runner

_PAGE = Path(__file__).parent / "console.html"

#: Formats the console offers as downloads.
EXPORT_FORMATS = ("docx", "pdf", "markdown", "html", "txt")
_SUFFIX = {"markdown": "md"}
_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "markdown": "text/markdown",
    "txt": "text/plain",
}


class ConsoleService:
    """Owns one run: a worker thread, a ledger, and a record of every API call."""

    def __init__(self, spec_path: str, run_id: str | None, state_dir: str | None) -> None:
        self.spec = load_spec(spec_path)
        self.settings = load_settings(state_dir=state_dir)
        self.ledger = Ledger(self.settings.ledger_path)
        self.calls = CallLog()
        self.run_id = run_id or self._resolve_run()

        self._go = threading.Event()
        self._lock = threading.Lock()
        self._report: dict[str, Any] = {}
        self._error: str | None = None
        self._busy = False
        self._budget = OperationBudget()
        threading.Thread(target=self._loop, daemon=True).start()

    def _resolve_run(self) -> str:
        open_runs = [
            r for r in self.ledger.list_runs()
            if r.spec_hash == self.spec.spec_hash and r.status != "completed"
        ]
        return open_runs[0].run_id if open_runs else plan_run(self.ledger, self.spec).run_id

    # --- the worker -------------------------------------------------------

    def _loop(self) -> None:
        # Idle until an operator asks. Nothing here spends money on its own.
        while True:
            self._go.wait()
            self._go.clear()
            with self._lock:
                self._busy = True
            try:
                self._advance()
            except Exception as exc:  # noqa: BLE001 - surfaced on the page, never swallowed
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"
            finally:
                with self._lock:
                    self._busy = False

    def _advance(self) -> None:
        if not self.settings.api_key:
            with self._lock:
                self._error = "SUPERDOCS_API_KEY is not set."
            return
        with self._client() as client:
            runner = Runner(
                self.ledger, client, self.spec, DeferredGate(), budget=self._budget
            )
            try:
                outcome = runner.run(self.run_id)
            except (LeaseLost, SuperDocsError) as exc:
                with self._lock:
                    self._error = str(exc)
                return
            report = build(self.ledger, outcome)
        with self._lock:
            self._report = report
            self._error = report.get("blocked_reason") if report["status"] == "failed" else None

    def _client(self) -> SuperDocsClient:
        return SuperDocsClient(
            self.settings.api_key, self.settings.base_url, call_log=self.calls
        )

    # --- commands ---------------------------------------------------------

    def start(self, max_operations: int | None, reserve: int) -> None:
        with self._lock:
            if self._busy:
                raise ValueError("the run is already working")
            self._budget = OperationBudget(
                limit=max_operations, reserve=reserve,
                spent=self._budget.spent,
                account_remaining=self._budget.account_remaining,
            )
            self._error = None
        self._go.set()

    def decide(self, step_index: int, changes: list[dict[str, Any]]) -> int:
        verdicts = {
            c["change_id"]: (bool(c["approved"]), c.get("feedback") or None)
            for c in changes
        }
        if not verdicts:
            raise ValueError("no decisions supplied")
        record_decisions(self.ledger, self.run_id, step_index, verdicts, decided_by="console")
        return len(verdicts)

    def export(self, slug: str, fmt: str) -> tuple[bytes, str]:
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"format must be one of {', '.join(EXPORT_FORMATS)}")
        run = self.ledger.get_run(self.run_id)
        doc = self.ledger.get_document(self.run_id, slug)
        if run is None or doc is None or not doc.document_id:
            raise ValueError(f"{slug} is not open in this run yet")
        with self._client() as client:
            blob = client.export_document(run.session_id, doc.document_id, fmt=fmt)
        return blob, f"{slug}.{_SUFFIX.get(fmt, fmt)}"

    def document_html(self, slug: str) -> str:
        run = self.ledger.get_run(self.run_id)
        doc = self.ledger.get_document(self.run_id, slug)
        if run is None or doc is None or not doc.document_id:
            raise ValueError(f"{slug} is not open in this run yet")
        with self._client() as client:
            for entry in client.session_documents(run.session_id, include_html=True):
                if entry.get("document_id") == doc.document_id:
                    return entry.get("html") or ""
        raise ValueError(f"{slug} is not open in the session")

    # --- reads ------------------------------------------------------------

    def state(self, since: int = 0) -> dict[str, Any]:
        run = self.ledger.get_run(self.run_id)
        steps = self.ledger.get_steps(self.run_id)

        pending = []
        for step in steps:
            proposals = self.ledger.get_proposals(self.run_id, step.step_index)
            decided = {
                d.change_id for d in self.ledger.get_decisions(self.run_id, step.step_index)
            }
            waiting = [p.to_public() for p in proposals if p.change_id not in decided]
            if waiting:
                pending.append({
                    "step_index": step.step_index, "step_id": step.step_id,
                    "document": step.doc_slug, "changes": waiting,
                })

        with self._lock:
            report, error, busy = dict(self._report), self._error, self._busy
            budget = self._budget

        issued = sum(1 for c in self.calls.since(0) if c["billable"])
        is_live = "api.superdocs.app" in self.settings.base_url
        return {
            "connection": {
                "base_url": self.settings.base_url,
                "live": is_live,
                "label": "api.superdocs.app" if is_live else self.settings.base_url,
                "key": self.settings.redacted(),
                # Issued is what left this process; confirmed is what the server says it
                # billed. They differ while a turn is awaiting approval, and a denied
                # change is never billed at all.
                "operations_issued": issued,
                "operations_confirmed": budget.spent,
                "operations_remaining": budget.account_remaining,
                "operations_limit": budget.limit,
            },
            "run": {
                "run_id": self.run_id,
                "job": self.spec.name,
                "description": self.spec.description,
                "session_id": run.session_id if run else None,
                "status": run.status if run else "unknown",
                "busy": busy,
                "error": error,
            },
            "steps": [
                {"index": s.step_index, "id": s.step_id, "document": s.doc_slug,
                 "state": s.state, "evidence": s.evidence, "ms": s.duration_ms,
                 "ops": s.billable_ops, "attempt": s.attempt,
                 "verification": s.verification,
                 "verification_detail": s.verification_detail,
                 "unmet": is_alarming(s.verification),
                 "terminal": s.state in TERMINAL_STATES}
                for s in steps
            ],
            "documents": [
                {"slug": d.slug, "title": d.title, "open": bool(d.document_id),
                 "document_id": d.document_id}
                for d in self.ledger.get_documents(self.run_id)
            ],
            "pending": pending,
            "calls": self.calls.since(since),
            "call_seq": self.calls.total(),
            "totals": report.get("totals", {}),
            "latency": report.get("step_latency_ms", {}),
            "findings": report.get("findings", []),
            "formats": list(EXPORT_FORMATS),
        }


def create_app(spec_path: str, run_id: str | None, state_dir: str | None) -> FastAPI:
    service = ConsoleService(spec_path, run_id, state_dir)
    app = FastAPI(title="longhaul console")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE.read_text(encoding="utf-8")

    @app.get("/api/state")
    def state(since: int = 0) -> dict[str, Any]:
        return service.state(since)

    @app.post("/api/run")
    def start(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        try:
            limit = payload.get("max_operations")
            service.start(int(limit) if limit else None, int(payload.get("reserve") or 0))
        except ValueError as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        return {"started": True}

    @app.post("/api/decide")
    def decide(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            count = service.decide(int(payload["step_index"]), payload["changes"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return {"recorded": count}

    @app.get("/api/document/{slug}")
    def document(slug: str) -> dict[str, Any]:
        try:
            return {"slug": slug, "html": service.document_html(slug)}
        except (ValueError, SuperDocsError) as exc:
            raise HTTPException(404, detail=str(exc)) from exc

    @app.get("/api/export/{slug}")
    def export(slug: str, fmt: str = "docx") -> Response:
        try:
            blob, filename = service.export(slug, fmt)
        except (ValueError, SuperDocsError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return Response(
            content=blob,
            media_type=_MEDIA.get(fmt, "application/octet-stream"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.exception_handler(HTTPException)
    def _err(_r: Any, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app
