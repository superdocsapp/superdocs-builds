"""Offline SuperDocs HTTP contract tests. No live key and no network."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from job_architecture.superdocs.config import load_settings
from job_architecture.superdocs.errors import (
    AmbiguousOutcomeError,
    ApprovalError,
    AuthenticationError,
    ConfigurationError,
    ExportError,
    JobFailedError,
    JobTimeoutError,
    MalformedResponseError,
    ProposedChangeParseError,
    RateLimitError,
    TransientHttpError,
)
from job_architecture.superdocs.models import ExportRequest, ReviewDecision
from tests.superdocs_fake import (
    OFFLINE_API_KEY,
    SAMPLE_CHANGE,
    FakeSuperDocsAPI,
    _job,
    make_client,
)


def test_missing_api_key():
    with pytest.raises(ConfigurationError, match="SUPERDOCS_API_KEY"):
        load_settings(environ={"SUPERDOCS_BASE_URL": "https://api.superdocs.app"}, require_api_key=True)


def test_settings_never_print_the_key():
    settings = load_settings(
        environ={
            "SUPERDOCS_API_KEY": OFFLINE_API_KEY,
            "SUPERDOCS_BASE_URL": "https://api.superdocs.app",
            "REQUEST_TIMEOUT_SECONDS": "30",
        }
    )
    assert OFFLINE_API_KEY not in repr(settings)
    assert OFFLINE_API_KEY not in str(settings)
    assert settings.timeout_seconds == 30


def test_upload_success_and_multi_document_isolation():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    first = client.upload_document("a.md", b"# A", session_id="sess-a", open_mode="new_focused")
    second = client.upload_document("b.md", b"# B", session_id="sess-a", open_mode="new_focused")
    other = client.upload_document("c.md", b"# C", session_id="sess-b", open_mode="new_focused")
    assert first.document.document_id != second.document.document_id
    assert first.document.durable_document_id != second.document.durable_document_id
    roster = client.list_session_documents("sess-a")
    ids = {item.document_id for item in roster.documents}
    assert first.document.document_id in ids
    assert second.document.document_id in ids
    assert other.document.document_id not in ids
    other_roster = client.list_session_documents("sess-b")
    assert {item.document_id for item in other_roster.documents} == {other.document.document_id}


def test_template_upload_and_reuse_ids():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    uploaded = client.upload_template("framework.md", b"# Framework")
    listed = client.list_templates()
    assert uploaded.template_id.startswith("tpl_")
    assert listed[0].template_id == uploaded.template_id


def test_search_documents_uses_reviewed_cross_session_chat():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    accepted = client.search_documents("profiles that mention IC3", session_id="sess-search")
    body = fake.json_bodies[-1]
    assert body["cross_session_search"] is True
    assert body["approval_mode"] == "ask_every_time"
    assert accepted.handle.normalized_status == "queued"


def test_async_edit_accepted_with_review_mode():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess-edit", "Add a competency row", document_id="doc_1")
    body = fake.json_bodies[-1]
    assert body["approval_mode"] == "ask_every_time"
    assert body["async_mode"] is True
    assert handle.job_id
    assert handle.normalized_status == "queued"


def test_queued_processing_awaiting_approval():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess-edit", "Edit the profile")
    snapshot = client.wait_for_job(
        handle.job_id,
        poll_interval_seconds=0,
        max_wait_seconds=10,
        sleep=lambda _: None,
        clock=lambda: 0.0,
    )
    assert snapshot.status == "awaiting_approval"
    assert snapshot.pending_changes[0].change_id == "ch_1"
    assert snapshot.pending_changes[0].before == "<p>before</p>"


def test_queued_processing_completed():
    fake = FakeSuperDocsAPI()
    fake.default_sequence = [
        _job("x", "s", "pending"),
        _job("x", "s", "in_progress", progress=50),
        _job("x", "s", "completed", progress=100),
    ]
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess-edit", "Summarize")
    snapshot = client.wait_for_job(
        handle.job_id,
        poll_interval_seconds=0,
        max_wait_seconds=10,
        sleep=lambda _: None,
        clock=lambda: 0.0,
    )
    assert snapshot.status == "completed"


def test_failed_job():
    fake = FakeSuperDocsAPI()
    fake.default_sequence = [
        _job("x", "s", "pending"),
        _job("x", "s", "failed", error="model backend unavailable"),
    ]
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess-edit", "Edit")
    with pytest.raises(JobFailedError, match="unavailable"):
        client.wait_for_job(
            handle.job_id,
            poll_interval_seconds=0,
            max_wait_seconds=10,
            sleep=lambda _: None,
            clock=lambda: 0.0,
        )


def test_polling_timeout_is_not_job_failure():
    fake = FakeSuperDocsAPI()
    fake.default_sequence = [
        _job("x", "s", "pending"),
        _job("x", "s", "in_progress", progress=10),
    ]
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess-edit", "Slow edit")
    ticks = {"now": 0.0}

    def clock() -> float:
        return ticks["now"]

    def sleep(seconds: float) -> None:
        ticks["now"] += seconds

    with pytest.raises(JobTimeoutError, match="still processing"):
        client.wait_for_job(
            handle.job_id,
            poll_interval_seconds=1,
            max_wait_seconds=2,
            stop_on_review=True,
            sleep=sleep,
            clock=clock,
        )


def test_malformed_job_response():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess-edit", "Edit")
    fake.job_sequences[handle.job_id] = ["not-an-object"]
    with pytest.raises(MalformedResponseError):
        client.get_job(handle.job_id)


def test_malformed_pending_changes_on_review_job():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess-edit", "Edit")
    fake.job_sequences[handle.job_id] = [
        _job(handle.job_id, "sess-edit", "awaiting_approval", pending_changes=None)
    ]
    fake.job_sequences[handle.job_id][0]["metadata"] = {"pending_changes": "{not-json"}
    with pytest.raises(ProposedChangeParseError):
        client.get_job(handle.job_id)


def test_auth_errors_and_secret_redaction():
    fake = FakeSuperDocsAPI()
    fake.status_overrides[("GET", "/v1/documents")] = 401
    client = make_client(fake)
    with pytest.raises(AuthenticationError) as captured:
        client.list_saved_documents()
    assert OFFLINE_API_KEY not in str(captured.value)
    assert OFFLINE_API_KEY not in repr(captured.value)
    assert captured.value.cause is None or OFFLINE_API_KEY not in captured.value.cause

    fake.status_overrides[("GET", "/v1/documents")] = 403
    with pytest.raises(AuthenticationError):
        client.list_saved_documents()


def test_rate_limit():
    fake = FakeSuperDocsAPI()
    fake.status_overrides[("GET", "/v1/templates")] = 429
    fake.get_failures_remaining = 0
    client = make_client(fake)
    # GET 429 is retried then raised.
    with pytest.raises(RateLimitError) as captured:
        client.list_templates()
    assert captured.value.retry_after_seconds == 2.0


def test_server_error_on_get_then_success():
    fake = FakeSuperDocsAPI()
    fake.get_failures_remaining = 1
    client = make_client(fake)
    listed = client.list_templates()
    assert listed == ()


def test_server_error_exhausted():
    fake = FakeSuperDocsAPI()
    fake.get_failures_remaining = 5
    client = make_client(fake)
    with pytest.raises(TransientHttpError):
        client.list_templates()


def test_network_timeout_on_get():
    fake = FakeSuperDocsAPI()
    fake.get_timeouts_remaining = 5
    client = make_client(fake)
    with pytest.raises(TransientHttpError):
        client.list_templates()


def test_ambiguous_state_changing_timeout_does_not_retry():
    fake = FakeSuperDocsAPI()
    fake.mutating_timeout = True
    client = make_client(fake)
    with pytest.raises(AmbiguousOutcomeError):
        client.upload_document("a.md", b"# A", session_id="sess")
    mutating = [item for item in fake.calls if item[0] != "GET"]
    assert len(mutating) == 1


def test_safe_get_retry_does_not_retry_mutating_5xx():
    fake = FakeSuperDocsAPI()
    fake.status_overrides[("POST", "/v1/chat/async")] = 503
    client = make_client(fake)
    with pytest.raises(TransientHttpError):
        client.start_reviewed_edit("sess", "Edit")
    posts = [item for item in fake.calls if item == ("POST", "/v1/chat/async")]
    assert len(posts) == 1


def test_operation_key_returns_completed_result_without_second_call():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    first = client.upload_template("t.md", b"# T", operation_key="tpl-1")
    second = client.upload_template("t.md", b"# T", operation_key="tpl-1")
    assert first.template_id == second.template_id
    uploads = [item for item in fake.calls if item[1] == "/v1/templates/upload-base64"]
    assert len(uploads) == 1


def test_approve_reject_and_mixed_decisions():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    approved = client.submit_review(
        "sess",
        "job_1",
        [ReviewDecision(change_id="ch_1", approved=True)],
    )
    assert approved.decided[0].approved is True
    assert fake.json_bodies[-1]["approved"] is True
    assert fake.json_bodies[-1]["change_id"] == "ch_1"

    rejected = client.submit_review(
        "sess",
        "job_1",
        [ReviewDecision(change_id="ch_1", approved=False, feedback="Keep original")],
    )
    assert rejected.decided[0].approved is False
    assert fake.json_bodies[-1]["approved"] is False

    mixed = client.submit_review(
        "sess",
        "job_1",
        [
            ReviewDecision(change_id="ch_1", approved=True),
            ReviewDecision(change_id="ch_2", approved=False),
        ],
    )
    body = fake.json_bodies[-1]
    assert body["approved"] is False
    assert body["changes"][0]["approved"] is True
    assert body["changes"][1]["approved"] is False
    assert mixed.all_approved is False


def test_failed_approval():
    fake = FakeSuperDocsAPI()
    fake.approve_status = 409
    client = make_client(fake)
    with pytest.raises(ApprovalError):
        client.submit_review("sess", "job_1", [ReviewDecision("ch_1", True)])


def test_export_success(tmp_path: Path):
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    dest = tmp_path / "out.docx"
    html = "<h1>Job architecture</h1><h2>Purpose</h2><p>Approved.</p>"
    result = client.export_document(
        dest,
        ExportRequest(session_id="sess", html=html, format="docx", filename="out.docx"),
    )
    assert result.byte_count == len(fake.export_bytes)
    assert dest.read_bytes() == fake.export_bytes
    body = fake.json_bodies[-1]
    assert body["session_id"] == "sess"
    assert body["html"] == html
    assert body["format"] == "docx"
    assert "document_id" not in body
    assert "durable_document_id" not in body


def test_export_stream_to_buffer():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    buffer = io.BytesIO()
    result = client.export_document(
        buffer,
        ExportRequest(session_id="sess", html="<h1>Profile</h1><p>Exact content.</p>"),
    )
    assert result.byte_count > 0
    assert buffer.getvalue() == fake.export_bytes


def test_export_failure():
    fake = FakeSuperDocsAPI()
    fake.status_overrides[("POST", "/v1/documents/export")] = 500
    client = make_client(fake)
    with pytest.raises(ExportError):
        client.export_document(
            io.BytesIO(),
            ExportRequest(session_id="sess", html="<p>content</p>"),
        )


def test_export_no_false_success_on_empty_or_json():
    fake = FakeSuperDocsAPI()
    fake.export_empty = True
    client = make_client(fake)
    with pytest.raises(ExportError, match="no bytes"):
        client.export_document(
            io.BytesIO(),
            ExportRequest(session_id="sess", html="<p>content</p>"),
        )

    fake.export_empty = False
    fake.export_as_json = True
    with pytest.raises(ExportError, match="JSON"):
        client.export_document(
            io.BytesIO(),
            ExportRequest(session_id="sess", html="<p>content</p>"),
        )


def test_session_export_refuses_empty_html():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    with pytest.raises(ExportError, match="Export HTML is empty"):
        ExportRequest(session_id="sess", html="")
    assert fake.json_bodies == []
    assert ("POST", "/v1/documents/export") not in fake.calls


def test_client_repr_hides_key():
    client = make_client(FakeSuperDocsAPI())
    assert OFFLINE_API_KEY not in repr(client)
    assert "Bearer" not in repr(client)


def test_double_encoded_pending_changes_through_client():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess", "Edit")
    fake.job_sequences[handle.job_id] = [
        _job(
            handle.job_id,
            "sess",
            "awaiting_approval",
            pending_changes=[SAMPLE_CHANGE],
            pending_as_string=True,
        )
    ]
    snapshot = client.get_job(handle.job_id)
    assert snapshot.pending_changes[0].change_id == "ch_1"


def test_open_saved_documents_keeps_explicit_ids():
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    roster = client.open_saved_documents("sess-open", ["durable-a", "durable-b"])
    assert roster.document("slot-durable-a").durable_document_id == "durable-a"
    assert roster.document("slot-durable-b").durable_document_id == "durable-b"


def test_continue_large_edit_is_explicit():
    fake = FakeSuperDocsAPI()
    fake.default_sequence = [
        _job("x", "s", "awaiting_approval", awaiting_kind="continue_prompt"),
    ]
    client = make_client(fake)
    handle = client.start_reviewed_edit("sess", "Rewrite the whole framework")
    snapshot = client.get_job(handle.job_id)
    assert snapshot.awaiting_kind == "continue_prompt"
    assert snapshot.pending_changes == ()
    client.continue_large_edit("sess", handle.job_id, resume=True)
    body = fake.json_bodies[-1]
    assert body["continue"] is True
    assert body["job_id"] == handle.job_id
