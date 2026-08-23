"""Tests for rfe_response_builder/versioning.py."""
import time

import pytest
import requests_mock
from sqlalchemy import create_engine

from rfe_response_builder.superdocs_client import SuperDocsClient, SuperDocsError
from rfe_response_builder.versioning import VersionStore, diff_versions, redraft_item


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'versions.sqlite3'}", connect_args={"check_same_thread": False})


@pytest.fixture
def client():
    return SuperDocsClient(api_key="sk_test_fake_key_not_real", retry_backoff_s=0)


# --- diff_versions -------------------------------------------------------------

def test_diff_versions_returns_empty_list_for_identical_text():
    assert diff_versions("Same text.", "Same text.") == []


def test_diff_versions_shows_line_level_changes():
    old = "Line one.\nLine two.\nLine three."
    new = "Line one.\nLine two revised.\nLine three."
    diff = diff_versions(old, new)
    assert any(line == "-Line two." for line in diff)
    assert any(line == "+Line two revised." for line in diff)


def test_diff_versions_handles_multiline_additions():
    old = "A single line."
    new = "A single line.\nA whole new paragraph was added here."
    diff = diff_versions(old, new)
    assert any(line.startswith("+A whole new paragraph") for line in diff)


# --- VersionStore ----------------------------------------------------------------

def test_record_first_version_returns_version_number_1(engine):
    store = VersionStore(engine)
    version_number = store.record("review-1", "1", "First draft text.")
    assert version_number == 1


def test_record_second_version_increments(engine):
    store = VersionStore(engine)
    store.record("review-1", "1", "First draft text.")
    version_number = store.record("review-1", "1", "Second draft text.", feedback="Make it more specific.")
    assert version_number == 2


def test_list_versions_returns_all_in_order(engine):
    store = VersionStore(engine)
    store.record("review-1", "1", "v1 text")
    store.record("review-1", "1", "v2 text", feedback="fb1")
    store.record("review-1", "1", "v3 text", feedback="fb2")
    versions = store.list_versions("review-1", "1")
    assert [v.reply_text for v in versions] == ["v1 text", "v2 text", "v3 text"]
    assert versions[0].feedback is None
    assert versions[1].feedback == "fb1"


def test_list_versions_is_scoped_per_request_id(engine):
    store = VersionStore(engine)
    store.record("review-1", "1", "item 1 text")
    store.record("review-1", "2", "item 2 text")
    assert len(store.list_versions("review-1", "1")) == 1
    assert len(store.list_versions("review-1", "2")) == 1


def test_list_versions_is_scoped_per_review_id(engine):
    store = VersionStore(engine)
    store.record("review-1", "1", "review 1 text")
    store.record("review-2", "1", "review 2 text")
    assert len(store.list_versions("review-1", "1")) == 1
    assert store.list_versions("review-1", "1")[0].reply_text == "review 1 text"


def test_latest_version_returns_none_when_no_versions_recorded(engine):
    store = VersionStore(engine)
    assert store.latest_version("review-1", "1") is None


def test_latest_version_returns_most_recent(engine):
    store = VersionStore(engine)
    store.record("review-1", "1", "v1 text")
    store.record("review-1", "1", "v2 text")
    latest = store.latest_version("review-1", "1")
    assert latest.reply_text == "v2 text"
    assert latest.version_number == 2


def test_expired_versions_are_pruned_on_next_record(engine):
    store = VersionStore(engine, ttl_s=0)
    store.record("review-1", "1", "old version")
    time.sleep(0.01)
    # A second record() call triggers pruning; the first version is
    # already past its (zero) TTL.
    store.record("review-2", "1", "new version")
    assert store.list_versions("review-1", "1") == []
    assert len(store.list_versions("review-2", "1")) == 1


def test_versions_within_ttl_are_not_pruned(engine):
    store = VersionStore(engine, ttl_s=3600)
    store.record("review-1", "1", "v1 text")
    store.record("review-1", "1", "v2 text")
    assert len(store.list_versions("review-1", "1")) == 2


# --- redraft_item ------------------------------------------------------------

def test_redraft_item_returns_revised_text_and_pending_status(client):
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat/async", json={"job_id": "job-redraft-1"})
        m.get(
            "https://api.superdocs.app/v1/jobs/job-redraft-1",
            json={"status": "awaiting_approval",
                  "pending_changes": [{"chunk_id": "chunk-2", "proposed_text": "Revised section text."}]},
        )
        reply_text, status, chunk_id = redraft_item(
            client, "session-1", "1", "Response to Item 1", "Be more specific about the timeline.",
        )
    assert reply_text == "Revised section text."
    assert status == "pending_review"
    assert chunk_id == "chunk-2"


def test_redraft_item_sends_feedback_in_the_instruction(client):
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat/async", json={"job_id": "job-redraft-1"})
        m.get(
            "https://api.superdocs.app/v1/jobs/job-redraft-1",
            json={"status": "awaiting_approval",
                  "pending_changes": [{"chunk_id": "chunk-2", "proposed_text": "Revised."}]},
        )
        redraft_item(client, "session-1", "1", "Response to Item 1", "Be more specific about the timeline.")
        sent_body = m.request_history[0].json()
    assert "Be more specific about the timeline." in sent_body["message"]
    assert sent_body["session_id"] == "session-1"  # same session as drafting, unlike judge.py's grading


def test_redraft_item_raises_on_persistent_failure(client):
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat/async", status_code=500, json={"detail": "down"})
        with pytest.raises(SuperDocsError):
            redraft_item(client, "session-1", "1", "Response to Item 1", "feedback text")
