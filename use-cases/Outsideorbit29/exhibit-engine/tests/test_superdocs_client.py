"""The SuperDocs client speaks the real HTTP contract — verified against the
bundled mock server (same endpoints, no key required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exhibit.flow import build_message, PROPOSAL_OPEN, PROPOSAL_CLOSE
from exhibit.mock_server import start_server
from exhibit.superdocs import SuperDocsClient, SuperDocsError, encode_file

SAMPLE_BRIEF = str(Path(__file__).resolve().parents[1] / "sample" / "brief" / "supporting_brief.md")


@pytest.fixture(scope="module")
def mock():
    base, stop, state = start_server()
    yield SuperDocsClient(base_url=base, api_key="sk_mock"), state
    stop.set()


def _proposal_payload(exhibits=2):
    return {
        "exhibits": [
            {"number": i + 1, "title": f"Exhibit {i + 1}", "proves": "Evidences a fact.",
             "page_range": "p. 3", "content": "content"}
            for i in range(exhibits)
        ],
        "citations": [
            {"exhibit_number": i + 1, "sentence": f"See Exhibit {i + 1}.",
             "anchor": "anchor sentence one", "rationale": "relies on it"}
            for i in range(exhibits)
        ],
        "index_pages": 1,
    }


def _message(exhibits=2):
    payload = json.dumps(_proposal_payload(exhibits))
    return f"Please apply these changes. {PROPOSAL_OPEN}{payload}{PROPOSAL_CLOSE}"


def test_upload_creates_session(mock):
    client, state = mock
    result = client.upload_base64("brief.html", encode_file(SAMPLE_BRIEF))
    assert result.session_id
    assert result.session_id in state.sessions


def test_chat_async_returns_job_and_pending_changes(mock):
    client, state = mock
    sid = client.upload_base64("brief.html", encode_file(SAMPLE_BRIEF)).session_id
    resp = client.chat_async(_message(exhibits=2), session_id=sid,
                             approval_mode="ask_every_time", response_mode="compact")
    assert resp["job_id"]
    job = client.poll_job(resp["job_id"])
    assert job.status == "awaiting_approval"
    # 2 citations + 2 covers + 1 index = 5 pending changes
    assert len(job.pending_changes) == 5


def test_approve_individual_changes_then_complete(mock):
    client, _state = mock
    sid = client.upload_base64("brief.html", encode_file(SAMPLE_BRIEF)).session_id
    job_id = client.chat_async(_message(exhibits=1), session_id=sid)["job_id"]
    job = client.poll_job(job_id)
    for change in job.pending_changes:
        client.approve(sid, job_id, approved=True, change_id=change["change_id"])
    done = client.poll_job(job_id)
    assert done.status == "completed"
    assert done.result


def test_approve_rejects_a_change_and_it_does_not_apply(mock):
    client, state = mock
    sid = client.upload_base64("brief.html", encode_file(SAMPLE_BRIEF)).session_id
    job_id = client.chat_async(_message(exhibits=1), session_id=sid)["job_id"]
    job = client.poll_job(job_id)
    first = job.pending_changes[0]
    client.approve(sid, job_id, approved=False, change_id=first["change_id"],
                   feedback="reject in test")
    for change in job.pending_changes[1:]:
        client.approve(sid, job_id, approved=True, change_id=change["change_id"])
    done = client.poll_job(job_id)
    assert done.status == "completed"


def test_export_returns_bytes_and_filename(mock):
    client, state = mock
    sid = client.upload_base64("brief.html", encode_file(SAMPLE_BRIEF)).session_id
    result = client.export(sid, fmt="html")
    assert result.content
    assert "text/html" in result.content_type
    assert result.filename and result.filename.endswith(".html")


def test_unknown_session_raises(mock):
    client, _state = mock
    with pytest.raises(SuperDocsError):
        client.chat_async(_message(), session_id="does-not-exist")


def test_upload_with_reused_session_keeps_document(mock):
    client, state = mock
    first = client.upload_base64("one.md", encode_file(SAMPLE_BRIEF))
    second = client.upload_base64("two.md", encode_file(SAMPLE_BRIEF),
                                  session_id=first.session_id)
    assert second.session_id == first.session_id
