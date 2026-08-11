import os
import unittest
from unittest.mock import Mock, patch

from src.superdocs_provider import SuperDocsLocalizationProvider


class SuperDocsProviderTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"SUPERDOCS_API_KEY": "test-key"},
        clear=False,
    )
    @patch("src.superdocs_provider.requests.post")
    def test_sends_authenticated_request(self, mock_post):
        response = Mock()
        response.json.return_value = {
            "response": "Abra SuperDocs desde su espacio de trabajo.",
            "document_changes": {
                "updated_html": "<p>Open SuperDocs from your workspace.</p>"
            },
        }
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        provider = SuperDocsLocalizationProvider()
        result = provider.translate(
            "Open SuperDocs from your workspace.",
            "es",
        )

        self.assertEqual(
            result,
            "Abra SuperDocs desde su espacio de trabajo.",
        )

        call = mock_post.call_args
        self.assertEqual(
            call.kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )
        self.assertEqual(
            call.kwargs["json"]["approval_mode"],
            "approve_all",
        )
        self.assertEqual(
            call.kwargs["json"]["document_html"],
            "Open SuperDocs from your workspace.",
        )

    @patch.dict(
        os.environ,
        {"SUPERDOCS_API_KEY": "test-key"},
        clear=False,
    )
    @patch("src.superdocs_provider.requests.post")
    def test_translate_uses_response_not_updated_html(self, mock_post):
        response = Mock()
        response.json.return_value = {
            "response": "Contenido traducido.",
            "document_changes": {
                "updated_html": "<p>Original English content.</p>"
            },
        }
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        provider = SuperDocsLocalizationProvider()

        self.assertEqual(
            provider.translate("Original English content.", "es"),
            "Contenido traducido.",
        )

    @patch.dict(
        os.environ,
        {"SUPERDOCS_API_KEY": "test-key"},
        clear=False,
    )
    def test_missing_response_field_fails_clearly(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "usable translated response",
        ):
            SuperDocsLocalizationProvider._extract_response({
                "document_changes": {
                    "updated_html": "<p>Original</p>"
                }
            })


if __name__ == "__main__":
    unittest.main()
