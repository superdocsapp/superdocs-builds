import json
from pathlib import Path

import httpx
import pytest

from superdocs_adapter import (
    ConfigurationError,
    ExportFormat,
    InvalidResponseError,
    JobStatus,
    SuperDocsAPIError,
    SuperDocsClient,
)


def make_client(handler: httpx.MockTransport) -> tuple[SuperDocsClient, httpx.Client]:
    http = httpx.Client(
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer test-key"},
        transport=handler,
    )
    return SuperDocsClient("test-key", http_client=http, upload_http_client=http), http


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
            return httpx.Response(
                200, json={"job_id": "job-1", "session_id": "session-1", "status": "pending"}
            )
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
                headers={
                    "content-type": (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                },
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
        lambda _: httpx.Response(
            413, text="Request Entity Too Large", headers={"content-type": "text/html"}
        )
    )
    client, http = make_client(transport)
    try:
        with pytest.raises(SuperDocsAPIError, match="HTTP 413"):
            client.export_document("session-1")
    finally:
        http.close()


def test_large_document_uses_presigned_streaming_upload(tmp_path: Path) -> None:
    source = tmp_path / "large.txt"
    source.write_bytes(b"large-document")
    api_requests: list[str] = []
    storage_requests: list[httpx.Request] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        api_requests.append(request.url.path)
        if request.url.path == "/v1/uploads":
            body = json.loads(request.content)
            assert body["size_bytes"] == len(b"large-document")
            assert body["purpose"] == "document"
            return httpx.Response(
                200,
                json={
                    "upload_id": "upload-1",
                    "upload_url": "https://storage.example/upload-1",
                    "expires_at": "2026-08-09T00:05:00Z",
                    "expires_in_seconds": 300,
                    "max_size_bytes": 104857600,
                    "curl_example": "curl ...",
                },
            )
        if request.url.path == "/v1/uploads/upload-1/process":
            body = json.loads(request.content)
            assert body == {
                "session_id": "session-1",
                "filename": "large.txt",
                "parse_mode": "document",
                "return_html": False,
            }
            return httpx.Response(
                200,
                json={
                    "session_id": "session-1",
                    "filename": "large.txt",
                    "status": "completed",
                    "parse_mode": "document",
                },
            )
        raise AssertionError(f"Unexpected API request: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        storage_requests.append(request)
        assert request.url == "https://storage.example/upload-1"
        assert request.content == b"large-document"
        return httpx.Response(200)

    api = httpx.Client(
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer test-key"},
        transport=httpx.MockTransport(api_handler),
    )
    storage = httpx.Client(transport=httpx.MockTransport(storage_handler))
    client = SuperDocsClient(
        "test-key",
        http_client=api,
        upload_http_client=storage,
        large_upload_threshold=1,
    )
    try:
        upload = client.upload_document(source, "session-1")
    finally:
        api.close()
        storage.close()

    assert upload.session_id == "session-1"
    assert api_requests == ["/v1/uploads", "/v1/uploads/upload-1/process"]
    assert len(storage_requests) == 1


def test_list_session_jobs_supports_start_edit_recovery() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/sessions/session-1/jobs"
        assert str(request.url.params) == "limit=1&compact=true"
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "job_id": "job-1",
                        "session_id": "session-1",
                        "job_type": "chat",
                        "status": "in_progress",
                        "created_at": "2026-08-09T00:00:00Z",
                        "updated_at": "2026-08-09T00:00:01Z",
                        "progress": 30,
                    }
                ],
                "total": 1,
            },
        )

    client, http = make_client(httpx.MockTransport(respond))
    try:
        jobs = client.list_session_jobs("session-1")
    finally:
        http.close()

    assert len(jobs) == 1
    assert jobs[0].job_id == "job-1"
    assert jobs[0].status is JobStatus.IN_PROGRESS


def test_unsupported_input_fails_before_network_call(tmp_path: Path) -> None:
    source = tmp_path / "sheet.xlsx"
    source.write_bytes(b"not-a-supported-output")
    client, http = make_client(
        httpx.MockTransport(lambda request: pytest.fail(f"Unexpected request: {request.url}"))
    )
    try:
        with pytest.raises(ConfigurationError, match="Unsupported input type"):
            client.upload_document(source, "session-1")
    finally:
        http.close()


@pytest.mark.parametrize(
    "status, message, suggestion",
    [
        (401, "bad key", "verify SUPERDOCS_API_KEY"),
        (429, "slow down", "rate-limit window"),
        (503, "unavailable", "saved checkpoint"),
    ],
)
def test_api_errors_include_remediation(status: int, message: str, suggestion: str) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json={"detail": message}))
    client, http = make_client(transport)
    try:
        with pytest.raises(SuperDocsAPIError, match=suggestion):
            client.export_document("session-1")
    finally:
        http.close()


def test_successful_non_json_response_is_rejected() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, text="not-json", headers={"content-type": "application/json"})
    )
    client, http = make_client(transport)
    try:
        with pytest.raises(InvalidResponseError, match="non-JSON"):
            client.export_document("session-1")
    finally:
        http.close()


def test_session_job_list_requires_array() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"jobs": {}}))
    client, http = make_client(transport)
    try:
        with pytest.raises(InvalidResponseError, match="jobs array"):
            client.list_session_jobs("session-1")
    finally:
        http.close()


def test_empty_instruction_fails_before_network() -> None:
    client, http = make_client(
        httpx.MockTransport(lambda request: pytest.fail(f"Unexpected request: {request.url}"))
    )
    try:
        with pytest.raises(ConfigurationError, match="cannot be empty"):
            client.start_edit("session-1", "   ")
    finally:
        http.close()
