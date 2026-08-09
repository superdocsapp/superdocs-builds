import json
from pathlib import Path

import httpx
import pytest

from superdocs_adapter import ExportFormat, JobStatus, SuperDocsAPIError, SuperDocsClient


def make_client(handler: httpx.MockTransport) -> tuple[SuperDocsClient, httpx.Client]:
    http = httpx.Client(
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer test-key"},
        transport=handler,
    )
    return SuperDocsClient("test-key", http_client=http), http


def test_http_contract_covers_upload_chat_job_approval_and_export(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Original", encoding="utf-8")
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-key"
        if request.url.path == "/v1/documents/upload":
            assert request.method == "POST"
            assert "multipart/form-data" in request.headers["content-type"]
            return httpx.Response(
                200,
                json={
                    "session_id": "session-1",
                    "document_id": "document-1",
                    "title": "Sample",
                },
            )
        if request.url.path == "/v1/chat/async":
            body = json.loads(request.content)
            assert body["approval_mode"] == "ask_every_time"
            assert body["response_mode"] == "compact"
            return httpx.Response(200, json={"job_id": "job-1", "session_id": "session-1", "status": "pending"})
        if request.url.path == "/v1/jobs/job-1":
            assert request.url.params["compact"] == "true"
            return httpx.Response(
                200,
                json={
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "job_type": "chat",
                    "status": "awaiting_approval",
                    "created_at": "2026-08-09T00:00:00Z",
                    "updated_at": "2026-08-09T00:00:01Z",
                    "progress": 60,
                    "metadata": {
                        "pending_changes": [
                            {
                                "change_id": "change-1",
                                "chunk_id": "chunk-1",
                                "content": '{"before":"Old","after":"New"}',
                            }
                        ]
                    },
                },
            )
        if request.url.path == "/v1/chat/session-1/approve":
            body = json.loads(request.content)
            assert body == {
                "job_id": "job-1",
                "approved": True,
                "changes": [{"change_id": "change-1", "approved": True}],
            }
            return httpx.Response(200, json={"status": "processing"})
        if request.url.path == "/v1/documents/export":
            body = json.loads(request.content)
            assert body["session_id"] == "session-1"
            assert body["format"] == "txt"
            return httpx.Response(200, content=b"Updated", headers={"content-type": "text/plain"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client, http = make_client(httpx.MockTransport(respond))
    try:
        upload = client.upload_document(source, "session-1")
        job_id = client.start_edit(upload.session_id, "Replace Old with New")
        job = client.get_job(job_id)
        client.approve_changes(upload.session_id, job)
        exported = client.export_document(upload.session_id, export_format=ExportFormat.TXT)
    finally:
        http.close()

    assert upload.document_id == "document-1"
    assert job.status is JobStatus.AWAITING_APPROVAL
    assert job.proposed_changes[0].content == {"before": "Old", "after": "New"}
    assert exported.content == b"Updated"
    assert [request.url.path for request in requests] == [
        "/v1/documents/upload",
        "/v1/chat/async",
        "/v1/jobs/job-1",
        "/v1/chat/session-1/approve",
        "/v1/documents/export",
    ]


def test_export_follows_signed_download_url() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/documents/export":
            return httpx.Response(
                200,
                json={"download_url": "https://download.example/result.docx"},
            )
        if request.url.host == "download.example":
            return httpx.Response(
                200,
                content=b"docx-bytes",
                headers={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client, http = make_client(httpx.MockTransport(respond))
    try:
        exported = client.export_document(
            "session-1",
            export_format=ExportFormat.DOCX,
            filename="reviewed",
        )
    finally:
        http.close()

    assert exported.content == b"docx-bytes"
    assert exported.filename == "reviewed.docx"


def test_non_json_gateway_error_is_actionable() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(413, text="Request Entity Too Large", headers={"content-type": "text/html"})
    )
    client, http = make_client(transport)
    try:
        with pytest.raises(SuperDocsAPIError, match="HTTP 413"):
            client.export_document("session-1")
    finally:
        http.close()
