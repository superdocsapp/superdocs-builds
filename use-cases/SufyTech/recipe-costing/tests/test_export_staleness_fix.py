"""
Proves SuperDocsClient.verify_and_get_final_html() actually fixes the
real export-staleness bug found during a live run: a menu costing sheet
still showing the OLD ingredient price after approve_change() returned
success, because export_document(session_id=...) trusted the server's
session snapshot to already reflect the just-approved edit.

test_verify_and_get_final_html_patches_locally_when_server_is_stale IS
the regression test - it reproduces the exact scenario found live
(server still returns old_html for an approved change) and proves the
fix produces the correct new_html anyway.

All at zero cost, zero network - requests.get/post are faked exactly
like test_superdocs_client_and_orchestration.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from superdocs_client import SuperDocsClient


class FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json_data = json_data or {}
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _history_response(html_content: str) -> FakeResponse:
    return FakeResponse({"document_state": {"html_content": html_content}})


def test_verify_and_get_final_html_leaves_already_landed_changes_untouched():
    """The happy path: the server's history already reflects the
    approved edit - nothing to patch."""
    client = SuperDocsClient(api_key="sk_test")
    current_html = "<p>Olive oil unit cost: $1.35</p>"
    expected_changes = [
        {"chunk_id": "c1", "old_html": "$0.45", "new_html": "$1.35"},
    ]

    with patch("superdocs_client.requests.get", return_value=_history_response(current_html)):
        result = client.verify_and_get_final_html("s1", expected_changes)

    assert result == current_html


def test_verify_and_get_final_html_patches_locally_when_server_is_stale():
    """
    THE REGRESSION TEST: reproduces the exact real bug found live -
    the session's history still has the OLD price even though
    approve_change() already returned success. Proves the fix patches
    it locally rather than exporting the stale value.
    """
    client = SuperDocsClient(api_key="sk_test")
    stale_html = "<p>Olive oil unit cost: $0.45 per oz, used in 3 dishes.</p>"
    expected_changes = [
        {"chunk_id": "c1", "old_html": "$0.45 per oz", "new_html": "$1.35 per oz"},
    ]

    with patch("superdocs_client.requests.get", return_value=_history_response(stale_html)):
        result = client.verify_and_get_final_html("s1", expected_changes)

    assert "$1.35 per oz" in result
    assert "$0.45 per oz" not in result


def test_verify_and_get_final_html_handles_multiple_changes_some_landed_some_not():
    client = SuperDocsClient(api_key="sk_test")
    # First change already landed (new_html present); second is stale
    # (still has old_html) - proves each change is checked independently.
    mixed_html = "<p>Caesar Salad: $1.35/oz.</p><p>Margherita: $0.45/oz.</p>"
    expected_changes = [
        {"chunk_id": "c1", "old_html": "Caesar Salad: $0.45/oz", "new_html": "Caesar Salad: $1.35/oz"},
        {"chunk_id": "c2", "old_html": "Margherita: $0.45/oz", "new_html": "Margherita: $1.35/oz"},
    ]

    with patch("superdocs_client.requests.get", return_value=_history_response(mixed_html)):
        result = client.verify_and_get_final_html("s1", expected_changes)

    assert "Caesar Salad: $1.35/oz" in result
    assert "Margherita: $1.35/oz" in result
    assert "$0.45/oz" not in result


def test_verify_and_get_final_html_raises_loudly_when_neither_old_nor_new_html_found():
    """
    Must NEVER silently export something that might be wrong - if
    neither the expected old text nor the expected new text can be
    found verbatim (e.g. the AI reworded the surrounding HTML too),
    this is genuinely ambiguous and must raise rather than guess.
    """
    client = SuperDocsClient(api_key="sk_test")
    unrelated_html = "<p>Something completely different was written here.</p>"
    expected_changes = [
        {"chunk_id": "c1", "old_html": "$0.45 per oz", "new_html": "$1.35 per oz"},
    ]

    with patch("superdocs_client.requests.get", return_value=_history_response(unrelated_html)):
        with pytest.raises(RuntimeError, match="c1"):
            client.verify_and_get_final_html("s1", expected_changes)


def test_verify_and_get_final_html_skips_changes_with_no_new_html():
    """Defensive: an expected_changes entry with no new_html (shouldn't
    happen in practice, but must not crash) is skipped, not treated as
    an error."""
    client = SuperDocsClient(api_key="sk_test")
    html = "<p>Untouched content.</p>"
    expected_changes = [{"chunk_id": "c1"}]

    with patch("superdocs_client.requests.get", return_value=_history_response(html)):
        result = client.verify_and_get_final_html("s1", expected_changes)

    assert result == html


def test_get_session_history_hits_the_correct_endpoint():
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.get") as mock_get:
        mock_get.return_value = _history_response("<p>hi</p>")
        client.get_session_history("s1")

    call_args = mock_get.call_args
    assert call_args.args[0].endswith("/sessions/s1/history")


def test_export_html_sends_raw_html_not_session_id(tmp_path):
    """
    The other half of the fix: export_html must send the html body
    directly, never a session_id - that's precisely what avoids
    re-trusting the server's own (possibly stale) session snapshot.
    """
    client = SuperDocsClient(api_key="sk_test")
    output_path = tmp_path / "out.docx"
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse(content=b"FAKE-DOCX-BYTES")
        client.export_html("<p>verified content</p>", str(output_path))

    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["json"]["html"] == "<p>verified content</p>"
    assert "session_id" not in call_kwargs["json"]
    assert output_path.read_bytes() == b"FAKE-DOCX-BYTES"
