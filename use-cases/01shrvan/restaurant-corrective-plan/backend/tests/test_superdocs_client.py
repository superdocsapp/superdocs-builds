from __future__ import annotations

import json

import httpx
import pytest

from app.superdocs_client import SuperDocsClient, SuperDocsError


def test_async_approval_flow_uses_human_gate_and_parses_pending_changes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/documents/upload":
            return httpx.Response(200, json={"html": "<html>uploaded</html>"})
        if request.url.path == "/v1/chat/async":
            payload = json.loads(request.content)
            assert payload["approval_mode"] == "ask_every_time"
            assert payload["document_html"] == "<html>uploaded</html>"
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        if request.url.path == "/v1/jobs/job-1":
            return httpx.Response(
                200,
                json={
                    "status": "awaiting_approval",
                    "metadata": {
                        "pending_changes": json.dumps(
                            [
                                {
                                    "change_id": "change-1",
                                    "chunk_id": "chunk-1",
                                    "document_id": "doc-1",
                                    "old_html": "<p>old</p>",
                                    "new_html": "<p>new</p>",
                                    "ai_explanation": "filled section",
                                }
                            ]
                        )
                    },
                },
            )
        if request.url.path == "/v1/chat/session-1/approve":
            payload = json.loads(request.content)
            assert payload == {
                "job_id": "job-1",
                "change_id": "change-1",
                "approved": True,
            }
            return httpx.Response(200, json={"status": "ok", "batch_complete": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = SuperDocsClient(
        api_key="test-key",
        base_url="https://api.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.draft_with_approval(
        document_html="<html>template</html>",
        message="Fill each violation section.",
        session_id="session-1",
        poll_interval_seconds=0,
    )

    assert result.job_id == "job-1"
    assert [request.url.path for request in requests] == [
        "/v1/documents/upload",
        "/v1/chat/async",
        "/v1/jobs/job-1",
        "/v1/chat/session-1/approve",
    ]


def test_upload_retries_once_for_warmup_failure() -> None:
    upload_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_count
        if request.url.path == "/v1/documents/upload":
            upload_count += 1
            if upload_count == 1:
                return httpx.Response(503, json={"detail": "warming up"})
            return httpx.Response(200, json={"html": "<html>uploaded</html>"})
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        if request.url.path == "/v1/jobs/job-1":
            return httpx.Response(
                200,
                json={
                    "status": "awaiting_approval",
                    "metadata": {
                        "pending_changes": [
                            {
                                "change_id": "change-1",
                                "old_html": "",
                                "new_html": "",
                            }
                        ]
                    },
                },
            )
        if request.url.path == "/v1/chat/session-1/approve":
            return httpx.Response(200, json={"status": "ok"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = SuperDocsClient(
        api_key="test-key",
        base_url="https://api.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.draft_with_approval(
        document_html="<html>template</html>",
        message="Fill each violation section.",
        session_id="session-1",
        poll_interval_seconds=0,
    )

    assert upload_count == 2


def test_polling_stops_after_max_polls_with_fix_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/documents/upload":
            return httpx.Response(200, json={"html": "<html>uploaded</html>"})
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        if request.url.path == "/v1/jobs/job-1":
            return httpx.Response(200, json={"status": "pending"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = SuperDocsClient(
        api_key="test-key",
        base_url="https://api.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(SuperDocsError) as error:
        client.draft_with_approval(
            document_html="<html>template</html>",
            message="Fill each violation section.",
            session_id="session-1",
            poll_interval_seconds=0,
            max_polls=2,
        )

    message = str(error.value)
    assert "polling stopped after 2 polls" in message
    assert "Increase max_polls" in message


def test_invalid_export_format_names_cause_and_fix() -> None:
    client = SuperDocsClient(
        api_key="test-key",
        base_url="https://api.test",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )

    with pytest.raises(SuperDocsError) as error:
        client.export(session_id="session-1", fmt="md")

    assert (
        str(error.value)
        == "export failed: format 'md' is not valid. Use 'doc', 'docx', 'html', 'markdown', 'pdf', 'txt'."
    )

