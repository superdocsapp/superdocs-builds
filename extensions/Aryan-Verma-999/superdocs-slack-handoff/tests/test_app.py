import hashlib
import hmac
import tempfile
import time
import unittest
from pathlib import Path

from app import Store, blocks, modal, now, plain_text, proposals_from, safe_failure_code, signed_slack_request, slack_file_url


class SlackHandoffTests(unittest.TestCase):
    def test_signature_rejects_tampered_or_stale_body(self):
        secret, body, timestamp = "secret", b"payload=hello", str(int(time.time()))
        signature = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
        self.assertTrue(signed_slack_request(secret, timestamp, signature, body))
        self.assertFalse(signed_slack_request(secret, timestamp, signature, b"payload=other"))
        self.assertFalse(signed_slack_request(secret, str(int(time.time()) - 301), signature, body))

    def test_provider_changes_are_unwrapped_without_persisting_text(self):
        changes = proposals_from({"pending_changes": '[{"change_id":"c1","old_html":"<p>Old</p>","new_html":"<p>New</p>"}]'})
        self.assertEqual(changes[0]["change_id"], "c1")
        self.assertEqual(plain_text(changes[0]["new_html"]), "New")

    def test_only_slack_private_download_urls_are_fetchable(self):
        self.assertTrue(slack_file_url("https://files.slack.com/files-pri/T1-F1/report.pdf"))
        self.assertFalse(slack_file_url("https://example.com/report.pdf"))
        self.assertFalse(slack_file_url("http://files.slack.com/report.pdf"))

    def test_message_shortcut_modal_stays_within_slack_input_limits(self):
        payload = {"team": {"id": "T1"}, "channel": {"id": "C1"}, "message": {"ts": "1.2"}, "user": {"id": "U1"}}
        view = modal(payload, {"id": "F1", "name": "manual.pdf", "mimetype": "application/pdf"})
        self.assertEqual(view["type"], "modal")
        instruction = next(block for block in view["blocks"] if block.get("block_id") == "instruction")
        self.assertEqual(instruction["element"]["max_length"], 3000)
        self.assertEqual(view["blocks"][0]["text"]["text"], "*▣ DOCUMENT INTAKE*\n`manual.pdf` is headed to SuperDocs. You will review every proposed revision before it is finalized.")

    def test_failures_are_persisted_as_safe_codes(self):
        self.assertEqual(safe_failure_code(RuntimeError("Slack API files.info failed: missing_scope")), "slack_files_info_missing_scope")
        self.assertEqual(safe_failure_code(RuntimeError("Slack API files.getUploadURLExternal failed: invalid_arguments")), "slack_files_getUploadURLExternal_invalid_arguments")
        self.assertEqual(safe_failure_code(RuntimeError("SuperDocs returned HTTP 401.")), "superdocs_http_401")
        self.assertEqual(safe_failure_code(RuntimeError("unexpected private detail")), "handoff_runtime_failure")

    def test_failed_export_is_retryable_without_reprocessing_document(self):
        handoff = {"id": "h1", "status": "failed", "file_name": "test.docx", "last_error": "slack_files_getUploadURLExternal_invalid_arguments", "session_id": "session-1"}
        self.assertEqual(blocks(handoff)[-1]["elements"][0]["action_id"], "superdocs_export")

    def test_retry_export_queues_only_the_requesters_completed_failed_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Store(Path(directory) / "handoffs.sqlite3")
            try:
                database.create({"id": "h1", "created_at": now(), "team_id": "T1", "channel_id": "C1", "thread_ts": "1.1", "requester_id": "U1", "file_id": "F1", "file_name": "test.docx", "file_mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "instruction": "Review"})
                database.complete_intake("h1", "session-1", "document-1", "job-1")
                database.set_status("h1", "failed", error="slack_files_getUploadURLExternal_invalid_arguments")
                retry = database.retry_latest_export("C1", "U1")
                self.assertIsNotNone(retry)
                self.assertEqual((retry["status"], retry["action"]), ("queued", "export"))
                self.assertIsNone(database.retry_latest_export("C1", "U2"))
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
