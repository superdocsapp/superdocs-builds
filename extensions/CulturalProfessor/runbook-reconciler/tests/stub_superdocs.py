"""A local, in-process stand-in for api.superdocs.app.

**Provenance: copied from the sibling build.** This is `tests/stub_superdocs.py`
from `use-cases/CulturalProfessor/product-manual-builder` in this repository --
same author, same MIT licence -- carried across so the crash-recovery and
zero-spend tests here can run the real `rr` command as a real subprocess without
a key. Routes added for this build are marked where they appear.

Not a test file -- pytest never collects this on its own name. It exists so
`test_process_reentry.py` can run the real `mb` command as a real subprocess,
kill it mid-request, and prove what survives, without spending a real
operation or needing a key. The stub answers exactly the calls the crash-
recovery path makes: session init, upload, image upload, an async chat turn,
the job poll, the session's job list, and approve.

The one deliberate piece of behaviour: `GET /v1/jobs/{id}` marks `polled` and
then sleeps before answering, so a test can wait for that event and kill the
client while it is genuinely blocked inside the HTTP call -- not guess at a
sleep long enough to "probably" land inside it.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_MULTIPART_NAME = re.compile(rb'name="([^"]+)"')


def _parse_multipart(content_type: str, body: bytes) -> dict[str, bytes]:
    """Just enough to read `session_id` and `open_mode` off an upload.

    The file's own bytes are read and discarded -- the stub does not need to
    understand the document it was handed, only which session to attach it to.
    """
    match = re.search(r'boundary=("?)([^";]+)\1', content_type)
    if not match:
        return {}
    boundary = match.group(2).encode()
    fields: dict[str, bytes] = {}
    for chunk in body.split(b"--" + boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        header_blob, sep, content = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        name = _MULTIPART_NAME.search(header_blob)
        if name:
            fields[name.group(1).decode()] = content
    return fields


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # keep test output readable
        pass

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        self.server.stub._post(self)  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        self.server.stub._get(self)  # type: ignore[attr-defined]


class Stub:
    """State the handler methods above read and mutate.

    One instance per test: it owns the HTTP server, so two tests never share
    a session or job counter by accident.
    """

    def __init__(self, poll_delay: float = 3.0) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.approve_calls: list[dict[str, Any]] = []
        self.poll_delay = poll_delay
        self.polled = threading.Event()
        self._n_sessions = self._n_docs = self._n_images = self._n_jobs = 0

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.stub = self  # type: ignore[attr-defined]
        self._server.daemon_threads = True
        # A killed client aborts the connection out from under a handler
        # thread that is mid-sleep; the write that follows fails, and the
        # default handler prints a traceback for it. Harmless and noisy.
        self._server.handle_error = lambda *a: None  # type: ignore[method-assign]
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # ------------------------------------------------------------- routing --

    def _post(self, h: _Handler) -> None:
        path, body = h.path, h._body()

        if path == "/v1/sessions/init":
            self._n_sessions += 1
            session_id = f"sess_{self._n_sessions}"
            self.sessions[session_id] = {"documents": [], "jobs": {}}
            h._json(200, {"session_id": session_id})
            return

        if path == "/v1/documents/upload":
            fields = _parse_multipart(h.headers.get("Content-Type", ""), body)
            session_id = fields.get("session_id", b"").decode()
            self._n_docs += 1
            document_id, durable_id = f"doc_{self._n_docs}", f"uuid-{self._n_docs}"
            self.sessions.setdefault(session_id, {"documents": [], "jobs": {}})
            # `open_mode="new_focused"` on a session that holds nothing yet:
            # the one document just uploaded is the whole list.
            self.sessions[session_id]["documents"] = [
                {"document_id": document_id, "durable_document_id": durable_id}
            ]
            h._json(200, {"document_id": document_id, "persisted": True})
            return

        if path == "/v1/documents/images/upload-base64":
            self._n_images += 1
            h._json(200, {"url": f"http://stub.local/img/{self._n_images}.svg"})
            return

        if path == "/v1/chat/async":
            payload = json.loads(body or b"{}")
            session_id = str(payload["session_id"])
            document_id = payload.get("document_id", "")
            self._n_jobs += 1
            job_id = f"job_{self._n_jobs}"
            job = {
                "job_id": job_id,
                "session_id": session_id,
                "status": "awaiting_approval",
                "metadata": {
                    "pending_changes": [
                        {
                            "change_id": f"change_{self._n_jobs}",
                            "operation": "edit",
                            "chunk_id": "chunk_1",
                            "document_id": document_id,
                            "old_html": "<p>1.2 N·m</p>",
                            "new_html": "<p>1.6 N·m</p>",
                            "ai_explanation": "raised the torque",
                        }
                    ]
                },
            }
            self.sessions.setdefault(session_id, {"documents": [], "jobs": {}})
            self.sessions[session_id]["jobs"][job_id] = job
            self.jobs[job_id] = job
            h._json(200, {"job_id": job_id})
            return

        match = re.match(r"^/v1/chat/([^/]+)/approve$", path)
        if match:
            payload = json.loads(body or b"{}")
            self.approve_calls.append(payload)
            job_id = payload.get("job_id")
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = "denied"
            h._json(200, {"status": "ok"})
            return

        h._json(404, {"detail": f"stub has no route for POST {path}"})

    def _get(self, h: _Handler) -> None:
        path = h.path

        match = re.match(r"^/v1/sessions/([^/]+)/documents$", path)
        if match:
            session = self.sessions.get(match.group(1), {})
            h._json(200, {"documents": session.get("documents", [])})
            return

        match = re.match(r"^/v1/sessions/([^/]+)/jobs$", path)
        if match:
            session = self.sessions.get(match.group(1), {})
            h._json(200, {"jobs": list(session.get("jobs", {}).values())})
            return

        match = re.match(r"^/v1/jobs/([^/]+)$", path)
        if match:
            # The one deliberately slow endpoint. Signalled before the sleep,
            # so a caller waiting on `polled` knows the client is genuinely
            # blocked here rather than guessing from a timer.
            self.polled.set()
            time.sleep(self.poll_delay)
            h._json(200, self.jobs.get(match.group(1), {}))
            return

        h._json(404, {"detail": f"stub has no route for GET {path}"})
