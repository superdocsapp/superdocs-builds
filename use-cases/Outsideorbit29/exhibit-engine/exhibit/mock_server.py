"""In-memory mock of the SuperDocs API, for tests and offline demos.

Speaks the same HTTP surface as the real service for the four calls the client
uses (upload-base64, chat/async, jobs/{job_id}, chat/{session_id}/approve,
documents/export) so tests exercise the *real* HTTP contract without a key.

The mock derives proposed changes from the ``[[PROPOSAL]]`` JSON block the
engine embeds in the chat message: one pending change per citation (an edit),
one per exhibit cover (a create), and one for the index (a create). Approving a
change applies it to the session document; when every pending change is decided
the job becomes ``completed`` and export returns the assembled document.

Start it with :func:`start_server`, which returns ``(base_url, shutdown)``.
"""

from __future__ import annotations

import html.parser
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MockSuperDocs:
    """Stateful fake: sessions + jobs, thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sessions: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self._seq = 0

    # -- helpers -----------------------------------------------------------------

    def _next(self, prefix: str) -> str:
        with self._lock:
            self._seq += 1
            return f"{prefix}-{self._seq}-{uuid.uuid4().hex[:8]}"

    def create_session(self, document_html: str) -> str:
        sid = self._next("sess")
        with self._lock:
            self.sessions[sid] = {"document_html": document_html}
        return sid

    # -- HTTP handlers -------------------------------------------------------------

    def handle_upload_base64(self, body: dict[str, Any]) -> dict[str, Any]:
        sid = body.get("session_id") or self._next("sess")
        if sid not in self.sessions:
            self.sessions[sid] = {}
        # The mock stores the decoded text as the session document.
        raw = _b64decode(body.get("file_base64", ""))
        self.sessions[sid]["document_html"] = _as_text(raw)
        return {
            "session_id": sid,
            "document_id": self._next("doc"),
            "chunks_count": len(self.sessions[sid].get("document_html", "")) // 200 + 1,
            "version_id": self._next("ver"),
        }

    def handle_chat_async(self, body: dict[str, Any]) -> dict[str, Any]:
        sid = body.get("session_id", "")
        if sid not in self.sessions:
            raise ValueError(f"unknown session {sid!r}")
        proposal = _extract_proposal(body.get("message", ""))
        pending = _proposal_changes(proposal)
        job_id = self._next("job")
        with self._lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "session_id": sid,
                "status": "awaiting_approval",
                "progress": 60,
                "pending_changes": pending,
                "pending_change_ids": [c["change_id"] for c in pending],
                "changes_by_id": {c["change_id"]: c for c in pending},
                "decided": set(),
                "created_at": _iso(),
                "updated_at": _iso(),
            }
        return {"job_id": job_id, "session_id": sid, "status": "pending"}

    def handle_get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return self._job_response(job)

    def handle_approve(self, sid: str, body: dict[str, Any]) -> dict[str, Any]:
        job_id = body.get("job_id", "")
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            decisions = _decisions(body)
            if not decisions:
                decisions = _decisions_from_flat(body)
            for change_id, approved, _feedback in decisions:
                if change_id in job.get("pending_change_ids", ()):
                    job["decided"].add(change_id)
                    if approved:
                        _apply_change(self.sessions[job["session_id"]], change_id,
                                      job["changes_by_id"])
            job["progress"] = min(
                100, int(60 + 40 * (len(job["decided"]) / max(1, len(job["pending_changes"]))))
            )
            if len(job["decided"]) >= len(job["pending_changes"]):
                job["status"] = "completed"
                job["progress"] = 100
            job["updated_at"] = _iso()
        return {}

    def handle_export(self, body: dict[str, Any]) -> tuple[bytes, str, str]:
        sid = body.get("session_id", "")
        fmt = body.get("format", "docx")
        with self._lock:
            doc = self.sessions.get(sid, {}).get("document_html", "")
        text = doc if fmt == "html" else _strip_tags(doc)
        if fmt == "pdf":
            return text.encode("utf-8"), "application/pdf", "packet.pdf"
        if fmt == "docx":
            return text.encode("utf-8"), (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ), "packet.docx"
        if fmt in {"markdown", "md"}:
            return text.encode("utf-8"), "text/markdown", "packet.md"
        if fmt == "txt":
            return _strip_tags(doc).encode("utf-8"), "text/plain", "packet.txt"
        return text.encode("utf-8"), "text/html", "packet.html"

    # -- internal --------------------------------------------------------------------

    def _job_response(self, job: dict[str, Any]) -> dict[str, Any]:
        pending = job["pending_changes"]
        for change in pending:
            change["change_id"] = change["change_id"]  # ensure present
        response: dict[str, Any] = {
            "job_id": job["job_id"],
            "session_id": job["session_id"],
            "job_type": "chat",
            "status": job["status"],
            "progress": job["progress"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "metadata": {"pending_changes": pending, "message": "mock chat"},
        }
        if job["status"] == "completed":
            response["result"] = {
                "response": "All changes applied by the mock.",
                "document_changes": list(job["decided"]),
                "usage": {"cost": 0.0},
            }
        return response


def start_server() -> tuple[str, threading.Event, MockSuperDocs]:
    """Start the mock on a random port. Returns (base_url, stop_event, state)."""
    state = MockSuperDocs()
    stop = threading.Event()

    handler = _make_handler(state, stop)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    return base_url, stop, state


def _make_handler(state: MockSuperDocs, stop: threading.Event):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence request logging
            pass

        def do_POST(self) -> None:
            try:
                self._route()
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)

        def do_GET(self) -> None:
            try:
                self._route()
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)

        def _route(self) -> None:
            path = self.path.split("?")[0]
            if path == "/v1/documents/upload-base64":
                self._send_json(state.handle_upload_base64(self._read_json()))
            elif path == "/v1/chat/async":
                self._send_json(state.handle_chat_async(self._read_json()))
            elif path.startswith("/v1/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                self._send_json(state.handle_get_job(job_id))
            elif m := re.match(r"^/v1/chat/([^/]+)/approve$", path):
                self._send_json(state.handle_approve(m.group(1), self._read_json()))
            elif path == "/v1/documents/export":
                content, ctype, fname = state.handle_export(self._read_json())
                self._send_bytes(content, ctype, fname)
            else:
                self._send_json({"error": f"no mock route for {path}"}, status=404)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0"))
            payload = self.rfile.read(length) or b"{}"
            return json.loads(payload)

        def _send_json(self, obj: Any, status: int = 200) -> None:
            payload = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_bytes(self, content: bytes, ctype: str, fname: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    return Handler


# --------------------------------------------------------------------------- proposal parsing


def _extract_proposal(message: str) -> dict[str, Any]:
    m = re.search(r"\[\[PROPOSAL\]\](.*?)\[\[/PROPOSAL\]\]", message, re.S)
    if not m:
        return {}
    return json.loads(m.group(1))


def _proposal_changes(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """One pending change per citation (edit) and one per cover (create), plus
    one for the index. ``id`` keys are stored so approved edits can be applied."""
    changes: list[dict[str, Any]] = []
    for i, cit in enumerate(proposal.get("citations", [])):
        changes.append({
            "change_id": f"cit-{cit.get('exhibit_number', i)}",
            "operation": "edit",
            "new_html": f'<p>{_esc(cit.get("sentence", ""))}</p>',
            "ai_explanation": cit.get("rationale", ""),
            "anchor": cit.get("anchor", ""),
        })
    for ex in proposal.get("exhibits", []):
        changes.append({
            "change_id": f"cover-{ex.get('number')}",
            "operation": "create",
            "new_html": (
                f'<section>Exhibit {ex.get("number")} — {_esc(ex.get("title", ""))}'
                f'<p>{_esc(ex.get("proves", ""))}</p>'
                f'<p>Pages: {ex.get("page_range", "—")}</p></section>'
            ),
            "ai_explanation": "Numbered cover page for this exhibit.",
        })
    changes.append({
        "change_id": "index",
        "operation": "create",
        "new_html": '<section class="index">Index appended.</section>',
        "ai_explanation": "Exhibit index appended.",
    })
    return changes


def _decisions(body: dict[str, Any]) -> list[tuple[str, bool, str | None]]:
    out = []
    for item in body.get("changes", []) or []:
        out.append((item.get("change_id"), bool(item.get("approved")), item.get("feedback")))
    return out


def _decisions_from_flat(body: dict[str, Any]) -> list[tuple[str, bool, str | None]]:
    cid = body.get("change_id")
    if cid:
        return [(cid, bool(body.get("approved")), body.get("feedback"))]
    return []


def _apply_change(session: dict[str, Any], change_id: str, by_id: dict[str, Any]) -> None:
    change = by_id.get(change_id)
    if not change:
        return
    doc = session.get("document_html", "")
    if change.get("operation") == "edit" and change.get("anchor"):
        anchor = change["anchor"]
        idx = doc.find(anchor)
        if idx != -1:
            doc = doc[: idx + len(anchor)] + " [See Exhibit " + re.sub(
                r"\D", "", change_id) + "]" + doc[idx + len(anchor):]
        else:
            doc = doc + "\n" + change.get("new_html", "")
    else:  # create
        doc = doc + "\n" + change.get("new_html", "")
    session["document_html"] = doc


class _HtmlStripper(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _strip_tags(html_text: str) -> str:
    strip = _HtmlStripper()
    strip.feed(html_text)
    return "\n".join(strip.parts)


def _b64decode(payload: str) -> bytes:
    import base64
    return base64.b64decode(payload)


def _as_text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
