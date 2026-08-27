"""The review console: a small web interface over the same batch commands.

Standard library only, like the rest of the project -- http.server plus a JSON
API, no framework and no build step. The CLI remains the source of truth; this
serves the one job a terminal is genuinely bad at, which is reading a proposed
customer letter and deciding whether it should be sent.

    python renewal_desk.py serve          then open http://localhost:7000
"""

from __future__ import annotations

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent

# One background job at a time, mirroring the CLI's batch lock. The UI polls it.
_job = {"running": False, "log": [], "done": False, "error": None}
_job_lock = threading.Lock()


def _push(line: str) -> None:
    with _job_lock:
        _job["log"].append(line)


class Console:
    """Everything the page needs, assembled from the same functions the CLI uses."""

    @staticmethod
    def overview() -> dict:
        import renewal_desk as rd
        from pricing import decide_all, money

        decisions, accounts, policy = decide_all(rd.DATA)
        states = rd.all_states()

        rows, skipped = [], []
        for d in decisions:
            st = states.get(d.account_id, {"status": "not_started"})
            acct = rd.account_by_id(accounts, d.account_id)
            if d.action == "skip":
                skipped.append({
                    "account_id": d.account_id,
                    "company": d.company,
                    "reason": d.skip_reason,
                })
                continue
            rows.append({
                "account_id": d.account_id,
                "company": d.company,
                "contact": acct["contact"]["name"],
                "plan": acct["plan"],
                "renewal_date": acct["renewal_date"],
                "seats": d.renewal_seats,
                "old_price": money(d.current_price),
                "new_price": money(d.new_price),
                "pct": d.change_pct,
                "direction": d.direction,
                "annual": money(d.renewal_annual),
                "delta_annual": money(d.price_delta_annual),
                "gated": d.gated,
                "gate_reasons": d.gate_reasons,
                "drivers": [
                    {"reason": x.reason, "pct": x.pct, "detail": x.detail}
                    for x in d.drivers
                ],
                "status": st.get("status", "not_started"),
                "decision": st.get("decision"),
                "revisions": len(st.get("revisions", [])),
                "files": [Path(f).name for f in st.get("files", [])],
                "fail_reason": st.get("fail_reason"),
                "ops": st.get("ops_spent", 0),
            })

        processed = [r for r in rows if r["status"] in ("exported", "rejected")]
        return {
            "batch": accounts["batch"],
            "policy": {
                "version": policy["policy_version"],
                "gate": policy["approval_gate"],
            },
            "rows": rows,
            "skipped": skipped,
            "summary": {
                "total": len(decisions),
                "to_process": len(rows),
                "skipped": len(skipped),
                "awaiting": sum(1 for r in rows if r["status"] == "awaiting_review"),
                "exported": sum(1 for r in rows if r["status"] == "exported"),
                "rejected": sum(1 for r in rows if r["status"] == "rejected"),
                "failed": sum(1 for r in rows if r["status"] == "failed"),
                "not_started": sum(1 for r in rows if r["status"] == "not_started"),
                "complete": len(processed) == len(rows) and bool(rows),
                "ops": rd.total_ops(),
            },
        }

    @staticmethod
    def detail(account_id: str) -> dict:
        import renewal_desk as rd
        from superdocs_client import Client, parse_pending_changes

        st = rd.acct_state(account_id)
        out = {"account_id": account_id, "status": st.get("status"),
               "changes": [], "document": "", "note": st.get("note"),
               "revisions": st.get("revisions", []),
               "gate_reasons": st.get("gate_reasons", [])}
        if not st.get("sessions"):
            return out

        client = Client()
        # Exports are free, so previewing the live document costs nothing.
        try:
            out["document"] = client.export_text(st["sessions"]["notice"], "markdown")
        except Exception as exc:  # noqa: BLE001
            out["document"] = f"(could not load the document: {exc})"

        if st.get("status") == "awaiting_review" and st.get("job_id"):
            try:
                job = client.job(st["job_id"])
                out["changes"] = parse_pending_changes(
                    (job.get("metadata") or {}).get("pending_changes"))
            except Exception as exc:  # noqa: BLE001
                out["error"] = str(exc)
        return out

    @staticmethod
    def decide(account_id: str, verdict: str, feedback: str, by: str) -> dict:
        import renewal_desk as rd

        args = type("A", (), {"account_id": account_id, "verdict": verdict,
                              "feedback": feedback, "by": by or "review-console"})()
        code = rd.cmd_decide(args)
        return {"ok": code == 0, "status": rd.acct_state(account_id).get("status")}

    @staticmethod
    def start_run(fresh: bool) -> None:
        import renewal_desk as rd

        with _job_lock:
            if _job["running"]:
                return
            _job.update(running=True, log=[], done=False, error=None)

        def work():
            import contextlib
            import io

            args = type("A", (), {"sample": 0, "max_ops": 80, "only": None,
                                  "fresh": fresh})()
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rd.cmd_run(args)
            except BaseException as exc:  # noqa: BLE001
                with _job_lock:
                    _job["error"] = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            finally:
                for line in buf.getvalue().splitlines():
                    _push(line)
                with _job_lock:
                    _job.update(running=False, done=True)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def job_status() -> dict:
        with _job_lock:
            return dict(_job)

    @staticmethod
    def report() -> str:
        import renewal_desk as rd

        rd.cmd_report(None)
        p = rd.OUT / "batch-report.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""


class Handler(BaseHTTPRequestHandler):
    server_version = "RenewalDesk/1.0"

    def log_message(self, fmt, *a):  # quieter console
        pass

    # ------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _fail(self, exc: BaseException) -> None:
        # Never a bare 500: the page shows this text in a toast.
        self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                html = (HERE / "web" / "index.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8")
            if path == "/api/overview":
                return self._json(Console.overview())
            if path == "/api/job":
                return self._json(Console.job_status())
            if path == "/api/report":
                return self._json({"markdown": Console.report()})
            if path.startswith("/api/account/"):
                return self._json(Console.detail(unquote(path.rsplit("/", 1)[-1])))
            self._json({"error": f"no route {path}"}, 404)
        except BaseException as exc:  # noqa: BLE001
            self._fail(exc)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if path == "/api/decide":
                return self._json(Console.decide(
                    body["account_id"], body["verdict"],
                    body.get("feedback", ""), body.get("by", "")))
            if path == "/api/run":
                Console.start_run(bool(body.get("fresh")))
                return self._json({"started": True})
            self._json({"error": f"no route {path}"}, 404)
        except BaseException as exc:  # noqa: BLE001
            self._fail(exc)


def serve(port: int = 7000) -> None:
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Renewal Desk review console -> http://localhost:{port}")
    print("Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
