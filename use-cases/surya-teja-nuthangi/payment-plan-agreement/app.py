from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import ValidationError

from payment_plan_agreement.engine import PaymentPlanService
from payment_plan_agreement.models import CreatePlanRequest, ReviewDecision
from payment_plan_agreement.render import render_seed_html
from payment_plan_agreement.superdocs import (
    FakeSuperDocsClient,
    HttpSuperDocsClient,
    SuperDocsError,
    SuperDocsTimeout,
    SuperDocsUnauthorized,
)
from payment_plan_agreement.verifier import AgreementVerifier
from payment_plan_agreement.workflow import AgreementRun, AgreementWorkflow


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


@dataclass
class StoredRun:
    workflow: AgreementWorkflow
    run: AgreementRun
    mode: str
    started_at: float
    batch_number: int = 1


RUNS: dict[str, StoredRun] = {}


def _request(value: dict) -> CreatePlanRequest:
    return CreatePlanRequest.model_validate(value)


def _run_json(stored: StoredRun) -> dict:
    run = stored.run
    return {
        "run_id": run.run_id,
        "mode": stored.mode,
        "state": run.state.value,
        "plan": run.plan.model_dump(mode="json"),
        "seed_html": run.seed_html,
        "final_html": run.final_html,
        "job": run.job.model_dump(mode="json") if run.job else None,
        "verification": run.verification.model_dump(mode="json") if run.verification else None,
        "decisions": [item.model_dump(mode="json") for item in run.decisions],
        "batch_number": stored.batch_number,
        "elapsed_seconds": round(time.time() - stored.started_at),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "PaymentPlanDemo/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if self.path == "/api/config":
            self._json({"live_available": bool(os.environ.get("SUPERDOCS_API_KEY"))})
            return
        match = re.fullmatch(r"/api/runs/([a-zA-Z0-9_]+)", self.path)
        if match:
            stored = RUNS.get(match.group(1))
            self._json(_run_json(stored), HTTPStatus.OK) if stored else self._json({"error": "Run not found."}, HTTPStatus.NOT_FOUND)
            return
        requested = "index.html" if self.path in ("/", "/index.html") else self.path.lstrip("/")
        target = (STATIC / requested).resolve()
        if STATIC not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        try:
            payload = self._body()
            if self.path == "/api/preview":
                request = _request(payload)
                plan = PaymentPlanService().calculate(request)
                seed = render_seed_html(plan)
                verification = AgreementVerifier().verify(plan, seed)
                self._json({"plan": plan.model_dump(mode="json"), "seed_html": seed, "verification": verification.model_dump(mode="json")})
                return
            if self.path == "/api/runs":
                mode = payload.pop("mode", "fake")
                if mode not in {"fake", "live"}:
                    raise ValueError("mode must be fake or live")
                if mode == "live" and not os.environ.get("SUPERDOCS_API_KEY"):
                    self._json({"error": "Live SuperDocs is unavailable because the server-side API key is missing. Your terms are preserved; set SUPERDOCS_API_KEY and restart."}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                workflow = AgreementWorkflow(HttpSuperDocsClient() if mode == "live" else FakeSuperDocsClient())
                run = workflow.start(_request(payload))
                if mode == "live" and run.state.value == "superdocs_processing":
                    workflow.wait_for_review(run)
                RUNS[run.run_id] = StoredRun(workflow, run, mode, time.time())
                self._json(_run_json(RUNS[run.run_id]), HTTPStatus.CREATED)
                return
            review = re.fullmatch(r"/api/runs/([a-zA-Z0-9_]+)/review", self.path)
            if review:
                stored = RUNS.get(review.group(1))
                if not stored:
                    self._json({"error": "Run not found."}, HTTPStatus.NOT_FOUND); return
                decisions = [ReviewDecision.model_validate(item) for item in payload.get("decisions", [])]
                stored.workflow.review(stored.run, decisions)
                if stored.run.state.value == "awaiting_human":
                    stored.batch_number += 1
                self._json(_run_json(stored)); return
            export = re.fullmatch(r"/api/runs/([a-zA-Z0-9_]+)/export", self.path)
            if export:
                stored = RUNS.get(export.group(1))
                if not stored:
                    self._json({"error": "Run not found."}, HTTPStatus.NOT_FOUND); return
                document = stored.workflow.export(stored.run)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", document.mime_type)
                self.send_header("Content-Disposition", f'attachment; filename="{document.filename}"')
                self.send_header("Content-Length", str(len(document.content)))
                self.send_header("Access-Control-Expose-Headers", "Content-Disposition, Content-Length")
                self.end_headers(); self.wfile.write(document.content); return
            self._json({"error": "Route not found."}, HTTPStatus.NOT_FOUND)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": f"The payment terms are invalid: {exc}. Correct the highlighted input and try again; no external request was made."}, HTTPStatus.BAD_REQUEST)
        except SuperDocsUnauthorized as exc:
            self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except SuperDocsTimeout as exc:
            self._json({"error": str(exc)}, HTTPStatus.GATEWAY_TIMEOUT)
        except SuperDocsError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"Payment Plan Agreement running at http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
