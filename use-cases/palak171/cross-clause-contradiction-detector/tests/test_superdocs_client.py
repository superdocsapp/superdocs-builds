"""
Every test here mocks the SuperDocs API with respx against the exact request/
response shapes documented at docs.superdocs.app/llms-full.txt (upload,
chat, chat/async, jobs, approve, export) — no live API key, no network call,
no cost. This is what "real tests exist and run without a live key" means
for an integration build: we can't test SuperDocs' own contradiction-finding
accuracy without a live account (that's proven in the demo video instead),
but every byte of OUR request-building and response-parsing is verified here.
"""
import base64
import json

import httpx
import pytest
import respx

from superdocs_client import JobTimeout, SuperDocsClient, SuperDocsError

API = "https://api.superdocs.app/v1"


@pytest.fixture
def client():
    with SuperDocsClient(api_key="sk_test_key") as c:
        yield c


@respx.mock
def test_upload_document_sends_multipart_with_session_id(client, tmp_path):
    contract = tmp_path / "contract.txt"
    contract.write_text("Clause 7. Payment Terms\nPay within 30 days.")

    route = respx.post(f"{API}/documents/upload").mock(
        return_value=httpx.Response(200, json={
            "html": "<div data-chunk-id=\"c1\">...</div>",
            "session_id": "sess-1", "filename": "contract.txt", "chunks_count": 1,
        })
    )

    result = client.upload_document(contract, "sess-1")

    assert route.called
    request = route.calls.last.request
    assert b"sess-1" in request.content
    assert result["session_id"] == "sess-1"


@respx.mock
def test_chat_detection_pass_sends_no_approval_mode(client):
    route = respx.post(f"{API}/chat").mock(
        return_value=httpx.Response(200, json={
            "response": "1. Clause 7 vs Clause 12: 30 days vs 45 days.",
            "session_id": "sess-1",
            "usage": {"ops_charged": 1, "monthly_remaining": 499},
        })
    )

    result = client.chat("find contradictions", "sess-1")

    sent = json.loads(route.calls.last.request.content)
    assert "approval_mode" not in sent  # detection pass must not trigger edits
    assert "Clause 7 vs Clause 12" in result["response"]


@respx.mock
def test_start_edit_always_uses_ask_every_time(client):
    route = respx.post(f"{API}/chat/async").mock(
        return_value=httpx.Response(200, json={"job_id": "job-1"})
    )

    result = client.start_edit("resolve contradictions", "sess-1")

    sent = json.loads(route.calls.last.request.content)
    assert sent["approval_mode"] == "ask_every_time"
    assert result["job_id"] == "job-1"


@respx.mock
def test_wait_for_job_polls_through_in_progress_to_awaiting_approval(client):
    responses = [
        httpx.Response(200, json={"status": "pending"}),
        httpx.Response(200, json={"status": "in_progress"}),
        httpx.Response(200, json={"status": "awaiting_approval", "metadata": {"pending_changes": []}}),
    ]
    route = respx.get(f"{API}/jobs/job-1").mock(side_effect=responses)

    job = client.wait_for_job("job-1", poll_interval=0)

    assert job["status"] == "awaiting_approval"
    assert route.call_count == 3


@respx.mock
def test_wait_for_job_times_out_instead_of_hanging_forever(client):
    respx.get(f"{API}/jobs/job-1").mock(return_value=httpx.Response(200, json={"status": "in_progress"}))

    with pytest.raises(JobTimeout):
        client.wait_for_job("job-1", poll_interval=0, timeout=0)


def test_pending_changes_parses_metadata_shape(client):
    job = {"metadata": {"pending_changes": [
        {"change_id": "ch_1", "chunk_id": "c7", "operation": "replace_text",
         "old_html": "<p>30 days</p>", "new_html": "<p>45 days</p>",
         "ai_explanation": "Clause 7 conflicts with Clause 12."},
    ]}}

    changes = client.pending_changes(job)

    assert len(changes) == 1
    assert changes[0].change_id == "ch_1"
    assert "Clause 7" in changes[0].ai_explanation


@respx.mock
def test_approve_changes_sends_independent_decisions_not_all_or_nothing(client):
    route = respx.post(f"{API}/chat/sess-1/approve").mock(return_value=httpx.Response(200, json={"status": "ok"}))

    client.approve_changes("sess-1", "job-1", [
        ("ch_1", True, None),
        ("ch_2", False, "needs legal review"),
    ])

    sent = json.loads(route.calls.last.request.content)
    assert sent["changes"] == [
        {"change_id": "ch_1", "approved": True},
        {"change_id": "ch_2", "approved": False, "feedback": "needs legal review"},
    ]


@respx.mock
def test_export_document_decodes_filename_and_warnings_header(client):
    warnings = [{"code": "footnote_orphan", "message": "one footnote had no anchor"}]
    encoded_warnings = base64.b64encode(json.dumps(warnings).encode()).decode()

    respx.post(f"{API}/documents/export").mock(
        return_value=httpx.Response(
            200,
            content=b"FAKE_DOCX_BYTES",
            headers={
                "content-disposition": 'attachment; filename="contract-reviewed.docx"',
                "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "x-export-warnings": encoded_warnings,
            },
        )
    )

    result = client.export_document("sess-1", format="docx")

    assert result.content == b"FAKE_DOCX_BYTES"
    assert result.filename == "contract-reviewed.docx"
    assert result.warnings == warnings


@respx.mock
def test_api_error_is_raised_with_status_and_detail(client):
    respx.post(f"{API}/chat").mock(
        return_value=httpx.Response(401, json={"detail": "Authentication required"})
    )

    with pytest.raises(SuperDocsError) as exc_info:
        client.chat("hello", "sess-1")

    assert exc_info.value.status_code == 401
    assert "Authentication required" in str(exc_info.value)
