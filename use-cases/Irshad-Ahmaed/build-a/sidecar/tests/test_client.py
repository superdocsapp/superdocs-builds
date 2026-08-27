"""Tests for the SuperDocs client (mocked)."""

import httpx
import pytest
import respx

from build_a.client import AuthError, OperationTracker, SuperDocsClient, SuperDocsError


def test_tracker_counts_ops() -> None:
    tracker = OperationTracker()
    tracker.record("start_session", 1, "test")
    tracker.record("export", 0, "test")
    assert tracker.total_ops == 1
    assert len(tracker.history) == 2


def test_missing_api_key_raises() -> None:
    import os
    old = os.environ.pop("SUPERDOCS_API_KEY", None)
    try:
        with pytest.raises(AuthError):
            SuperDocsClient(api_key="")
    finally:
        if old:
            os.environ["SUPERDOCS_API_KEY"] = old


@pytest.mark.asyncio
@respx.mock
async def test_start_session_calls_correct_endpoint() -> None:
    respx.post("https://api.superdocs.app/v1/chat").mock(
        return_value=httpx.Response(200, json={
            "response": "ok",
            "session_id": "test-session",
            "document_changes": None,
        })
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        result = await client.start_session("<p>Hello</p>", "test-session")
        assert result.response == "ok"
        assert client.tracker.total_ops == 1


@pytest.mark.asyncio
@respx.mock
async def test_export_returns_download_url() -> None:
    respx.post("https://api.superdocs.app/v1/documents/export").mock(
        return_value=httpx.Response(
            200, json={"download_url": "https://example.com/file.pdf", "format": "pdf"}
        )
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        result = await client.export(session_id="test-session", format="pdf")
        assert result.download_url == "https://example.com/file.pdf"
        assert client.tracker.total_ops == 0  # export is free


@pytest.mark.asyncio
@respx.mock
async def test_list_sessions() -> None:
    respx.get("https://api.superdocs.app/v1/sessions").mock(
        return_value=httpx.Response(200, json={
            "sessions": [
                {
                    "session_id": "s1",
                    "created_at": "2025-01-01T00:00:00Z",
                    "last_activity": "2025-01-01T01:00:00Z",
                    "message_count": 5,
                    "preview": "First session",
                },
                {
                    "session_id": "s2",
                    "created_at": "2025-01-02T00:00:00Z",
                    "last_activity": "2025-01-02T01:00:00Z",
                    "message_count": 3,
                    "preview": "Second session",
                },
            ],
            "total": 2,
        })
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        sessions = await client.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].session_id == "s1"


@pytest.mark.asyncio
async def test_export_requires_session_or_html() -> None:
    async with SuperDocsClient(api_key="sk_test_key") as client:
        with pytest.raises(SuperDocsError, match="requires either"):
            await client.export()


@pytest.mark.asyncio
@respx.mock
async def test_export_handles_direct_binary_pdf() -> None:
    respx.post("https://api.superdocs.app/v1/documents/export").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.4 binary content \xd3\xff",
        )
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        result = await client.export(session_id="test-session", format="pdf")
        assert result.content == b"%PDF-1.4 binary content \xd3\xff"
        assert result.download_url is None
        assert client.tracker.total_ops == 0
