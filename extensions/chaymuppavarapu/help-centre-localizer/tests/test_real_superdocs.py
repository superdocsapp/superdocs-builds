import os
import unittest

from src.superdocs_provider import SuperDocsLocalizationProvider


@unittest.skipUnless(
    os.getenv("RUN_REAL_SUPERDOCS_TEST") == "1"
    and os.getenv("SUPERDOCS_API_KEY"),
    "Set RUN_REAL_SUPERDOCS_TEST=1 to run live SuperDocs tests",
)
class RealSuperDocsTests(unittest.TestCase):
    def test_real_spanish_translation(self):
        provider = SuperDocsLocalizationProvider()

        result = provider.translate(
            "Open SuperDocs from your workspace.",
            "Spanish",
        )

        self.assertIsInstance(result, str)
        self.assertNotIn(
            "Open SuperDocs from your workspace",
            result,
        )
        self.assertIn("SuperDocs", result)


if __name__ == "__main__":
    unittest.main()
