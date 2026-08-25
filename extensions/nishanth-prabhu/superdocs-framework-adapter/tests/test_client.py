from __future__ import annotations

import json
from unittest.mock import patch
import urllib.error

from superdocs_adapter import SuperDocsClient, ToolName


def test_upload_creates_document_id() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload(
        "Example",
        "# Introduction\nHello SuperDocs.",
    )

    assert document_id.startswith("superdocs-")


def test_search_document() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload(
        "Example",
        "# Introduction\nHello SuperDocs.\nAuthentication is required.",
    )

    result = client.search_document(
        document_id,
        "authentication",
    )

    assert result.success is True
    assert result.tool is ToolName.SEARCH_DOCUMENT
    assert result.data["count"] == 1


def test_search_unknown_document() -> None:
    client = SuperDocsClient(api_key="test-key")

    result = client.search_document(
        "missing-document",
        "authentication",
    )

    assert result.success is False
    assert "Unknown document_id" in result.error


def test_search_empty_query() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload("Example", "Hello.")

    result = client.search_document(document_id, "   ")

    assert result.success is False
    assert "Query cannot be empty" in result.error


def test_export_document() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload(
        "Example",
        "# Introduction\nHello.",
    )

    result = client.export_document(
        document_id,
        "markdown",
    )

    assert result.success is True
    assert result.data["content"] == "# Introduction\nHello."


def test_export_unsupported_format() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload(
        "Example",
        "Hello.",
    )

    result = client.export_document(
        document_id,
        "pdf",
    )

    assert result.success is False
    assert "Unsupported export format" in result.error


def test_export_unknown_document() -> None:
    client = SuperDocsClient(api_key="test-key")

    result = client.export_document("missing-doc", "markdown")

    assert result.success is False
    assert "Unknown document_id" in result.error


def test_edit_document_sends_superdocs_chat_request() -> None:
    client = SuperDocsClient(
        base_url="https://api.superdocs.app/v1",
        api_key="test-key",
    )

    document_id = client.upload(
        "Example",
        "# Introduction\nHello SuperDocs.",
    )

    response_payload = {
        "document_changes": {
            "changes": [
                {
                    "change_id": "change-1",
                    "old_html": "<p>Hello SuperDocs.</p>",
                    "new_html": "<p>Hello SuperDocs API.</p>",
                    "ai_explanation": "Updated the introduction.",
                    "chunk_id": "chunk-1",
                }
            ]
        }
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(response_payload).encode("utf-8")

    with patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(),
    ) as mock_urlopen:
        result = client.edit_document(
            document_id,
            "Update the introduction.",
        )

    assert result.success is True
    assert result.tool is ToolName.EDIT_DOCUMENT

    changes = result.data["changes"]

    assert len(changes) == 1
    assert changes[0]["change_id"] == "change-1"
    assert changes[0]["old_snippet"] == "Hello SuperDocs."
    assert changes[0]["new_snippet"] == "Hello SuperDocs API."

    request = mock_urlopen.call_args.args[0]

    assert request.full_url == (
        "https://api.superdocs.app/v1/chat"
    )

    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer test-key"

    payload = json.loads(request.data.decode("utf-8"))

    assert payload["session_id"] == document_id
    assert payload["document_html"] == (
        "<h1>Introduction</h1>\n"
        "<p>Hello SuperDocs.</p>"
    )
    assert "Update the introduction." in payload["message"]


def test_edit_document_parses_json_response_fallback() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload(
        "Example",
        "# Introduction\nHello.",
    )

    response_payload = {
        "response": (
            "```json\n"
            "["
            "{"
            '"change_id": "change-1", '
            '"target_section": "Introduction", '
            '"old_snippet": "Hello.", '
            '"new_snippet": "Hello SuperDocs.", '
            '"explanation": "Improved wording."'
            "}"
            "]"
            "\n```"
        )
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(response_payload).encode("utf-8")

    with patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(),
    ):
        result = client.edit_document(
            document_id,
            "Improve the greeting.",
        )

    assert result.success is True

    changes = result.data["changes"]

    assert len(changes) == 1
    assert changes[0]["change_id"] == "change-1"


def test_edit_document_unknown_document() -> None:
    client = SuperDocsClient(api_key="test-key")

    result = client.edit_document("missing-doc", "instruction")

    assert result.success is False
    assert "Unknown document_id" in result.error


def test_edit_document_empty_instruction() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload("Example", "Hello.")

    result = client.edit_document(document_id, "   ")

    assert result.success is False
    assert "Instruction cannot be empty" in result.error


def test_edit_document_returns_failure_on_http_error() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload(
        "Example",
        "# Introduction\nHello.",
    )

    error = urllib.error.HTTPError(
        url="https://api.superdocs.app/v1/chat",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=None,
    )

    with patch(
        "urllib.request.urlopen",
        side_effect=error,
    ):
        result = client.edit_document(
            document_id,
            "Update the introduction.",
        )

    assert result.success is False
    assert "SuperDocs HTTP error 500" in result.error


def test_edit_document_returns_failure_on_connection_error() -> None:
    client = SuperDocsClient(api_key="test-key")

    document_id = client.upload(
        "Example",
        "# Introduction\nHello.",
    )

    error = urllib.error.URLError("connection refused")

    with patch(
        "urllib.request.urlopen",
        side_effect=error,
    ):
        result = client.edit_document(
            document_id,
            "Update the introduction.",
        )

    assert result.success is False
    assert "SuperDocs connection error" in result.error
