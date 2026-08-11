import unittest

from src.localizer import (
    Localizer,
    TestLocalizationProvider,
)


class LocalizerTests(unittest.TestCase):

    def test_localizes_text(self):
        localizer = Localizer(
            provider=TestLocalizationProvider(),
            product_names=["SuperDocs"],
        )

        result = localizer.localize(
            "Open SuperDocs and press Ctrl + K.",
            "es",
        )

        self.assertEqual(
            result.locale,
            "es",
        )

        self.assertIn(
            "[es]",
            result.localized,
        )

    def test_protected_content_survives_localization(self):
        localizer = Localizer(
            provider=TestLocalizationProvider(),
            product_names=["SuperDocs"],
        )

        source = (
            "Open SuperDocs and press Ctrl + K. "
            "Then run `npm install`."
        )

        result = localizer.localize(
            source,
            "es",
        )

        self.assertIn(
            "SuperDocs",
            result.localized,
        )

        self.assertIn(
            "Ctrl + K",
            result.localized,
        )

        self.assertIn(
            "`npm install`",
            result.localized,
        )


if __name__ == "__main__":
    unittest.main()