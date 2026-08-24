"""Unit tests for the SuperDocs REST client — request shaping and response
parsing against a mocked transport. No network, no API key: same discipline
Task 1 states for its own suite, applied here to a REST client instead of a
pipeline.
"""

import asyncio
import base64
import json

import httpx

from app.superdocs.client import SuperDocsClient


def _client_with(handler) -> SuperDocsClient:
    client = SuperDocsClient(api_key="sk_test")
    client._client = httpx.AsyncClient(
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer sk_test"},
        transport=httpx.MockTransport(handler),
    )
    return client


def test_upload_base64_sends_bearer_auth_and_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk_test"
        assert request.url.path == "/v1/documents/upload-base64"
        payload = json.loads(request.content)
        assert payload == {
            "file_base64": "Zm9v",
            "filename": "sow.html",
            "session_id": "s1",
            "return_html": True,
        }
        return httpx.Response(
            200, json={"html": "<p>ok</p>", "session_id": "s1", "chunks_count": 3}
        )

    async def run():
        client = _client_with(handler)
        result = await client.upload_base64(
            file_base64="Zm9v", filename="sow.html", session_id="s1"
        )
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.session_id == "s1"
    assert result.chunks_count == 3


def test_chat_async_defaults_to_auto_approval_mode():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["approval_mode"] == "auto"
        return httpx.Response(200, json={"job_id": "job1", "session_id": "s1"})

    async def run():
        client = _client_with(handler)
        result = await client.chat_async(message="add a scope section", session_id="s1")
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.job_id == "job1"


def test_chat_async_passes_model_tier_and_thinking_depth_when_set():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model_tier"] == "max"
        assert payload["thinking_depth"] == "deep"
        return httpx.Response(200, json={"job_id": "job1", "session_id": "s1"})

    async def run():
        client = _client_with(handler)
        result = await client.chat_async(
            message="add a scope section",
            session_id="s1",
            model_tier="max",
            thinking_depth="deep",
        )
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.job_id == "job1"


def test_chat_async_omits_model_params_when_none():
    # When unset, the wire body must not carry model_tier/thinking_depth at
    # all — the server's defaults apply, same call shape as before.
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "model_tier" not in payload
        assert "thinking_depth" not in payload
        return httpx.Response(200, json={"job_id": "job1", "session_id": "s1"})

    async def run():
        client = _client_with(handler)
        result = await client.chat_async(message="add a scope section", session_id="s1")
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.job_id == "job1"


def test_get_job_tolerates_a_status_value_this_client_has_never_seen():
    # status is a plain str, not a closed enum — SuperDocs is a third-party
    # API, and a status this client doesn't recognize yet must surface, not
    # crash the caller. See schemas.py's module docstring.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job1", "status": "a_future_status"})

    async def run():
        client = _client_with(handler)
        result = await client.get_job("job1")
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.status == "a_future_status"
    assert result.metadata.pending_changes == []


def test_get_job_treats_null_pending_changes_as_empty_not_a_crash():
    # Confirmed against the real API: "nothing pending" comes back as
    # metadata.pending_changes: null, not [] or an absent key. Found the
    # hard way via `make smoke` — see PROGRESS.md M1.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"job_id": "job1", "status": "completed", "metadata": {"pending_changes": None}}
        )

    async def run():
        client = _client_with(handler)
        result = await client.get_job("job1")
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.metadata.pending_changes == []


def test_approve_sends_job_id_and_approved_not_a_changes_batch():
    # Confirmed against the real API's 422: it wants top-level {job_id,
    # approved}, not the {"changes": [...]} batch the docs described — see
    # PROGRESS.md M1.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/s1/approve"
        payload = json.loads(request.content)
        assert payload == {"job_id": "job1", "approved": True}
        return httpx.Response(200, json={"status": "ok"})

    async def run():
        client = _client_with(handler)
        await client.approve(session_id="s1", job_id="job1", approved=True)
        await client.aclose()

    asyncio.run(run())


def test_export_decodes_the_base64_json_warnings_header():
    warnings_header = base64.b64encode(json.dumps(["heads up"]).encode()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html></html>",
            headers={"x-export-warnings": warnings_header, "content-type": "text/html"},
        )

    async def run():
        client = _client_with(handler)
        result = await client.export(session_id="s1", format="html")
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.warnings == ["heads up"]
    assert result.content == b"<html></html>"


def test_export_with_no_warnings_header_returns_an_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html></html>", headers={"content-type": "text/html"})

    async def run():
        client = _client_with(handler)
        result = await client.export(session_id="s1", format="html")
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.warnings == []


def test_a_4xx_response_raises_rather_than_being_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    async def run():
        client = _client_with(handler)
        try:
            await client.upload_base64(file_base64="Zm9v", filename="x.html", session_id="s1")
        finally:
            await client.aclose()

    try:
        asyncio.run(run())
        raised = False
    except httpx.HTTPStatusError:
        raised = True
    assert raised
