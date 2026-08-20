"""SuperDocs client unit tests — httpx.MockTransport, no network.

Verifies request shaping (exact wire bodies) and response parsing for all
five endpoints, with special attention to the two approval shapes: the
documented batch `{changes: [...]}` and the individual `{job_id, approved,
chunk_id}` zoom-app confirmed against the live API.
"""

import asyncio
import base64
import json

import httpx

from app.superdocs.client import SuperDocsClient


def _client(handler) -> SuperDocsClient:
    c = SuperDocsClient(api_key="sk_test", base_url="https://api.superdocs.app")
    c._client = httpx.AsyncClient(
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer sk_test"},
        transport=httpx.MockTransport(handler),
    )
    return c


def test_upload_base64_sends_file_base64_field():
    seen = {}

    async def handler(request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"session_id": "s1", "html": "<p>x</p>", "chunks_count": 2})

    async def run():
        async with _client(handler) as c:
            await c.upload_base64(
                file_base64="QUJD", filename="essay.html", session_id="classroom-1"
            )

    asyncio.run(run())
    assert seen["json"]["file_base64"] == "QUJD"
    assert seen["json"]["filename"] == "essay.html"
    assert seen["json"]["session_id"] == "classroom-1"


def test_chat_async_sends_approval_mode():
    seen = {}

    async def handler(request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"job_id": "job1", "session_id": "s1"})

    async def run():
        async with _client(handler) as c:
            resp = await c.chat_async(
                message="Review for grammar", session_id="s1", approval_mode="ask_every_time"
            )
        assert resp.job_id == "job1"

    asyncio.run(run())
    assert seen["json"]["approval_mode"] == "ask_every_time"
    assert seen["json"]["session_id"] == "s1"


def test_chat_async_sends_selected_model_and_thinking_depth():
    """The browser never supplies these raw values; the backend sends the
    validated mapping on the one async HITL request."""
    seen = {}

    async def handler(request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"job_id": "job1", "session_id": "s1"})

    async def run():
        async with _client(handler) as c:
            await c.chat_async(
                message="Review for academic writing",
                session_id="s1",
                approval_mode="ask_every_time",
                model_tier="pro",
                thinking_depth="deep",
            )

    asyncio.run(run())
    assert seen["json"] == {
        "message": "Review for academic writing",
        "session_id": "s1",
        "approval_mode": "ask_every_time",
        "model_tier": "pro",
        "thinking_depth": "deep",
    }


def test_approve_batch_sends_documented_schema_with_change_id():
    """The current official schema — {job_id, approved, changes:
    [{change_id, approved}]}. Live-verified: this shape advances the job
    to completed; the nested identifier is change_id, not chunk_id."""
    seen = {}

    async def handler(request):
        seen["json"] = json.loads(request.content)
        seen["path"] = request.url.path
        return httpx.Response(200, json={"status": "ok", "batch_complete": True})

    async def run():
        async with _client(handler) as c:
            resp = await c.approve_batch(
                session_id="s1",
                job_id="job1",
                approved=True,
                changes=[
                    {"change_id": "chg1", "approved": True},
                    {"change_id": "chg2", "approved": False},
                ],
            )
        assert resp["batch_complete"] is True

    asyncio.run(run())
    assert seen["path"] == "/v1/chat/s1/approve"
    assert seen["json"] == {
        "job_id": "job1",
        "approved": True,
        "changes": [
            {"change_id": "chg1", "approved": True},
            {"change_id": "chg2", "approved": False},
        ],
    }


def test_approve_sends_individual_shape():
    """The individual shape zoom-app confirmed against the live API:
    {job_id, approved} required, chunk_id optional."""
    seen = {}

    async def handler(request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok", "message": "Approval processed"})

    async def run():
        async with _client(handler) as c:
            resp = await c.approve(
                session_id="s1", job_id="job1", approved=True, chunk_id="c1"
            )
        assert resp["status"] == "ok"

    asyncio.run(run())
    assert seen["json"] == {"job_id": "job1", "approved": True, "chunk_id": "c1"}


def test_get_job_coerces_null_pending_changes():
    """Live API returns metadata.pending_changes: null when nothing is
    pending — must parse as [] rather than crash."""
    payload = {
        "job_id": "job1",
        "status": "awaiting_approval",
        "metadata": {"pending_changes": None, "awaiting_kind": None},
    }

    async def handler(request):
        return httpx.Response(200, json=payload)

    async def run():
        async with _client(handler) as c:
            job = await c.get_job("job1")
        assert job.status == "awaiting_approval"
        assert job.metadata.pending_changes == []

    asyncio.run(run())


def test_get_job_parses_pending_changes():
    payload = {
        "job_id": "job1",
        "status": "awaiting_approval",
        "metadata": {
            "pending_changes": [
                {
                    "chunk_id": "c1",
                    "operation": "update",
                    "html_before": "<p>Thier</p>",
                    "html_after": "<p>Their</p>",
                }
            ]
        },
    }

    async def handler(request):
        return httpx.Response(200, json=payload)

    async def run():
        async with _client(handler) as c:
            job = await c.get_job("job1")
        assert job.metadata.pending_changes[0].chunk_id == "c1"
        assert job.metadata.pending_changes[0].html_before == "<p>Thier</p>"

    asyncio.run(run())


def test_get_job_completed_parses_document_changes_at_result():
    """A completed job's edits live at result.document_changes.changes."""
    payload = {
        "job_id": "job1",
        "status": "completed",
        "metadata": {"pending_changes": None},
        "result": {
            "response": "done",
            "document_changes": {
                "updated_html": "<p>Their</p>",
                "changes": [
                    {
                        "chunk_id": "c1",
                        "operation": "update",
                        "old_html": "<p>Thier</p>",
                        "new_html": "<p>Their</p>",
                    }
                ],
            },
        },
    }

    async def handler(request):
        return httpx.Response(200, json=payload)

    async def run():
        async with _client(handler) as c:
            job = await c.get_job("job1")
        changes = job.document_changes.changes
        assert len(changes) == 1
        assert changes[0].old_html == "<p>Thier</p>"
        assert changes[0].new_html == "<p>Their</p>"

    asyncio.run(run())


def test_export_returns_binary_and_parses_warnings_header():
    encoded = base64.b64encode(json.dumps(["minor loss"]).encode())

    async def handler(request):
        return httpx.Response(
            200,
            content=b"PK\x03\x04fake-docx",
            headers={
                "content-type": (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                "x-export-warnings": encoded.decode(),
            },
        )

    async def run():
        async with _client(handler) as c:
            result = await c.export(session_id="s1", format="docx")
        assert result.content == b"PK\x03\x04fake-docx"
        assert result.warnings == ["minor loss"]

    asyncio.run(run())


def test_http_error_raises_httpx_status_error():
    async def handler(request):
        return httpx.Response(422, json={"detail": "Field required"})

    async def run():
        async with _client(handler) as c:
            try:
                await c.chat_async(message="x", session_id="s1")
            except httpx.HTTPStatusError as exc:
                assert exc.response.status_code == 422
                return
            raise AssertionError("expected httpx.HTTPStatusError")

    asyncio.run(run())
