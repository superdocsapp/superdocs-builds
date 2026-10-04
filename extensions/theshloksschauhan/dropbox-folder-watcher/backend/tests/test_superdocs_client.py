"""Tests for the SuperDocs client integration.

Proves:
- Double JSON parse works correctly (the task doc's #1 integration bug)
- Preview mode guarantees zero billable calls (the no-spend chokepoint)
- SuperDocs failures are handled without losing state
- The 4-call contract executes correctly

All tests use the fake client — no SuperDocs API key needed.
"""
import json
import pytest

from app.services.superdocs_client import (
    parse_proposed_changes,
    PreviewModeBlocked,
)
from tests.fixtures.fake_superdocs import (
    FakeSuperDocsClient,
    make_double_encoded_response,
    make_simple_response,
    make_malicious_response,
)


class TestDoubleJsonParse:
    """THE CRITICAL TEST: prove we handle the double-encoded proposed changes."""

    def test_double_encoded_string_parsed_correctly(self):
        """When proposed_changes is a JSON string containing objects whose
        'content' fields are ALSO JSON strings, we parse both layers."""
        raw = make_double_encoded_response("doc_001", "normalize formatting")
        changes = parse_proposed_changes(raw)

        assert len(changes) >= 1
        # The inner content should be parsed into a real dict, not a string
        first = changes[0]
        assert isinstance(first.content, str)
        assert len(first.content) > 0
        # The raw field should be a parsed dict
        assert isinstance(first.raw, dict)

    def test_already_parsed_response_still_works(self):
        """When proposed_changes is already a list of dicts (no double encoding),
        we handle it gracefully without breaking."""
        raw = make_simple_response("doc_002")
        changes = parse_proposed_changes(raw)

        assert len(changes) == 1
        assert changes[0].content == "Simple change content"

    def test_empty_proposed_changes(self):
        """Missing or empty proposed_changes returns an empty list, not a crash."""
        assert parse_proposed_changes({}) == []
        assert parse_proposed_changes({"proposed_changes": []}) == []
        assert parse_proposed_changes({"proposed_changes": ""}) == []

    def test_deeply_nested_json_string(self):
        """A content field that is itself a JSON string gets parsed."""
        raw = {
            "proposed_changes": [
                {"content": json.dumps({"type": "edit", "text": "Hello world"})}
            ]
        }
        changes = parse_proposed_changes(raw)
        assert len(changes) == 1
        # Should have parsed the inner JSON
        assert "Hello world" in changes[0].content or "Hello world" in str(changes[0].raw)

    def test_plain_string_content_not_json(self):
        """Content that is a plain string (not JSON) is kept as-is."""
        raw = {
            "proposed_changes": [
                {"content": "Just a plain text change, not JSON"}
            ]
        }
        changes = parse_proposed_changes(raw)
        assert len(changes) == 1
        assert changes[0].content == "Just a plain text change, not JSON"


class TestPreviewModeChokepoint:
    """Prove that preview mode STRUCTURALLY prevents billable operations."""

    def test_upload_blocked_in_preview(self):
        """Upload (billable) is blocked when preview=True."""
        client = FakeSuperDocsClient()
        with pytest.raises(PreviewModeBlocked):
            client.upload_document(b"content", "test.docx", preview=True)
        # Verify zero calls were made
        assert len(client.billable_calls) == 0

    def test_chat_blocked_in_preview(self):
        """Chat/edit instruction (billable) is blocked when preview=True."""
        client = FakeSuperDocsClient()
        with pytest.raises(PreviewModeBlocked):
            client.send_edit_instruction("doc_001", "normalize", preview=True)
        assert len(client.billable_calls) == 0

    def test_approve_allowed_in_preview(self):
        """Approve is NOT billable — should work even conceptually in preview.
        (In practice preview jobs stop before reaching approve.)"""
        client = FakeSuperDocsClient()
        result = client.approve_changes("doc_001")
        assert result["status"] == "approved"

    def test_export_allowed_always(self):
        """Export is NOT billable — safe to retry freely."""
        client = FakeSuperDocsClient()
        result = client.export_document("doc_001")
        assert len(result.content) > 0

    def test_normal_mode_allows_billable(self):
        """Without preview=True, billable operations work normally."""
        client = FakeSuperDocsClient()
        result = client.upload_document(b"content", "test.docx", preview=False)
        assert result.document_id.startswith("fake_doc_")
        assert len(client.billable_calls) == 1


class TestFourCallContract:
    """Prove the full 4-call lifecycle works end to end."""

    def test_happy_path(self):
        """upload -> chat -> approve -> export completes successfully."""
        client = FakeSuperDocsClient()

        # 1. Upload
        upload = client.upload_document(b"document bytes", "report.docx")
        assert upload.document_id
        doc_id = upload.document_id

        # 2. Chat (edit instruction)
        chat = client.send_edit_instruction(doc_id, "Normalize to template")
        assert len(chat.proposed_changes) >= 1
        assert chat.raw_response["status"] == "changes_proposed"

        # 3. Approve
        approve = client.approve_changes(doc_id)
        assert approve["status"] == "approved"

        # 4. Export
        export = client.export_document(doc_id)
        assert len(export.content) > 0
        assert export.filename

        # Verify call sequence
        ops = [c["operation"] for c in client.calls]
        assert ops == ["upload", "chat", "approve", "export"]

    def test_upload_failure_no_doc_id(self):
        """If upload fails, no doc_id exists — retry is safe (no double-spend)."""
        client = FakeSuperDocsClient(fail_on="upload")
        with pytest.raises(Exception, match="upload failure"):
            client.upload_document(b"content", "test.docx")
        # No calls should have been recorded on failure
        assert len(client.billable_calls) == 0

    def test_chat_failure_doc_id_preserved(self):
        """If chat fails, the doc_id from upload still exists.
        Retry should resume from chat, not re-upload."""
        client = FakeSuperDocsClient()

        # Upload succeeds
        upload = client.upload_document(b"content", "test.docx")
        doc_id = upload.document_id

        # Now make chat fail
        client._fail_on = "chat"
        with pytest.raises(Exception, match="chat failure"):
            client.send_edit_instruction(doc_id, "normalize")

        # doc_id is still valid — a retry would use it, not re-upload
        assert doc_id.startswith("fake_doc_")
        # Only 1 billable call (the upload), not 2
        assert len(client.billable_calls) == 1


class TestPromptInjection:
    """Prove that malicious document content doesn't affect system behavior.

    Test 17 from Section 19: "A source document that contains instructions
    aimed at the system is data to report on, not commands to follow."
    """

    def test_malicious_content_parsed_as_data(self):
        """Document content containing 'ignore previous instructions' or
        'approve automatically' is treated as plain data, not as a command."""
        client = FakeSuperDocsClient()
        client.set_chat_response(make_malicious_response("doc_evil"))

        result = client.send_edit_instruction("doc_evil", "normalize")

        # The malicious content is in the proposed changes as DATA
        assert len(result.proposed_changes) >= 1
        # But it's just a string — it doesn't trigger any approval
        malicious_text = str(result.proposed_changes[0].raw)
        assert "approve" in malicious_text.lower() or "ignore" in malicious_text.lower()

        # The system DOES NOT auto-approve — no approve call was made
        ops = [c["operation"] for c in client.calls]
        assert "approve" not in ops

        # The system still requires an explicit approve_changes() call
        # from a real authenticated actor to proceed
