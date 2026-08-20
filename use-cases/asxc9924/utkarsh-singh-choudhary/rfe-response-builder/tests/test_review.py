"""
Mocked tests for rfe_response_builder/review.py -- proves the human
approval gate actually controls what counts as answered and what reaches
the exported document, without any network access.
"""
import json
from pathlib import Path

import pytest
import requests_mock

from rfe_response_builder.generate import load_new_evidence_catalog, load_petition
from rfe_response_builder.review import finalize_review, start_review
from rfe_response_builder.superdocs_client import SuperDocsClient

DATA_DIR = Path(__file__).parent.parent / "data"
NOTICE_TEXT = (DATA_DIR / "sample_rfe_notice.txt").read_text()


@pytest.fixture
def client():
    return SuperDocsClient(api_key="sk_test_fake_key_not_real", retry_backoff_s=0)


@pytest.fixture
def petition():
    return load_petition(DATA_DIR / "sample_petition_arguments.json")


@pytest.fixture
def evidence_catalog():
    return load_new_evidence_catalog(DATA_DIR / "sample_new_evidence.json")


def _mock_pending_review(m, job_id="job-1", chunk_id="chunk-1", proposed_text=None, session_id=None):
    proposed_text = proposed_text or "Drafted response section addressing the officer's specific concern with citations."
    m.post("https://api.superdocs.app/v1/chat", json={"response": "ok", "document_changes": {}})
    m.post("https://api.superdocs.app/v1/chat/async", json={"job_id": job_id})
    m.get(
        f"https://api.superdocs.app/v1/jobs/{job_id}",
        json={
            "status": "awaiting_approval",
            "pending_changes": [{"chunk_id": chunk_id, "proposed_text": proposed_text}],
        },
    )
    import re as _re
    m.post(_re.compile(r"https://api\.superdocs\.app/v1/chat/.+/approve"), json={"status": "ok"})
    m.post("https://api.superdocs.app/v1/documents/export", content=b"FAKE_DOCX")


def test_start_review_returns_pending_items(client, petition, evidence_catalog):
    with requests_mock.Mocker() as m:
        _mock_pending_review(m)
        session = start_review(client, "sess-1", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)

    assert len(session.items) == 3
    assert all(item.status == "pending_review" for item in session.items)
    assert all(item.job_id == "chunk-1" for item in session.items)
    assert session.items[0].response_section == "Response to Item 1"


def test_finalize_review_approves_only_selected_items(client, petition, evidence_catalog, tmp_path):
    with requests_mock.Mocker() as m:
        _mock_pending_review(m)
        session = start_review(client, "sess-2", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)

        decisions = {
            session.items[0].request_id: {"approve": True},
            session.items[1].request_id: {"approve": False, "feedback": "needs more detail"},
            # item 3 intentionally omitted -- silence must mean rejected
        }
        out_path, coverage = finalize_review(client, session, decisions, tmp_path)

    answered = {row.request_id: row.answered for row in coverage}
    assert answered[session.items[0].request_id] is True
    assert answered[session.items[1].request_id] is False
    assert answered[session.items[2].request_id] is False
    assert out_path.exists()

    approve_posts = [r for r in m.request_history if r.url.endswith("/approve")]
    assert len(approve_posts) == 3
    bodies = [json.loads(r.text) for r in approve_posts]
    approved_flags = {b["chunk_id"]: b["approved"] for b in bodies}
    assert approved_flags["chunk-1"] in (True, False)  # sanity: field present


def test_finalize_review_response_section_only_set_when_answered(client, petition, evidence_catalog, tmp_path):
    with requests_mock.Mocker() as m:
        _mock_pending_review(m)
        session = start_review(client, "sess-3", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)
        decisions = {item.request_id: {"approve": False} for item in session.items}
        _, coverage = finalize_review(client, session, decisions, tmp_path)

    assert all(row.response_section == "(not answered)" for row in coverage)
    assert all(not row.answered for row in coverage)


def test_no_pending_change_still_requires_substantive_text(client, petition, evidence_catalog, tmp_path):
    """If SuperDocs answers synchronously (status=completed, nothing
    pending), approval alone isn't enough -- the reply still has to pass
    is_substantive_reply, same bar as the non-review flow."""
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat", json={"response": "ok", "document_changes": {}})
        m.post("https://api.superdocs.app/v1/chat/async", json={"job_id": "job-x"})
        m.get(
            "https://api.superdocs.app/v1/jobs/job-x",
            json={"status": "completed", "response": "I don't have enough information to address this."},
        )
        m.post("https://api.superdocs.app/v1/documents/export", content=b"FAKE_DOCX")

        session = start_review(client, "sess-4", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)
        assert all(item.status == "no_pending_change" for item in session.items)

        decisions = {item.request_id: {"approve": True} for item in session.items}
        _, coverage = finalize_review(client, session, decisions, tmp_path)

    assert all(not row.answered for row in coverage)
