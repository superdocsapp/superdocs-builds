"""Tests for the SuperDocs client wrapper — specifically the documented
JSON-string-in-JSON gotcha, using a mocked response so no live key or
network call is required."""

import json
from unittest.mock import patch, MagicMock

import pytest
from techpack.superdocs_client import send_edit, SuperDocsError


def _mock_response(status_code=200, json_body=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_body or {}
    mock.text = json.dumps(json_body or {})
    return mock


@patch.dict("os.environ", {"SUPERDOCS_API_KEY": "sk_test_fake_key"})
@patch("techpack.superdocs_client.requests.post")
def test_send_edit_parses_json_encoded_string_field(mock_post):
    # Simulates the documented gotcha: old_html/new_html arriving as a
    # JSON-encoded string that needs a second parse
    nested_as_string = json.dumps({"text": "some nested content"})

    mock_post.return_value = _mock_response(200, {
        "response": "ok",
        "session_id": "test",
        "document_changes": {
            "changes": [
                {"old_html": nested_as_string, "new_html": "<p>plain html, not json</p>"}
            ]
        },
    })

    result = send_edit(session_id="test", message="do something")
    parsed_old = result["document_changes"]["changes"][0]["old_html"]

    # It should have been auto-parsed from a string into a real dict
    assert isinstance(parsed_old, dict)
    assert parsed_old["text"] == "some nested content"


@patch.dict("os.environ", {"SUPERDOCS_API_KEY": "sk_test_fake_key"})
@patch("techpack.superdocs_client.requests.post")
def test_send_edit_leaves_plain_html_untouched(mock_post):
    # Plain HTML starting with '<' should never be mistakenly parsed as JSON
    mock_post.return_value = _mock_response(200, {
        "response": "ok",
        "session_id": "test",
        "document_changes": {
            "changes": [{"old_html": "<p>Hello</p>", "new_html": "<p>Hi</p>"}]
        },
    })

    result = send_edit(session_id="test", message="do something")
    assert result["document_changes"]["changes"][0]["old_html"] == "<p>Hello</p>"


@patch.dict("os.environ", {"SUPERDOCS_API_KEY": "sk_test_fake_key"})
@patch("techpack.superdocs_client.requests.post")
def test_send_edit_handles_null_document_changes(mock_post):
    # Real behavior observed during development: a repeated, already-satisfied
    # instruction returns document_changes: null rather than an error
    mock_post.return_value = _mock_response(200, {
        "response": "already done",
        "session_id": "test",
        "document_changes": None,
    })

    result = send_edit(session_id="test", message="do something")
    assert result["document_changes"] is None  # send_edit itself doesn't need to fix this — callers (get_updated_html) do


def test_send_edit_raises_without_api_key():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SuperDocsError, match="SUPERDOCS_API_KEY"):
            send_edit(session_id="test", message="anything")


@patch.dict("os.environ", {"SUPERDOCS_API_KEY": "sk_test_fake_key"})
@patch("techpack.superdocs_client.requests.post")
def test_send_edit_raises_on_error_status(mock_post):
    mock_post.return_value = _mock_response(500, {"detail": "server error"})

    with pytest.raises(SuperDocsError, match="500"):
        send_edit(session_id="test", message="anything")