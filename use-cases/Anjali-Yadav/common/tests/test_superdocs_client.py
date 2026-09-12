import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from superdocs_client import (
    BudgetExceeded,
    OperationBudget,
    SuperDocsClient,
    SuperDocsError,
)


def _mock_response(status_code=200, json_data=None, content=b""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.content = content
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        r.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status_code}")
    return r


class TestDoubleJSONParse:
    """Gotcha #1 from the task doc."""

    def test_document_changes_string_gets_parsed(self):
        client = SuperDocsClient("fake-key")
        raw = json.dumps({"chunk_id": "c1", "old_html": "<p>a</p>", "new_html": "<p>b</p>"})
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(
                200, {"response": "ok", "document_changes": raw, "usage": {}}
            )
            result = client.chat("sess-1", "edit this")
        assert isinstance(result["document_changes"], dict)
        assert result["document_changes"]["chunk_id"] == "c1"

    def test_document_changes_already_object_left_alone(self):
        client = SuperDocsClient("fake-key")
        already_parsed = {"chunk_id": "c1"}
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(
                200, {"response": "ok", "document_changes": already_parsed, "usage": {}}
            )
            result = client.chat("sess-1", "edit this")
        assert result["document_changes"] == already_parsed

    def test_document_changes_none_stays_none(self):
        client = SuperDocsClient("fake-key")
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(200, {"response": "no edits", "usage": {}})
            result = client.chat("sess-1", "just chatting")
        assert result["document_changes"] is None

    def test_malformed_json_string_returned_raw_not_crashed(self):
        client = SuperDocsClient("fake-key")
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(
                200, {"response": "ok", "document_changes": "{not valid json", "usage": {}}
            )
            result = client.chat("sess-1", "edit this")  # must not raise
        assert result["document_changes"] == "{not valid json"

    def test_approval_changes_string_gets_parsed(self):
        client = SuperDocsClient("fake-key")
        changes = {"chunk_id": "c1", "new_html": "<p>b</p>"}
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(
                200,
                {
                    "response": "ok",
                    "document_changes": json.dumps(changes),
                    "approval": {
                        "job_id": "job-1",
                        "changes": json.dumps(changes),
                    },
                    "usage": {},
                },
            )
            result = client.chat("sess-1", "edit this")
        assert result["approval"]["changes"] == changes


class TestHumanReview:
    def test_review_accepts_only_explicit_yes(self):
        from superdocs_client import review_proposed_changes

        assert review_proposed_changes({"change": 1}, lambda _: "yes") is True
        assert review_proposed_changes({"change": 1}, lambda _: "no") is False

    def test_malformed_approval_changes_fail_closed(self):
        from superdocs_client import require_structured_changes

        with pytest.raises(SuperDocsError, match="not valid structured JSON"):
            require_structured_changes("{not-json}")

    def test_review_changes_one_by_one_returns_decision_per_change(self):
        from superdocs_client import review_changes_one_by_one

        changes = [{"change_id": "one", "operation": "edit"}, {"change_id": "two", "operation": "delete"}]
        answers = iter(["y", "n"])
        decisions = review_changes_one_by_one(changes, lambda _: next(answers))
        assert decisions == [
            {"change_id": "one", "approved": True},
            {"change_id": "two", "approved": False},
        ]


class TestOperationBudget:
    """Gotcha #3: stopping rule."""

    def test_raises_below_floor(self):
        budget = OperationBudget(floor=20)
        with pytest.raises(BudgetExceeded):
            budget.check({"monthly_remaining": 5})

    def test_does_not_raise_above_floor(self):
        budget = OperationBudget(floor=20)
        budget.check({"monthly_remaining": 100})  # must not raise

    def test_missing_usage_does_not_raise(self):
        budget = OperationBudget(floor=20)
        budget.check(None)
        budget.check({})

    def test_client_chat_enforces_budget(self):
        client = SuperDocsClient("fake-key", budget=OperationBudget(floor=20))
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(
                200, {"response": "ok", "usage": {"monthly_remaining": 3}}
            )
            with pytest.raises(BudgetExceeded):
                client.chat("sess-1", "one more edit")

    def test_async_chat_requests_approval_mode(self):
        client = SuperDocsClient("fake-key")
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(200, {"job_id": "job-1"})
            result = client.chat_async(
                "sess-1",
                "edit this",
                approval_mode="ask_every_time",
            )
        assert result["job_id"] == "job-1"
        payload = mock_post.call_args[0][2]
        assert payload["approval_mode"] == "ask_every_time"

    def test_get_job_is_free_and_passes_compact_query(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, {"job_id": "job-1", "status": "in_progress"})
            result = client.get_job("job-1", compact=True)
        assert result["status"] == "in_progress"
        assert mock_get.call_args.kwargs["params"] == {"compact": "true"}

    def test_get_job_parses_encoded_pending_changes(self):
        client = SuperDocsClient("fake-key")
        pending = [{"change_id": "c1", "operation": "create"}]
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(
                200,
                {"job_id": "job-1", "status": "awaiting_approval", "metadata": {
                    "pending_changes": json.dumps(pending),
                }},
            )
            result = client.get_job("job-1")
        assert result["metadata"]["pending_changes"] == pending


