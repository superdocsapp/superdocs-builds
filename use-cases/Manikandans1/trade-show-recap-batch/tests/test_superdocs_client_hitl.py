"""Proves SuperDocsClient.edit_document() exercises the real, documented
HITL sequence — same contract as
extensions/object-storage-pipeline/tests/test_superdocs_client_hitl.py,
duplicated here (rather than shared) so this build stays self-contained.
See that file's module docstring for the full rationale."""

from __future__ import annotations

import json

import httpx
import pytest

from app.superdocs_client import SuperDocsClient, SuperDocsError


def _json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


class ScriptedJobServer:
    def __init__(self, job_id: str = "job_abc"):
        self.job_id = job_id
        self.calls: list[tuple[str, str, dict | None]] = []
        self._poll_count = 0
        self.approved_change_ids: list[str] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))

        if method == "POST" and path == "/v1/chat/async":
            assert body["approval_mode"] == "ask_every_time"
            return _json_response(
                200, {"job_id": self.job_id, "session_id": body["session_id"], "status": "pending"}
            )
        if method == "GET" and path == f"/v1/jobs/{self.job_id}":
            return self._poll_response()
        if method == "POST" and path.endswith("/approve"):
            assert body["job_id"] == self.job_id
            assert body["approved"] is True
            self.approved_change_ids = [c["change_id"] for c in body["changes"]]
            return _json_response(200, {"status": "ok"})
        raise AssertionError(f"unexpected request: {method} {path}")

    def _poll_response(self) -> httpx.Response:
        self._poll_count += 1
        if self._poll_count == 1:
            return _json_response(
                200,
                {
                    "job_id": self.job_id,
                    "status": "awaiting_approval",
                    "metadata": {
                        "pending_changes": [
                            {
                                "change_id": "ch_1",
                                "operation": "edit",
                                "chunk_id": "abc",
                                "old_html": "<p>{{lead_name}}</p>",
                                "new_html": "<p>Jane Doe</p>",
                                "ai_explanation": "Substituted lead_name",
                            }
                        ]
                    },
                },
            )
        return _json_response(
            200,
            {
                "job_id": self.job_id,
                "status": "completed",
                "result": {
                    "response": "Done.",
                    "session_id": "recap-L001",
                    "document_changes": {
                        "updated_html": "<div>final</div>",
                        "changes_summary": "1 section edited",
                    },
                    "usage": {"monthly_used": 1, "monthly_remaining": 499},
                },
            },
        )


def test_ask_every_time_polls_reviews_and_auto_approves_then_returns_result():
    server = ScriptedJobServer()
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    client = SuperDocsClient(
        base_url="https://fake-superdocs", api_key="unused", http_client=http,
        poll_interval_seconds=0, max_wait_seconds=5,
    )

    result = client.edit_document("recap-L001", "substitute the values", approval_mode="ask_every_time")

    assert result.updated_html == "<div>final</div>"
    kinds = [(m, p) for m, p, _ in server.calls]
    assert kinds == [
        ("POST", "/v1/chat/async"),
        ("GET", "/v1/jobs/job_abc"),
        ("POST", "/v1/chat/recap-L001/approve"),
        ("GET", "/v1/jobs/job_abc"),
    ]
    assert server.approved_change_ids == ["ch_1"]


def test_approve_all_is_a_single_synchronous_call():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat"
        body = json.loads(request.content)
        assert body["approval_mode"] == "approve_all"
        return _json_response(
            200,
            {
                "response": "Done.",
                "session_id": body["session_id"],
                "document_changes": {"updated_html": "<div>ok</div>", "changes_summary": "filled"},
                "usage": {"monthly_used": 1, "monthly_remaining": 499},
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SuperDocsClient(base_url="https://fake-superdocs", api_key="unused", http_client=http)

    result = client.edit_document("recap-L001", "substitute the values", approval_mode="approve_all")
    assert result.updated_html == "<div>ok</div>"


def test_upload_document_posts_multipart_with_session_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/documents/upload"
        captured["body"] = request.read()
        return _json_response(
            200, {"session_id": "recap-L001", "filename": "template.txt", "chunks_count": 3, "version_id": "v1"}
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SuperDocsClient(base_url="https://fake-superdocs", api_key="unused", http_client=http)

    info = client.upload_document(b"SUPERDOCS TEMPLATE {{lead_name}}", "template.txt", "recap-L001")
    assert info.session_id == "recap-L001"
    assert info.chunks_count == 3
    assert b"SUPERDOCS TEMPLATE" in captured["body"]
    assert b'name="session_id"' in captured["body"]


def test_export_bytes_returns_raw_document_content():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/documents/export"
        body = json.loads(request.content)
        assert body["format"] == "txt"
        return httpx.Response(200, content=b"final recap text")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SuperDocsClient(base_url="https://fake-superdocs", api_key="unused", http_client=http)

    content = client.export_bytes("recap-L001", "txt")
    assert content == b"final recap text"


def test_failed_job_raises_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/async":
            return _json_response(200, {"job_id": "j1", "session_id": "s", "status": "pending"})
        if request.url.path == "/v1/jobs/j1":
            return _json_response(200, {"job_id": "j1", "status": "failed", "error": "boom"})
        raise AssertionError("unexpected call")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SuperDocsClient(
        base_url="https://fake-superdocs", api_key="unused", http_client=http,
        poll_interval_seconds=0, max_wait_seconds=5,
    )
    with pytest.raises(SuperDocsError, match="boom"):
        client.edit_document("s", "substitute", approval_mode="ask_every_time")
