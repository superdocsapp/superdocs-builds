import json

import httpx
import pytest

from edit_precision_evaluator.config import Settings
from edit_precision_evaluator.superdocs_client import SuperDocsClient


@pytest.mark.asyncio
async def test_analyze_uses_server_side_bearer_auth_and_reads_usage() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "result": {"response": '{"chunk_ids":["target"]}'},
                "usage": {"ops_charged": 1, "monthly_used": 5},
            },
        )

    settings = Settings(api_key="test-api-key", poll_interval_seconds=0.001)
    async with SuperDocsClient(settings, transport=httpx.MockTransport(handler)) as client:
        outcome = await client.analyze(
            document_html='<p data-chunk-id="target">Old</p>',
            message="Find target",
            session_id="search-1",
        )

    assert outcome.response_text == '{"chunk_ids":["target"]}'
    assert outcome.operations_charged == 1
    assert captured[0].headers["authorization"] == "Bearer test-api-key"
    assert captured[0].url.path == "/v1/chat"


@pytest.mark.asyncio
async def test_async_edit_approves_pending_batch_and_returns_final_html() -> None:
    states = iter(["awaiting_approval", "completed"])
    approval_bodies: list[dict] = []
    final_html = '<p data-chunk-id="target">New</p>'

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "job-1"})
        if request.url.path == "/v1/jobs/job-1":
            status = next(states)
            if status == "awaiting_approval":
                return httpx.Response(
                    200,
                    json={
                        "status": status,
                        "metadata": {
                            "pending_changes": json.dumps(
                                {
                                    "changes": [
                                        {
                                            "change_id": "change-1",
                                            "chunk_id": "target",
                                            "old_html": "Old",
                                            "new_html": "New",
                                        }
                                    ]
                                }
                            )
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "result": {
                        "response": "Done",
                        "document_changes": {"updated_html": final_html},
                    },
                    "usage": {"ops_charged": 1},
                },
            )
        if request.url.path == "/v1/chat/session-1/approve":
            approval_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "in_progress"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        api_key="test-api-key",
        poll_interval_seconds=0.001,
        job_timeout_seconds=1,
    )
    async with SuperDocsClient(settings, transport=httpx.MockTransport(handler)) as client:
        outcome = await client.edit_with_approval(
            document_html='<p data-chunk-id="target">Old</p>',
            message="Change Old to New",
            session_id="session-1",
        )

    assert outcome.updated_html == final_html
    assert outcome.operations_charged == 1
    assert outcome.proposed_changes[0]["change_id"] == "change-1"
    assert approval_bodies == [
        {
            "job_id": "job-1",
            "approved": True,
            "changes": [{"change_id": "change-1", "approved": True}],
        }
    ]


@pytest.mark.asyncio
async def test_upload_and_export_complete_the_document_loop() -> None:
    requests_seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        if request.url.path == "/v1/documents/upload":
            assert request.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(
                200,
                json={
                    "html": '<p data-chunk-id="parsed">Policy</p>',
                    "filename": "policy.html",
                    "chunks_count": 1,
                },
            )
        if request.url.path == "/v1/documents/export":
            return httpx.Response(
                200,
                content=b"<html>exported</html>",
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(api_key="test-api-key")
    async with SuperDocsClient(settings, transport=httpx.MockTransport(handler)) as client:
        uploaded = await client.upload_document(
            filename="policy.html",
            content=b"<p>Policy</p>",
            session_id="loop-1",
        )
        exported = await client.export_document(
            session_id="loop-1",
            filename="finished.html",
            format="html",
        )

    assert uploaded.chunks_count == 1
    assert uploaded.html == '<p data-chunk-id="parsed">Policy</p>'
    assert exported.content == b"<html>exported</html>"
    assert [request.url.path for request in requests_seen] == [
        "/v1/documents/upload",
        "/v1/documents/export",
    ]
