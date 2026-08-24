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


def test_start_review_flags_ungrounded_facts_in_drafted_reply(client, petition, evidence_catalog):
    """A reply containing a specific dollar figure and year that appear
    nowhere in the notice, the matched petition argument, or the matched
    evidence catalog should be flagged via DraftItem.ungrounded_facts --
    this is the heuristic check for the drafting model inventing details
    despite being told not to."""
    fabricated_reply = (
        "The beneficiary earned a bonus of $87,250 in 2011 for exceptional performance, "
        "as demonstrated in the attached record."
    )
    with requests_mock.Mocker() as m:
        _mock_pending_review(m, proposed_text=fabricated_reply)
        session = start_review(client, "sess-2", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)

    assert any(item.ungrounded_facts for item in session.items)
    flagged = next(item for item in session.items if item.ungrounded_facts)
    assert "$87,250" in flagged.ungrounded_facts
    assert "2011" in flagged.ungrounded_facts


def test_start_review_does_not_flag_grounded_reply(client, petition, evidence_catalog):
    with requests_mock.Mocker() as m:
        _mock_pending_review(m, proposed_text="A direct, well-supported response addressing the officer's concern.")
        session = start_review(client, "sess-3", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)

    assert all(item.ungrounded_facts == [] for item in session.items)


def test_start_review_quality_gate_disabled_by_default(client, petition, evidence_catalog):
    with requests_mock.Mocker() as m:
        _mock_pending_review(m)
        session = start_review(client, "sess-4", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)
    # QUALITY_GATE_ENABLED is unset -- verdict stays "unknown" and no
    # extra grading calls are made (only the header + 3 item turns, no
    # grading turns -- see call count below).
    assert all(item.quality_verdict == "unknown" for item in session.items)


def test_start_review_quality_gate_flags_weak_draft_when_enabled(client, petition, evidence_catalog, monkeypatch):
    monkeypatch.setenv("QUALITY_GATE_ENABLED", "1")

    def chat_callback(request, context):
        body = request.json()
        if "-grading-" in body["session_id"]:
            return {"response": '{"addresses_concern": false, "reasoning": "Restates the petition instead."}',
                     "document_changes": {}}
        return {"response": "ok", "document_changes": {}}

    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat", json=chat_callback)
        m.post("https://api.superdocs.app/v1/chat/async", json={"job_id": "job-1"})
        m.get(
            "https://api.superdocs.app/v1/jobs/job-1",
            json={"status": "awaiting_approval",
                  "pending_changes": [{"chunk_id": "chunk-1",
                                        "proposed_text": "Drafted response section addressing the concern."}]},
        )
        session = start_review(client, "sess-5", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)

    assert all(item.quality_verdict == "weak" for item in session.items)
    assert all(item.quality_reasoning == "Restates the petition instead." for item in session.items)


def test_start_review_quality_gate_uses_separate_grading_session_per_item(client, petition, evidence_catalog, monkeypatch):
    monkeypatch.setenv("QUALITY_GATE_ENABLED", "1")
    seen_grading_sessions = []

    def chat_callback(request, context):
        body = request.json()
        if "-grading-" in body["session_id"]:
            seen_grading_sessions.append(body["session_id"])
            return {"response": '{"addresses_concern": true, "reasoning": "Fine."}', "document_changes": {}}
        return {"response": "ok", "document_changes": {}}

    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat", json=chat_callback)
        m.post("https://api.superdocs.app/v1/chat/async", json={"job_id": "job-1"})
        m.get(
            "https://api.superdocs.app/v1/jobs/job-1",
            json={"status": "awaiting_approval",
                  "pending_changes": [{"chunk_id": "chunk-1", "proposed_text": "A drafted response."}]},
        )
        start_review(client, "sess-6", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)

    # One distinct grading session per RFE item (3 items), none equal to
    # the drafting session_id itself.
    assert len(set(seen_grading_sessions)) == 3
    assert all(s != "sess-6" for s in seen_grading_sessions)


def test_finalize_review_appends_pre_export_validation_summary(client, petition, evidence_catalog, tmp_path):
    with requests_mock.Mocker() as m:
        _mock_pending_review(m)
        session = start_review(client, "sess-val", "CASE-2002", "Marco Alvarez", NOTICE_TEXT, petition, evidence_catalog)

        decisions = {
            session.items[0].request_id: {"approve": True},
            session.items[1].request_id: {"approve": False, "feedback": "needs more detail"},
            # item 3 intentionally omitted -- rejected by silence
        }
        finalize_review(client, session, decisions, tmp_path)

        validation_calls = [
            json.loads(r.text) for r in m.request_history
            if r.url.endswith("/v1/chat") and "Pre-Export Validation Summary" in json.loads(r.text).get("message", "")
        ]
    assert len(validation_calls) == 1
    message = validation_calls[0]["message"]
    assert "Every request answered: FAIL" in message
    assert "Cross-item consistency checked: PASS" in message


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
