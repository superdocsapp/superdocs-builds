import tempfile
import unittest
from pathlib import Path

from src.screenshots import ScreenshotResolver


class ScreenshotResolverTests(unittest.TestCase):

    def test_resolves_existing_locale_screenshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            spanish = root / "es"

            english.mkdir()
            spanish.mkdir()

            (english / "create-project.png").touch()
            (spanish / "create-project.png").touch()

            resolver = ScreenshotResolver(root)

            result = resolver.resolve(
                "screenshots/en/create-project.png",
                "es",
            )

            self.assertFalse(result.missing)

            self.assertEqual(
                Path(result.resolved),
                spanish/"create-project.png",
            )

    def test_missing_locale_screenshot_is_flagged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            english.mkdir()

            (english / "create-project.png").touch()

            resolver = ScreenshotResolver(root)

            result = resolver.resolve(
                "screenshots/en/create-project.png",
                "fr",
            )

            self.assertTrue(result.missing)
            self.assertIsNone(result.resolved)

    def test_does_not_fallback_to_english(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            english.mkdir()

            (english / "create-project.png").touch()

            resolver = ScreenshotResolver(root)

            result = resolver.resolve(
                "screenshots/en/create-project.png",
                "fr",
            )

            self.assertIsNone(result.resolved)
            self.assertTrue(result.missing)


if __name__ == "__main__":
    unittest.main()