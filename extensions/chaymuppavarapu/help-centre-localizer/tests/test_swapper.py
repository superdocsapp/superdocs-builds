import tempfile
import unittest
from pathlib import Path

from src.swapper import ScreenshotSwapper


class ScreenshotSwapperTests(unittest.TestCase):

    def test_swaps_existing_locale_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            spanish = root / "es"

            english.mkdir()
            spanish.mkdir()

            (english / "create-project.png").touch()
            (spanish / "create-project.png").touch()

            html = """
            <article>
                <h1>How to create a project</h1>

                <figure>
                    <img
                        src="screenshots/en/create-project.png"
                        alt="Create project"
                    >
                    <figcaption>
                        Figure 1: Create Project
                    </figcaption>
                </figure>
            </article>
            """

            swapper = ScreenshotSwapper(root)

            result = swapper.swap(html, "es")

            self.assertEqual(result.replaced, 1)
            self.assertEqual(result.flags, [])

            self.assertIn(
                "es/create-project.png",
                result.html,
            )

            self.assertIn(
                "Figure 1: Create Project",
                result.html,
            )

    def test_missing_image_creates_flag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            english.mkdir()

            (english / "create-project.png").touch()

            html = """
            <article>
                <figure>
                    <img src="screenshots/en/create-project.png">
                    <figcaption>Figure 1</figcaption>
                </figure>
            </article>
            """

            swapper = ScreenshotSwapper(root)

            result = swapper.swap(html, "fr")

            self.assertEqual(result.replaced, 0)
            self.assertEqual(len(result.flags), 1)

            self.assertEqual(
                result.flags[0].locale,
                "fr",
            )

            self.assertIn(
                'data-localization-missing="true"',
                result.html,
            )

            self.assertIn(
                'data-missing-locale="fr"',
                result.html,
            )

            self.assertNotIn(
                'src="screenshots/en/create-project.png"',
                result.html,
            )

    def test_preserves_multiple_images_and_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            spanish = root / "es"

            english.mkdir()
            spanish.mkdir()

            for name in ["first.png", "second.png"]:
                (english / name).touch()
                (spanish / name).touch()

            html = """
            <article>
                <figure>
                    <img src="screenshots/en/first.png">
                    <figcaption>Figure 1</figcaption>
                </figure>

                <p>Some text.</p>

                <figure>
                    <img src="screenshots/en/second.png">
                    <figcaption>Figure 2</figcaption>
                </figure>
            </article>
            """

            swapper = ScreenshotSwapper(root)

            result = swapper.swap(html, "es")

            self.assertEqual(result.replaced, 2)
            self.assertEqual(len(result.flags), 0)

            first_position = result.html.index(
                "es/first.png"
            )

            second_position = result.html.index(
                "es/second.png"
            )

            self.assertLess(
                first_position,
                second_position,
            )

            self.assertIn("Figure 1", result.html)
            self.assertIn("Figure 2", result.html)


if __name__ == "__main__":
    unittest.main()