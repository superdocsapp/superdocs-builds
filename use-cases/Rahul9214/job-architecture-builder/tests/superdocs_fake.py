"""Deterministic SuperDocs HTTP fake. Contains no live credentials."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

from job_architecture.superdocs.models import SuperDocsSettings

OFFLINE_API_KEY = "sk_test_offline_not_a_real_key"

SAMPLE_CHANGE = {
    "change_id": "ch_1",
    "operation": "edit",
    "chunk_id": "chunk_a",
    "document_id": "doc_1",
    "old_html": "<p>before</p>",
    "new_html": "<p>after</p>",
    "ai_explanation": "Clarify the responsibility",
}


def offline_settings() -> SuperDocsSettings:
    return SuperDocsSettings(api_key=OFFLINE_API_KEY, base_url="https://api.superdocs.app")


def make_client(fake: FakeSuperDocsAPI):
    from job_architecture.superdocs.client import SuperDocsClient

    http = httpx.Client(transport=httpx.MockTransport(fake), timeout=5.0)
    return SuperDocsClient(offline_settings(), http=http)


class FakeSuperDocsAPI:
    """In-memory SuperDocs REST surface for offline tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.json_bodies: list[Any] = []
        self.documents_by_session: dict[str, list[dict[str, Any]]] = {}
        self.saved_documents: list[dict[str, Any]] = []
        self.templates: list[dict[str, Any]] = []
        self.jobs: dict[str, dict[str, Any]] = {}
        self.job_polls: dict[str, int] = {}
        self.job_sequences: dict[str, list[dict[str, Any]]] = {}
        self.default_sequence: list[dict[str, Any]] | None = None
        self.get_failures_remaining = 0
        self.get_timeouts_remaining = 0
        self.mutating_timeout = False
        self.mutating_connect_error = False
        self.status_overrides: dict[tuple[str, str], int] = {}
        self.retry_after: str | None = "2"
        self.export_bytes = b"PK\x03\x04-fake-docx-bytes"
        self.export_empty = False
        self.export_as_json = False
        self.approve_status = 200
        self._job_counter = 0
        self._doc_counter = 0
        self._template_counter = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.method.upper()
        path = urlparse(str(request.url)).path
        self.calls.append((method, path))
        if method != "GET":
            if self.mutating_timeout:
                raise httpx.ReadTimeout("read timeout")
            if self.mutating_connect_error:
                raise httpx.ConnectError("connection reset")
        if method == "GET" and self.get_timeouts_remaining > 0:
            self.get_timeouts_remaining -= 1
            raise httpx.ReadTimeout("read timeout")
        if method == "GET" and self.get_failures_remaining > 0:
            self.get_failures_remaining -= 1
            return httpx.Response(500, json={"detail": "temporary"}, request=request)

        override = self.status_overrides.get((method, path))
        if override:
            headers = {}
            if override == 429 and self.retry_after is not None:
                headers["Retry-After"] = self.retry_after
            body: dict[str, Any] = {"detail": f"forced {override}"}
            if override in (401, 403) and OFFLINE_API_KEY in (request.headers.get("authorization") or ""):
                body["detail"] = f"rejected {OFFLINE_API_KEY}"
            return httpx.Response(override, json=body, headers=headers, request=request)

        if method == "POST" and path == "/v1/documents/upload":
            return self._upload(request)
        if method == "POST" and path == "/v1/templates/upload-base64":
            return self._upload_template(request)
        if method == "GET" and path == "/v1/templates":
            return httpx.Response(200, json={"templates": self.templates}, request=request)
        if method == "GET" and path == "/v1/documents":
            return httpx.Response(200, json={"documents": self.saved_documents}, request=request)
        if method == "GET" and path.endswith("/documents") and "/sessions/" in path:
            session_id = path.split("/")[3]
            docs = self.documents_by_session.get(session_id, [])
            return httpx.Response(
                200,
                json={
                    "session_id": session_id,
                    "documents": docs,
                    "focused_document_id": docs[0]["document_id"] if docs else None,
                },
                request=request,
            )
        if method == "POST" and path.endswith("/documents/open"):
            return self._open(request, path)
        if method == "POST" and path == "/v1/chat/async":
            return self._chat_async(request)
        if method == "GET" and path.startswith("/v1/jobs/"):
            return self._get_job(request, path.rsplit("/", 1)[-1])
        if method == "POST" and path.endswith("/approve"):
            return self._approve(request)
        if method == "POST" and path.endswith("/continue"):
            body = _json_body(request)
            self.json_bodies.append(body)
            return httpx.Response(200, json={"ok": True, "continue": body.get("continue")}, request=request)
        if method == "POST" and path == "/v1/documents/export":
            return self._export(request)
        return httpx.Response(404, json={"detail": f"no fake for {method} {path}"}, request=request)

    def _upload(self, request: httpx.Request) -> httpx.Response:
        fields = _multipart_text_fields(request)
        session_id = fields.get("session_id") or "session"
        open_mode = fields.get("open_mode") or "replace"
        roster = self.documents_by_session.setdefault(session_id, [])
        if open_mode == "replace":
            roster.clear()
        self._doc_counter += 1
        document_id = f"doc_{self._doc_counter}"
        durable = f"durable-{self._doc_counter}"
        for item in roster:
            item["focused"] = False
        record = {
            "document_id": document_id,
            "durable_document_id": durable,
            "title": fields.get("filename") or f"file-{self._doc_counter}.md",
            "focused": True,
            "chunks_count": 1,
            "version_id": f"v{self._doc_counter}",
        }
        roster.append(record)
        self.saved_documents.append(
            {"id": durable, "title": record["title"], "session_count": 1, "updated_at": "2026-01-01"}
        )
        return httpx.Response(
            200,
            json={
                "session_id": session_id,
                "filename": record["title"],
                "document_id": document_id,
                "durable_document_id": durable,
                "focused_document_id": document_id,
                "documents": list(roster),
                "html": "<p>uploaded</p>",
            },
            request=request,
        )

    def _upload_template(self, request: httpx.Request) -> httpx.Response:
        body = _json_body(request)
        self.json_bodies.append(body)
        self._template_counter += 1
        template = {
            "template_id": f"tpl_{self._template_counter}",
            "name": body.get("filename"),
            "filename": body.get("filename"),
        }
        self.templates.append(template)
        return httpx.Response(200, json=template, request=request)

    def _open(self, request: httpx.Request, path: str) -> httpx.Response:
        session_id = path.split("/")[3]
        body = _json_body(request)
        self.json_bodies.append(body)
        roster = self.documents_by_session.setdefault(session_id, [])
        for doc_id in body.get("document_ids") or []:
            roster.append(
                {
                    "document_id": f"slot-{doc_id}",
                    "durable_document_id": doc_id,
                    "title": doc_id,
                    "focused": False,
                    "chunks_count": 1,
                }
            )
        if roster:
            roster[0]["focused"] = True
        return httpx.Response(
            200,
            json={
                "session_id": session_id,
                "documents": roster,
                "focused_document_id": roster[0]["document_id"] if roster else None,
            },
            request=request,
        )

    def _chat_async(self, request: httpx.Request) -> httpx.Response:
        body = _json_body(request)
        self.json_bodies.append(body)
        self._job_counter += 1
        job_id = f"job_{self._job_counter}"
        session_id = body.get("session_id") or "session"
        self.jobs[job_id] = {
            "request": body,
            "session_id": session_id,
        }
        if self.default_sequence is None:
            self.job_sequences[job_id] = [
                _job(job_id, session_id, "pending", progress=0),
                _job(job_id, session_id, "in_progress", progress=40),
                _job(
                    job_id,
                    session_id,
                    "awaiting_approval",
                    progress=80,
                    pending_changes=[SAMPLE_CHANGE],
                ),
            ]
        else:
            sequenced = []
            for item in self.default_sequence:
                copied = json.loads(json.dumps(item))
                copied["job_id"] = job_id
                copied["session_id"] = session_id
                sequenced.append(copied)
            self.job_sequences[job_id] = sequenced
        return httpx.Response(
            200,
            json={
                "job_id": job_id,
                "session_id": session_id,
                "status": "pending",
                "message": "Chat request queued for processing",
            },
            request=request,
        )

    def _get_job(self, request: httpx.Request, job_id: str) -> httpx.Response:
        sequence = self.job_sequences.get(job_id)
        if not sequence:
            return httpx.Response(404, json={"detail": "Job not found"}, request=request)
        index = self.job_polls.get(job_id, 0)
        snapshot = sequence[min(index, len(sequence) - 1)]
        self.job_polls[job_id] = index + 1
        return httpx.Response(200, json=snapshot, request=request)

    def _approve(self, request: httpx.Request) -> httpx.Response:
        body = _json_body(request)
        self.json_bodies.append(body)
        if self.approve_status >= 400:
            return httpx.Response(
                self.approve_status,
                json={"detail": "approval failed"},
                request=request,
            )
        return httpx.Response(200, json={"status": "accepted", "job_id": body.get("job_id")}, request=request)

    def _export(self, request: httpx.Request) -> httpx.Response:
        body = _json_body(request)
        self.json_bodies.append(body)
        if self.export_as_json:
            return httpx.Response(
                200,
                json={"detail": "not a file"},
                headers={"content-type": "application/json"},
                request=request,
            )
        if self.export_empty:
            return httpx.Response(
                200,
                content=b"",
                headers={"content-type": "application/octet-stream"},
                request=request,
            )
        return httpx.Response(
            200,
            content=self.export_bytes,
            headers={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            request=request,
        )


def _job(
    job_id: str,
    session_id: str,
    status: str,
    *,
    progress: int = 0,
    pending_changes: list[dict[str, Any]] | None = None,
    awaiting_kind: str | None = None,
    error: str | None = None,
    pending_as_string: bool = False,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if awaiting_kind:
        metadata["awaiting_kind"] = awaiting_kind
    if pending_changes is not None:
        metadata["pending_changes"] = (
            json.dumps(pending_changes) if pending_as_string else pending_changes
        )
    return {
        "job_id": job_id,
        "session_id": session_id,
        "job_type": "chat",
        "status": status,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "progress": progress,
        "error": error,
        "metadata": metadata,
        "result": {"response": "done"} if status == "completed" else None,
    }


def _json_body(request: httpx.Request) -> dict[str, Any]:
    if not request.content:
        return {}
    return json.loads(request.content.decode("utf-8"))


def _multipart_text_fields(request: httpx.Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    raw = request.content
    fields: dict[str, str] = {}
    if "boundary=" not in content_type:
        return fields
    boundary = content_type.split("boundary=", 1)[1].encode("ascii")
    for part in raw.split(b"--" + boundary):
        if b"Content-Disposition" not in part:
            continue
        header, _, body = part.partition(b"\r\n\r\n")
        header_text = header.decode("utf-8", errors="replace")
        if 'name="' not in header_text:
            continue
        name = header_text.split('name="', 1)[1].split('"', 1)[0]
        if "filename=" in header_text:
            filename = header_text.split('filename="', 1)[1].split('"', 1)[0]
            fields["filename"] = filename
            continue
        fields[name] = body.rstrip(b"\r\n").decode("utf-8", errors="replace")
    return fields
