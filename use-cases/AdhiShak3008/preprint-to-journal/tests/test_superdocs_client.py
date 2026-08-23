"""
test_superdocs_client.py
Tests for the SuperDocs API client.
All HTTP calls are mocked — no live API key required.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
import superdocs_client as sd


def _mock_response(status_code=200, json_data=None, content=b""):
    mock = MagicMock()
    mock.status_code = status_code
    mock.ok = status_code < 400
    mock.json.return_value = json_data or {}
    mock.content = content
    mock.text = json.dumps(json_data) if json_data else ""
    return mock


class TestUploadDocument:
    def test_upload_returns_html(self):
        mock_resp = _mock_response(200, {
            "html": "<h1>Test</h1>",
            "chunks_count": 5,
            "version_id": "v1",
            "filename": "test.docx",
        })
        with patch("requests.post", return_value=mock_resp):
            result = sd.upload_document(b"fake bytes", "test.docx", "session-1")
        assert result["html"] == "<h1>Test</h1>"
        assert result["chunks_count"] == 5

    def test_upload_raises_on_401(self):
        mock_resp = _mock_response(401, {"detail": "Invalid API key"})
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(sd.SuperDocsError, match="Invalid or missing API key"):
                sd.upload_document(b"fake", "test.docx", "session-1")

    def test_upload_raises_on_429(self):
        mock_resp = _mock_response(429, {"detail": "Quota exhausted"})
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(sd.SuperDocsRateLimitError):
                sd.upload_document(b"fake", "test.docx", "session-1")

    def test_upload_raises_on_500(self):
        mock_resp = _mock_response(500, {"detail": "Internal error"})
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(sd.SuperDocsError, match="500"):
                sd.upload_document(b"fake", "test.docx", "session-1")


class TestStartTransformation:
    def test_returns_job_id(self):
        mock_resp = _mock_response(200, {"job_id": "job-abc-123"})
        with patch("requests.post", return_value=mock_resp):
            job_id = sd.start_transformation("session-1", "<h1>Doc</h1>", "Transform this")
        assert job_id == "job-abc-123"

    def test_sends_approval_mode(self):
        mock_resp = _mock_response(200, {"job_id": "job-xyz"})
        with patch("requests.post", return_value=mock_resp) as mock_post:
            sd.start_transformation("session-1", "<h1>Doc</h1>", "Transform")
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert payload.get("approval_mode") == "ask_every_time"

    def test_sends_document_html(self):
        mock_resp = _mock_response(200, {"job_id": "job-xyz"})
        with patch("requests.post", return_value=mock_resp) as mock_post:
            sd.start_transformation("session-1", "<h1>Original</h1>", "Transform")
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["document_html"] == "<h1>Original</h1>"


class TestPollJob:
    def test_poll_in_progress(self):
        mock_resp = _mock_response(200, {"status": "in_progress", "metadata": {}})
        with patch("requests.get", return_value=mock_resp):
            state = sd.poll_job("job-1")
        assert state["status"] == "in_progress"
        assert state["pending_changes"] == []

    def test_poll_completed_returns_result(self):
        mock_resp = _mock_response(200, {
            "status": "completed",
            "result": {
                "response": "Done",
                "document_changes": {"updated_html": "<h1>Transformed</h1>"},
            },
            "metadata": {},
        })
        with patch("requests.get", return_value=mock_resp):
            state = sd.poll_job("job-1")
        assert state["status"] == "completed"
        assert state["result"]["document_changes"]["updated_html"] == "<h1>Transformed</h1>"

    def test_poll_awaiting_approval_returns_changes(self):
        raw_changes = [
            {
                "change_id": "ch-1",
                "chunk_id": "c1",
                "operation": "update",
                "old_html": "<p>Old</p>",
                "new_html": "<p>New</p>",
                "ai_explanation": "Updated section",
            }
        ]
        mock_resp = _mock_response(200, {
            "status": "awaiting_approval",
            "metadata": {"pending_changes": raw_changes},
        })
        with patch("requests.get", return_value=mock_resp):
            state = sd.poll_job("job-1")
        assert state["status"] == "awaiting_approval"
        assert len(state["pending_changes"]) == 1
        assert state["pending_changes"][0]["change_id"] == "ch-1"

    def test_poll_failed(self):
        mock_resp = _mock_response(200, {
            "status": "failed",
            "error": "AI processing error",
            "metadata": {},
        })
        with patch("requests.get", return_value=mock_resp):
            state = sd.poll_job("job-1")
        assert state["status"] == "failed"
        assert state["error"] == "AI processing error"


class TestParsePendingChanges:
    def test_parses_normal_change(self):
        raw = [{
            "change_id": "ch-1",
            "chunk_id": "c1",
            "operation": "update",
            "old_html": "<p>Old</p>",
            "new_html": "<p>New</p>",
            "ai_explanation": "Explanation",
        }]
        result = sd._parse_pending_changes(raw)
        assert len(result) == 1
        assert result[0]["change_id"] == "ch-1"
        assert result[0]["old_html"] == "<p>Old</p>"

    def test_parses_double_encoded_content(self):
        """
        SuperDocs may JSON-encode the content field as a string.
        This tests the required double-parse.
        """
        inner = {
            "changes": [{
                "change_id": "ch-2",
                "chunk_id": "c2",
                "operation": "update",
                "old_html": "<p>Before</p>",
                "new_html": "<p>After</p>",
                "ai_explanation": "Double-encoded",
            }]
        }
        # Simulate the double-encoding: content is a JSON string
        raw = [{"content": json.dumps(inner)}]
        result = sd._parse_pending_changes(raw)
        assert len(result) == 1
        assert result[0]["change_id"] == "ch-2"
        assert result[0]["old_html"] == "<p>Before</p>"

    def test_parses_string_encoded_change(self):
        """Change item itself is a JSON string."""
        change = {
            "change_id": "ch-3",
            "chunk_id": "c3",
            "operation": "insert",
            "old_html": "",
            "new_html": "<p>New section</p>",
            "ai_explanation": "Inserted",
        }
        raw = [json.dumps(change)]
        result = sd._parse_pending_changes(raw)
        assert len(result) == 1
        assert result[0]["change_id"] == "ch-3"

    def test_normalise_change_handles_missing_keys(self):
        change = {"id": "ch-4"}  # uses 'id' not 'change_id'
        result = sd._normalise_change(change)
        assert result["change_id"] == "ch-4"
        assert result["old_html"] == ""
        assert result["new_html"] == ""

    def test_empty_changes_list(self):
        result = sd._parse_pending_changes([])
        assert result == []


class TestApproveChanges:
    def test_sends_correct_payload(self):
        mock_resp = _mock_response(200, {"ok": True})
        decisions = [
            {"change_id": "ch-1", "approved": True, "feedback": ""},
            {"change_id": "ch-2", "approved": False, "feedback": "Keep original"},
        ]
        with patch("requests.post", return_value=mock_resp) as mock_post:
            sd.approve_changes("session-1", "job-1", decisions)
        payload = mock_post.call_args[1]["json"]
        assert payload["job_id"] == "job-1"
        assert len(payload["changes"]) == 2
        assert payload["changes"][0]["approved"] is True
        assert payload["changes"][1]["approved"] is False
        assert payload["changes"][1]["feedback"] == "Keep original"

    def test_raises_on_api_error(self):
        mock_resp = _mock_response(400, {"detail": "Bad request"})
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(sd.SuperDocsError):
                sd.approve_changes("session-1", "job-1", [])


class TestExportDocument:
    def test_returns_bytes(self):
        fake_docx = b"PK\x03\x04fake docx bytes"
        mock_resp = _mock_response(200, content=fake_docx)
        mock_resp.ok = True
        with patch("requests.post", return_value=mock_resp):
            result = sd.export_document("session-1", "my-manuscript")
        assert result == fake_docx

    def test_raises_on_error(self):
        mock_resp = _mock_response(400, {"detail": "Session not found"})
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(sd.SuperDocsError):
                sd.export_document("session-1")


class TestGetFinalHtml:
    def test_extracts_html_from_result(self):
        result = {
            "response": "Done",
            "document_changes": {"updated_html": "<h1>Final</h1>"},
        }
        assert sd.get_final_html(result) == "<h1>Final</h1>"

    def test_returns_none_for_no_changes(self):
        result = {"response": "No changes needed"}
        assert sd.get_final_html(result) is None

    def test_returns_none_for_none_input(self):
        assert sd.get_final_html(None) is None


class TestMissingApiKey:
    def test_raises_when_key_not_set(self, monkeypatch):
        monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
        with pytest.raises(sd.SuperDocsError, match="SUPERDOCS_API_KEY"):
            sd._get_api_key()
