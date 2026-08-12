import os
import unittest
from unittest.mock import patch
from client import SuperDocsClient
from requests.exceptions import ConnectionError

@patch.dict(os.environ, {"SUPERDOCS_API_KEY": "sk_test_123"})
class TestSuperDocsClient(unittest.TestCase):
    
    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {"SUPERDOCS_API_KEY": "sk_test_123"})
        self.env_patcher.start()
        self.client = SuperDocsClient()

    def tearDown(self):
        self.env_patcher.stop()

    @patch('client.requests.get')
    def test_verify_connection_success(self, mock_get):
        mock_get.return_value.status_code = 200
        
        result = self.client.verify_connection()
        
        self.assertTrue(result)
        mock_get.assert_called_once_with(
            "https://api.superdocs.app/v1/sessions",
            headers={"Authorization": "Bearer sk_test_123"}
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_verify_connection_missing_key(self):
        client = SuperDocsClient()
        with self.assertRaises(ValueError) as context:
            client.verify_connection()
        self.assertTrue("SUPERDOCS_API_KEY" in str(context.exception))

    @patch('client.requests.get')
    def test_verify_connection_error(self, mock_get):
        mock_get.return_value.status_code = 401
        
        self.assertFalse(self.client.verify_connection())

    @patch('client.requests.get')
    def test_verify_connection_exception(self, mock_get):
        mock_get.side_effect = ConnectionError("Network failure")
        
        self.assertFalse(self.client.verify_connection())

    @patch('client.requests.post')
    def test_upload_document_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"session_id": "sess_123", "document_id": "doc_123"}
        
        with patch('builtins.open', unittest.mock.mock_open(read_data=b"dummy")):
            result = self.client.upload_document("dummy.docx")
            
        self.assertEqual(result, {"session_id": "sess_123", "document_id": "doc_123"})

    @patch('client.requests.post')
    def test_upload_attachment_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"attachment_id": "att_123"}
        
        with patch('builtins.open', unittest.mock.mock_open(read_data=b"dummy text")):
            result = self.client.upload_attachment("sess_123", "dummy.txt")
            
        self.assertEqual(result, "att_123")

    @patch('client.requests.post')
    def test_chat_async_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"job_id": "job_123"}
        
        result = self.client.chat_async("sess_123", "Draft section 2.5")
        
        self.assertEqual(result, "job_123")
        mock_post.assert_called_once_with(
            "https://api.superdocs.app/v1/sessions/sess_123/chat_async",
            headers={"Authorization": "Bearer sk_test_123", "Content-Type": "application/json"},
            json={"prompt": "Draft section 2.5"}
        )

    @patch('client.requests.get')
    def test_get_job_status_success(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "completed"}
        
        result = self.client.get_job_status("job_123")
        
        self.assertEqual(result, "completed")
        mock_get.assert_called_once_with(
            "https://api.superdocs.app/v1/jobs/job_123",
            headers={"Authorization": "Bearer sk_test_123"}
        )

    @patch('client.requests.get')
    def test_export_document_success(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"exported_content"
        
        with patch('builtins.open', unittest.mock.mock_open()) as m:
            result = self.client.export_document("doc_123", "out.docx")
            
        self.assertEqual(result, "out.docx")
        mock_get.assert_called_once_with(
            "https://api.superdocs.app/v1/export",
            headers={"Authorization": "Bearer sk_test_123"},
            params={"document_id": "doc_123"}
        )
        m().write.assert_called_once_with(b"exported_content")

if __name__ == '__main__':
    unittest.main()
