import pytest

from connector.errors import ValidationError
from connector.operations.edit_by_instruction import edit_by_instruction
from schemas.common import ApprovalMode, JobStatus, ModelTier
from schemas.edit_by_instruction import EditByInstructionInput
from tests.conftest import json_response


@pytest.mark.asyncio
async def test_sync_request_serialization(fake_server, client):
    fake_server.on("POST", "/v1/chat", lambda r: json_response(200, {
        "response": "Done", "session_id": "s1",
        "document_changes": {"updated_html": "<p>edited</p>", "version_id": "v2", "changes_summary": "Fixed clause 3"},
        "usage": {"input_tokens": 10, "output_tokens": 20, "cost_usd": 0.001},
    }))

    result = await edit_by_instruction(client, EditByInstructionInput(
        session_id="s1", instruction="Fix clause 3",
    ))

    sent = fake_server.last_request_json()
    assert sent["message"] == "Fix clause 3"
    assert sent["session_id"] == "s1"
    assert result.status == JobStatus.completed
    assert result.job_id is None
    assert result.updated_html == "<p>edited</p>"
    assert result.version_id == "v2"


@pytest.mark.asyncio
async def test_async_request_serialization(fake_server, client):
    fake_server.on("POST", "/v1/chat/async", lambda r: json_response(200, {
        "job_id": "job_abc", "session_id": "s1", "status": "pending",
    }))

    result = await edit_by_instruction(client, EditByInstructionInput(
        session_id="s1", instruction="Rewrite section 2", run_async=True,
    ))

    assert fake_server.requests[0].url.path == "/v1/chat/async"
    assert result.job_id == "job_abc"
    assert result.status == JobStatus.pending


@pytest.mark.asyncio
async def test_model_options_are_serialized(fake_server, client):
    fake_server.on("POST", "/v1/chat", lambda r: json_response(200, {"session_id": "s1"}))

    await edit_by_instruction(client, EditByInstructionInput(
        session_id="s1", instruction="x",
        model_tier=ModelTier.max, thinking_depth="deep",
    ))

    sent = fake_server.last_request_json()
    assert sent["model_tier"] == "max"
    assert sent["thinking_depth"] == "deep"


@pytest.mark.asyncio
async def test_ask_every_time_without_async_is_rejected_client_side(fake_server, client):
    with pytest.raises(ValidationError, match="run_async=True"):
        await edit_by_instruction(client, EditByInstructionInput(
            session_id="s1", instruction="x",
            approval_mode=ApprovalMode.ask_every_time, run_async=False,
        ))
    assert fake_server.requests == []  # rejected before any HTTP call


@pytest.mark.asyncio
async def test_ask_every_time_with_async_is_allowed(fake_server, client):
    fake_server.on("POST", "/v1/chat/async", lambda r: json_response(200, {
        "job_id": "job_1", "session_id": "s1", "status": "pending",
    }))
    result = await edit_by_instruction(client, EditByInstructionInput(
        session_id="s1", instruction="x",
        approval_mode=ApprovalMode.ask_every_time, run_async=True,
    ))
    assert result.job_id == "job_1"
    sent = fake_server.last_request_json()
    assert sent["approval_mode"] == "ask_every_time"


@pytest.mark.asyncio
async def test_document_html_only_sent_when_provided(fake_server, client):
    fake_server.on("POST", "/v1/chat", lambda r: json_response(200, {"session_id": "s1"}))

    await edit_by_instruction(client, EditByInstructionInput(session_id="s1", instruction="x"))
    assert "document_html" not in fake_server.last_request_json()

    await edit_by_instruction(client, EditByInstructionInput(
        session_id="s1", instruction="x", document_html="<p>loaded</p>",
    ))
    assert fake_server.last_request_json()["document_html"] == "<p>loaded</p>"
