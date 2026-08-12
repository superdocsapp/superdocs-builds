import os
import unittest
from unittest.mock import patch
from client import SuperDocsClient
from requests.exceptions import ConnectionError

class TestSuperDocsClient(unittest.TestCase):
    
    @patch.dict(os.environ, {"SUPERDOCS_API_KEY": "sk_test_123"})
    @patch('client.requests.get')
    def test_verify_connection_success(self, mock_get):
        mock_get.return_value.status_code = 200
        
        client = SuperDocsClient()
        result = client.verify_connection()
        
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

    @patch.dict(os.environ, {"SUPERDOCS_API_KEY": "sk_test_123"})
    @patch('client.requests.get')
    def test_verify_connection_error(self, mock_get):
        mock_get.return_value.status_code = 401
        
        client = SuperDocsClient()
        self.assertFalse(client.verify_connection())

    @patch.dict(os.environ, {"SUPERDOCS_API_KEY": "sk_test_123"})
    @patch('client.requests.get')
    def test_verify_connection_exception(self, mock_get):
        mock_get.side_effect = ConnectionError("Network failure")
        
        client = SuperDocsClient()
        self.assertFalse(client.verify_connection())

if __name__ == '__main__':
    unittest.main()