class TestUploadRequiresSessionId:
    def test_session_id_included_in_payload(self):
        client = SuperDocsClient("fake-key")
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(200, {"html": "<p>x</p>", "persisted": True})
            client.upload("doc.html", "<p>x</p>", "sess-123")
            sent_payload = mock_post.call_args[0][2]  # (session, url, json_body, timeout)
        assert sent_payload["session_id"] == "sess-123"

    def test_chat_reuses_deterministic_idempotency_key(self):
        client = SuperDocsClient("fake-key")
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(200, {"response": "ok", "usage": {}})
            client.chat("sess-1", "same instruction")
            first_key = mock_post.call_args.kwargs["idempotency_key"]
            client.chat("sess-1", "same instruction")
            second_key = mock_post.call_args.kwargs["idempotency_key"]
        assert first_key == second_key


class TestRetryBehavior:
    def test_retries_on_429_then_succeeds(self):
        from superdocs_client import _post_with_backoff

        session = MagicMock()
        session.post.side_effect = [
            _mock_response(429),
            _mock_response(200, {"ok": True}),
        ]
        with patch("superdocs_client.time.sleep"):  # don't actually wait in tests
            r = _post_with_backoff(session, "http://x", {}, 30)
        assert r.status_code == 200
        assert session.post.call_count == 2

    def test_does_not_retry_on_400(self):
        from superdocs_client import _post_with_backoff

        session = MagicMock()
        session.post.return_value = _mock_response(400)
        r = _post_with_backoff(session, "http://x", {}, 30)
        assert r.status_code == 400
        assert session.post.call_count == 1  # no retry wasted on a validation error

    def test_gives_up_after_max_retries(self):
        from superdocs_client import _post_with_backoff

        session = MagicMock()
        session.post.return_value = _mock_response(503)
        with patch("superdocs_client.time.sleep"), pytest.raises(SuperDocsError):
            _post_with_backoff(session, "http://x", {}, 30)
        assert session.post.call_count == 3  # _MAX_RETRIES


class TestExportNoBudgetCheck:
    def test_export_does_not_touch_budget(self, tmp_path):
        client = SuperDocsClient("fake-key", budget=OperationBudget(floor=999999))  # would raise on ANY chat call
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(200, content=b"fake pdf bytes")
            out = client.export("sess-1", "pdf", str(tmp_path / "out.pdf"))  # must not raise
        assert Path(out).read_bytes() == b"fake pdf bytes"


class TestTemplatesSurface:
    def test_upload_template_sends_documented_multipart_file(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = _mock_response(200, {"template_id": "tpl-1", "name": "haccp-skeleton"})
            result = client.upload_template("haccp-skeleton", "<html>...</html>")
            sent_files = mock_post.call_args.kwargs["files"]
        assert sent_files["file"][0] == "haccp-skeleton.html"
        assert sent_files["file"][1] == b"<html>...</html>"
        assert result["template_id"] == "tpl-1"

    def test_get_document_detail_passes_include_html(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, {"structure": {"headings": []}})
            result = client.get_document_detail("doc-1", include_html=True)
        assert result["structure"] == {"headings": []}
        assert mock_get.call_args.kwargs["params"] == {"include_html": "true"}

    def test_get_session_jobs_reads_jobs_envelope(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, {"jobs": [{"job_id": "job-1"}]})
            result = client.get_session_jobs("sess-1")
        assert result == [{"job_id": "job-1"}]

    def test_find_active_job_matches_session_message(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client, "get_session_jobs", return_value=[
            {"job_id": "job-1", "status": "awaiting_approval", "metadata": {"message": "edit this"}},
            {"job_id": "job-2", "status": "completed", "metadata": {"message": "edit this"}},
        ]):
            assert client.find_active_job("sess-1", "edit this")["job_id"] == "job-1"

    def test_list_templates_handles_bare_list_response(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, [{"template_id": "tpl-1"}])
            result = client.list_templates()
        assert result == [{"template_id": "tpl-1"}]

    def test_list_templates_handles_enveloped_response(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, {"templates": [{"template_id": "tpl-1"}]})
            result = client.list_templates()
        assert result == [{"template_id": "tpl-1"}]


class TestVersionHistorySurface:
    def test_revert_sends_turn_index(self):
        client = SuperDocsClient("fake-key")
        with patch("superdocs_client._post_with_backoff") as mock_post:
            mock_post.return_value = _mock_response(200, {"reverted_to_turn": 2})
            result = client.revert("sess-1", turn_index=2)
            sent_payload = mock_post.call_args[0][2]
        assert sent_payload["turn_index"] == 2
        assert sent_payload["dry_run"] is False
        assert result["reverted_to_turn"] == 2

    def test_get_session_history_handles_bare_list(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, [{"turn": 0, "message": "hi"}])
            result = client.get_session_history("sess-1")
        assert result == [{"turn": 0, "message": "hi"}]

    def test_get_session_history_handles_enveloped_response(self):
        client = SuperDocsClient("fake-key")
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(200, {"history": [{"turn": 0}]})
            result = client.get_session_history("sess-1")
        assert result == [{"turn": 0}]