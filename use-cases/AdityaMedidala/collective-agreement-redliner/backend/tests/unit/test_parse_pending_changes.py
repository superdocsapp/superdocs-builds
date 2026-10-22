"""
The one thing that's fully real in Phase 0: SuperDocsClient.parse_pending_changes.
Everything else is a stub — this function is the one the brief specifically
warns most integrators get wrong (JSON-encoded string inside the JSON
response), so it gets a real test before any other logic exists.
"""

import json

from app.superdocs_client import SuperDocsClient


def test_parses_json_encoded_string_content():
    job_response = {
        "metadata": {
            "pending_changes": [
                {"chunk_id": "abc123", "content": json.dumps({"old": "foo", "new": "bar"})},
            ]
        }
    }
    parsed = SuperDocsClient.parse_pending_changes(job_response)
    assert parsed[0]["content"] == {"old": "foo", "new": "bar"}


def test_leaves_plain_string_content_alone():
    # not every field is guaranteed to be double-encoded — a legitimately
    # plain string must survive untouched, not raise or get mangled
    job_response = {
        "metadata": {"pending_changes": [{"chunk_id": "def456", "content": "just plain text"}]}
    }
    parsed = SuperDocsClient.parse_pending_changes(job_response)
    assert parsed[0]["content"] == "just plain text"


def test_handles_missing_pending_changes():
    assert SuperDocsClient.parse_pending_changes({"metadata": {}}) == []
    assert SuperDocsClient.parse_pending_changes({}) == []


def test_handles_multiple_changes_independently():
    job_response = {
        "metadata": {
            "pending_changes": [
                {"chunk_id": "a", "content": json.dumps({"x": 1})},
                {"chunk_id": "b", "content": "plain"},
                {"chunk_id": "c", "content": json.dumps({"y": 2})},
            ]
        }
    }
    parsed = SuperDocsClient.parse_pending_changes(job_response)
    assert parsed[0]["content"] == {"x": 1}
    assert parsed[1]["content"] == "plain"
    assert parsed[2]["content"] == {"y": 2}
