from unittest.mock import Mock, patch

import requests

from src.superdocs_client import (
    SuperDocsAPIError,
    SuperDocsClient,
)


def make_client():
    return SuperDocsClient(
        api_key="test-key",
        base_url="https://api.superdocs.test",
        timeout=10,
    )


@patch("src.superdocs_client.requests.post")
def test_edit_sends_expected_request(mock_post):
    response = Mock()
    response.ok = True
    response.json.return_value = {
        "html": "<article><p>Edited</p></article>"
    }

    mock_post.return_value = response

    client = make_client()

    result = client.edit(
        "<article><p>Hello</p></article>",
        "Improve formatting",
    )

    assert result.html == "<article><p>Edited</p></article>"

    mock_post.assert_called_once_with(
        "https://api.superdocs.test/v1/documents",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "html": "<article><p>Hello</p></article>",
            "instruction": "Improve formatting",
        },
        timeout=10,
    )


@patch("src.superdocs_client.requests.post")
def test_edit_rejects_http_error(mock_post):
    response = Mock()
    response.ok = False
    response.status_code = 500
    response.text = "Internal Server Error"

    mock_post.return_value = response

    client = make_client()

    try:
        client.edit("<p>Hello</p>", "Edit")
        assert False, "Expected SuperDocsAPIError"
    except SuperDocsAPIError as exc:
        assert "HTTP 500" in str(exc)


@patch("src.superdocs_client.requests.post")
def test_edit_rejects_network_error(mock_post):
    mock_post.side_effect = requests.RequestException(
        "Connection failed"
    )

    client = make_client()

    try:
        client.edit("<p>Hello</p>", "Edit")
        assert False, "Expected SuperDocsAPIError"
    except SuperDocsAPIError as exc:
        assert "request failed" in str(exc)


@patch("src.superdocs_client.requests.post")
def test_edit_rejects_invalid_json(mock_post):
    response = Mock()
    response.ok = True
    response.json.side_effect = ValueError("invalid json")

    mock_post.return_value = response

    client = make_client()

    try:
        client.edit("<p>Hello</p>", "Edit")
        assert False, "Expected SuperDocsAPIError"
    except SuperDocsAPIError as exc:
        assert "invalid JSON" in str(exc)


@patch("src.superdocs_client.requests.post")
def test_edit_rejects_missing_html(mock_post):
    response = Mock()
    response.ok = True
    response.json.return_value = {
        "message": "Success"
    }

    mock_post.return_value = response

    client = make_client()

    try:
        client.edit("<p>Hello</p>", "Edit")
        assert False, "Expected SuperDocsAPIError"
    except SuperDocsAPIError as exc:
        assert "edited HTML" in str(exc)
