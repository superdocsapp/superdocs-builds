"""SuperDocsClient tests -- entirely mocked HTTP via `responses`.

No network call in this file reaches api.superdocs.app (nor could it -- this sandbox
has no route to that host). Response fixtures are shaped to match what
docs.superdocs.app documents for each endpoint (see architecture.md §3), not
guessed.
"""
import io

import pytest
import responses

from winloss_superdocs.client import (
    OperationBudgetExceeded,
    SuperDocsAPIError,
    SuperDocsClient,
)
from winloss_superdocs.config import Settings

BASE = "https://api.superdocs.app"


@pytest.fixture
def settings():
    return Settings(
        api_key="sk_test",
        base_url=BASE,
        max_operations=20,
        small_sample_threshold=3,
        request_timeout_seconds=5,
        poll_interval_seconds=0,  # no real sleeping in tests
        poll_timeout_seconds=5,
    )


@pytest.fixture
def client(settings):
    return SuperDocsClient(settings, api_key="sk_test")


@responses.activate
def test_upload_attachment(client, tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("hello transcript")
    responses.add(
        responses.POST,
        f"{BASE}/v1/attachments/upload",
        json={"job_id": "job-1", "filename": "t.txt", "status": "processing", "message": "Upload successful."},
        status=200,
    )
    result = client.upload_attachment("sess-1", str(f))
    assert result["job_id"] == "job-1"


@responses.activate
def test_wait_for_attachment_polls_until_completed(client):
    responses.add(responses.GET, f"{BASE}/v1/jobs/job-1", json={"status": "processing"}, status=200)
    responses.add(responses.GET, f"{BASE}/v1/jobs/job-1", json={"status": "completed", "result": {}}, status=200)
    job = client.wait_for_attachment("sess-1", "job-1")
    assert job["status"] == "completed"


@responses.activate
def test_chat_sync_records_usage(client):
    responses.add(
        responses.POST,
        f"{BASE}/v1/chat",
        json={
            "response": "Done",
            "document_changes": {"updated_html": "<h1>Doc</h1>"},
            "usage": {"monthly_used": 1, "monthly_limit": 500, "monthly_remaining": 499, "ops_charged": 1},
        },
        status=200,
    )
    result = client.chat("sess-1", "hello")
    assert result["document_changes"]["updated_html"] == "<h1>Doc</h1>"
    assert client.usage.ops_used == 1


@responses.activate
def test_chat_async_returns_job_id(client):
    responses.add(responses.POST, f"{BASE}/v1/chat/async", json={"job_id": "job-42"}, status=200)
    result = client.chat_async("sess-1", "hello", approval_mode="ask_every_time")
    assert result["job_id"] == "job-42"


@responses.activate
def test_approve_change_single(client):
    responses.add(
        responses.POST,
        f"{BASE}/v1/chat/sess-1/approve",
        json={"status": "processing"},
        status=200,
        match=[responses.matchers.json_params_matcher({"job_id": "job-42", "approved": True, "change_id": "ch_1"})],
    )
    result = client.approve_change("sess-1", "job-42", approved=True, change_id="ch_1")
    assert result["status"] == "processing"


@responses.activate
def test_approve_change_batch_carries_top_level_approved(client):
    """Regression test for the documented footgun: top-level `approved` is required
    even for a batch decision, and is what our client always sends."""
    responses.add(
        responses.POST,
        f"{BASE}/v1/chat/sess-1/approve",
        json={"status": "processing"},
        status=200,
        match=[
            responses.matchers.json_params_matcher(
                {
                    "job_id": "job-42",
                    "approved": True,
                    "changes": [{"change_id": "ch_1", "approved": True}, {"change_id": "ch_2", "approved": False}],
                }
            )
        ],
    )
    client.approve_change(
        "sess-1",
        "job-42",
        approved=True,
        changes=[{"change_id": "ch_1", "approved": True}, {"change_id": "ch_2", "approved": False}],
    )


@responses.activate
def test_export_returns_bytes(client):
    responses.add(responses.POST, f"{BASE}/v1/documents/export", body=b"PK\x03\x04fakedocx", status=200)
    content = client.export(html="<h1>x</h1>", format="docx")
    assert content == b"PK\x03\x04fakedocx"


def test_export_requires_html_or_session_id(client):
    with pytest.raises(ValueError):
        client.export(format="docx")


@responses.activate
def test_sessions_init(client):
    responses.add(
        responses.POST,
        f"{BASE}/v1/sessions/init",
        json={"session_id": "brief-2025Q4", "documents": [{"id": "doc_1", "focused": True}]},
        status=200,
    )
    result = client.sessions_init(session_id="brief-2025Q4", document_ids=["doc_1"])
    assert result["session_id"] == "brief-2025Q4"


@responses.activate
def test_list_documents(client):
    responses.add(responses.GET, f"{BASE}/v1/documents", json={"documents": []}, status=200)
    result = client.list_documents()
    assert result["documents"] == []


@responses.activate
def test_401_raises_api_error(client):
    responses.add(responses.GET, f"{BASE}/v1/documents", json={"detail": "Invalid API key"}, status=401)
    with pytest.raises(SuperDocsAPIError) as exc_info:
        client.list_documents()
    assert exc_info.value.status_code == 401
    assert "Invalid API key" in exc_info.value.detail


@responses.activate
def test_429_retries_then_succeeds(client):
    responses.add(responses.GET, f"{BASE}/v1/documents", json={"detail": "rate limited"}, status=429, headers={"Retry-After": "0"})
    responses.add(responses.GET, f"{BASE}/v1/documents", json={"documents": []}, status=200)
    result = client.list_documents()
    assert result["documents"] == []


@responses.activate
def test_429_exhausts_retries_and_raises(client):
    for _ in range(5):
        responses.add(responses.GET, f"{BASE}/v1/documents", json={"detail": "rate limited"}, status=429, headers={"Retry-After": "0"})
    with pytest.raises(SuperDocsAPIError) as exc_info:
        client.list_documents()
    assert exc_info.value.status_code == 429


def test_operation_budget_exceeded_before_call(settings):
    settings = Settings(**{**settings.__dict__, "max_operations": 1})
    client = SuperDocsClient(settings, api_key="sk_test")
    client.usage.ops_used = 1  # simulate a prior billable call
    with pytest.raises(OperationBudgetExceeded):
        client.usage.check_budget("chat")


@responses.activate
def test_wait_for_job_reaches_awaiting_approval(client):
    responses.add(
        responses.GET,
        f"{BASE}/v1/jobs/job-1",
        json={
            "status": "awaiting_approval",
            "metadata": {
                "awaiting_kind": "change_review",
                "pending_changes": [{"change_id": "ch_1", "operation": "edit", "ai_explanation": "x"}],
            },
        },
        status=200,
    )
    job = client.wait_for_job("job-1")
    assert job["status"] == "awaiting_approval"
    assert job["metadata"]["pending_changes"][0]["change_id"] == "ch_1"
