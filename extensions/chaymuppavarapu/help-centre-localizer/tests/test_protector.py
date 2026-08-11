import unittest

from src.protector import ProtectedContent


class ProtectedContentTests(unittest.TestCase):

    def test_protect_and_restore(self):
        text = (
            "Open SuperDocs and press Ctrl + K. "
            "Then run `npm install`."
        )

        protector = ProtectedContent(
            product_names=["SuperDocs"]
        )

        protected = protector.protect(text)

        self.assertNotIn("SuperDocs", protected)
        self.assertNotIn("Ctrl + K", protected)
        self.assertNotIn("`npm install`", protected)

        restored = protector.restore(protected)

        self.assertEqual(restored, text)

    def test_multiple_product_names(self):
        text = "SuperDocs works with Cursor."

        protector = ProtectedContent(
            product_names=["SuperDocs", "Cursor"]
        )

        protected = protector.protect(text)
        restored = protector.restore(protected)

        self.assertEqual(restored, text)


if __name__ == "__main__":
    unittest.main()