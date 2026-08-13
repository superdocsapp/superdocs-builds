import os
import unittest
from unittest import mock

from client import SuperDocsClient, session_url
from requests.exceptions import ConnectionError


class TestSuperDocsClient(unittest.TestCase):
    def setUp(self):
        self.env_patcher = mock.patch.dict(os.environ, {"SUPERDOCS_API_KEY": "sk_test_123"})
        self.env_patcher.start()
        self.client = SuperDocsClient()

    def tearDown(self):
        self.env_patcher.stop()

    @mock.patch("client.requests.get")
    def test_verify_connection_uses_sessions_endpoint(self, mock_get):
        mock_get.return_value.status_code = 200

        self.assertTrue(self.client.verify_connection())
        mock_get.assert_called_once_with(
            "https://api.superdocs.app/v1/sessions",
            headers={"Authorization": "Bearer sk_test_123"},
            timeout=30,
        )

    def test_verify_connection_missing_key(self):
        self.env_patcher.stop()
        client = SuperDocsClient()
        with self.assertRaises(ValueError):
            client.verify_connection()

    @mock.patch("client.requests.get")
    def test_verify_connection_rejects_invalid_key(self, mock_get):
        mock_get.return_value.status_code = 401
        self.assertFalse(self.client.verify_connection())

    @mock.patch("client.uuid.uuid4")
    @mock.patch("client.requests.post")
    def test_upload_document_success(self, mock_post, mock_uuid):
        mock_uuid.return_value = "sess_123"
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "document_id": "doc_123",
            "filename": "shell.docx",
            "chunks_count": 4,
        }

        with mock.patch("builtins.open", mock.mock_open(read_data=b"dummy")):
            result = self.client.upload_document("shell.docx")

        self.assertEqual(result["session_id"], "sess_123")
        self.assertEqual(result["document_id"], "doc_123")

    @mock.patch("client.requests.get")
    @mock.patch("client.requests.post")
    def test_upload_attachment_and_wait(self, mock_post, mock_get):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"job_id": "job_att_123"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "completed", "job_id": "job_att_123"}

        with mock.patch("builtins.open", mock.mock_open(read_data=b"dummy text")):
            result = self.client.upload_attachment_and_wait("sess_123", "report.txt")

        self.assertEqual(result["status"], "completed")

    @mock.patch("client.requests.post")
    def test_chat_async_defaults_to_review_mode(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"job_id": "job_123"}

        job_id = self.client.chat_async("sess_123", "Draft section 2.5.1")

        self.assertEqual(job_id, "job_123")
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["approval_mode"], "ask_every_time")

    @mock.patch("client.requests.post")
    def test_approve_changes(self, mock_post):
        mock_post.return_value.status_code = 200

        self.client.approve_changes(
            "sess_123",
            "job_123",
            [{"change_id": "chg_1"}, {"change_id": "chg_2"}],
        )

        mock_post.assert_called_once_with(
            "https://api.superdocs.app/v1/chat/sess_123/approve",
            headers={"Authorization": "Bearer sk_test_123", "Content-Type": "application/json"},
            json={
                "job_id": "job_123",
                "approved": True,
                "changes": [
                    {"change_id": "chg_1", "approved": True},
                    {"change_id": "chg_2", "approved": True},
                ],
            },
            timeout=30,
        )

    @mock.patch("client.requests.post")
    def test_export_document_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"exported_content"

        with mock.patch("builtins.open", mock.mock_open()) as opened:
            result = self.client.export_document("sess_123", "out.docx")

        self.assertEqual(result, "out.docx")
        opened().write.assert_called_once_with(b"exported_content")


class TestSessionUrl(unittest.TestCase):
    def test_session_url(self):
        self.assertEqual(session_url("abc"), "https://use.superdocs.app/sessions/abc")


if __name__ == "__main__":
    unittest.main()
