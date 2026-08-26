"""Integration tests for src/integrations/superdocs_client.py against a mock
transport seeded with real response bodies recorded from the live SuperDocs
API. No network calls; no SuperDocs quota consumed.
"""

from __future__ import annotations

import os

import httpx
import pytest
import respx

from src.integrations.superdocs_client import (
    SUPERDOCS_MCP_URL,
    SuperDocsParseError,
    SuperDocsRpcError,
    approve_change,
    export_document,
    poll_job,
    propose_change,
    upload_document,
)
from tests.integration.superdocs_fixtures import (
    APPROVE_CHANGE_ENVELOPE,
    CHAT_ASYNC_QUEUED_ENVELOPE,
    EXPORT_DOCUMENT_ENVELOPE,
    GET_JOB_AWAITING_APPROVAL_ENVELOPE,
    JOB_NOT_FOUND_IS_ERROR_ENVELOPE,
    MALFORMED_INNER_JSON_ENVELOPE,
    UPLOAD_DOCUMENT_ENVELOPE,
)


@pytest.fixture(autouse=True)
def superdocs_api_key(monkeypatch):
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_key")


@pytest.mark.asyncio
async def test_upload_document_parses_recorded_response():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).respond(200, json=UPLOAD_DOCUMENT_ENVELOPE)
        async with httpx.AsyncClient() as client:
            result = await upload_document(client, "contract_01_northstar.md", b"dummy", "smoketest-001")

    assert result.session_id == "smoketest-001"
    assert result.chunks_count == 34
    assert result.version_id == "a3b1e163-c48d-497c-82b9-39f916751ccf"


@pytest.mark.asyncio
async def test_propose_change_returns_job_id():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).respond(200, json=CHAT_ASYNC_QUEUED_ENVELOPE)
        async with httpx.AsyncClient() as client:
            job_id = await propose_change(client, "smoketest-001", "scoped rate-only instruction")

    assert job_id == "3585ccfb-9281-4071-901c-af64f80eabc6"


@pytest.mark.asyncio
async def test_poll_job_parses_pending_changes_from_recorded_awaiting_approval():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).respond(200, json=GET_JOB_AWAITING_APPROVAL_ENVELOPE)
        async with httpx.AsyncClient() as client:
            status = await poll_job(client, "3585ccfb-9281-4071-901c-af64f80eabc6")

    assert status.status == "awaiting_approval"
    assert len(status.pending_changes) == 1
    change = status.pending_changes[0]
    assert change.change_id == "41c3fc53-b2f7-4bea-b887-aa05f76a80ea"
    assert change.old_html is None
    assert "Schedule A" in change.new_html
    assert "United States" in change.new_html
    assert status.cumulative_tokens == 251300


@pytest.mark.asyncio
async def test_poll_job_raises_structured_error_on_malformed_inner_json():
    """The second, independent JSON parse (inside result.content[0].text)
    must fail loudly and structured, never silently return an empty list."""

    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).respond(200, json=MALFORMED_INNER_JSON_ENVELOPE)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SuperDocsParseError) as excinfo:
                await poll_job(client, "abc")

    error = excinfo.value
    assert error.what
    assert error.likely_cause
    assert error.next_action
    assert "pending_changes" in error.what or "result" in error.what


@pytest.mark.asyncio
async def test_iserror_true_response_raises_structured_rpc_error_not_parse_error():
    """SuperDocs signals tool-level failures via result.isError=true with a
    plain-text (non-JSON) message, distinct from a JSON-RPC `error` object.
    This must surface as SuperDocsRpcError naming the actual cause (e.g. a
    404 'Job not found'), never be misreported as a JSON parse failure."""

    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).respond(200, json=JOB_NOT_FOUND_IS_ERROR_ENVELOPE)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SuperDocsRpcError) as excinfo:
                await poll_job(client, "some-expired-job-id")

    error = excinfo.value
    assert "Job not found" in error.likely_cause
    assert error.what
    assert error.next_action


@pytest.mark.asyncio
async def test_approve_change_parses_recorded_response():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).respond(200, json=APPROVE_CHANGE_ENVELOPE)
        async with httpx.AsyncClient() as client:
            result = await approve_change(
                client, "smoketest-001", "job-1", "change-1", approved=True
            )

    assert result.status == "ok"
    assert result.batch_complete is True


@pytest.mark.asyncio
async def test_export_document_returns_inline_text_and_omits_untouched_clauses_intact():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).respond(200, json=EXPORT_DOCUMENT_ENVELOPE)
        async with httpx.AsyncClient() as client:
            markdown = await export_document(client, "smoketest-001", "markdown")

    assert "Schedule A — Rate Card" in markdown
    assert "United States" in markdown
    # Non-rate content is proven untouched: Article 7's exact notice-period
    # sentence survives byte-for-byte after the rate-table edit.
    assert (
        "Either Party may propose an amendment to the Rate Card by delivering "
        "written notice to the other Party at least **thirty (30) calendar days**"
        in markdown
    )


@pytest.mark.asyncio
async def test_missing_api_key_raises_structured_error(monkeypatch):
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    async with httpx.AsyncClient() as client:
        with pytest.raises(Exception) as excinfo:
            await upload_document(client, "f.md", b"x", "s1")
    assert "SUPERDOCS_API_KEY" in str(excinfo.value)


@pytest.mark.asyncio
async def test_transport_error_is_structured():
    def raise_timeout(request):
        raise httpx.ConnectTimeout("connect timed out")

    with respx.mock(assert_all_called=True) as mock:
        mock.post(SUPERDOCS_MCP_URL).mock(side_effect=raise_timeout)
        async with httpx.AsyncClient() as client:
            with pytest.raises(Exception) as excinfo:
                await upload_document(client, "f.md", b"x", "s1")

    assert hasattr(excinfo.value, "what")
    assert hasattr(excinfo.value, "likely_cause")
    assert hasattr(excinfo.value, "next_action")
