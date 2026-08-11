import tempfile
import unittest
from pathlib import Path

from src.localizer import (
    Localizer,
    TestLocalizationProvider,
)
from src.pipeline import LocalizationPipeline


class LocalizationPipelineTests(unittest.TestCase):

    def create_pipeline(self, root):
        localizer = Localizer(
            provider=TestLocalizationProvider(),
            product_names=["SuperDocs"],
        )

        return LocalizationPipeline(
            localizer=localizer,
            screenshot_root=root,
        )

    def test_first_run_localizes_all_paragraphs_and_swaps_image(self):
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

                <p>Open SuperDocs.</p>
                <p>Press Ctrl + K.</p>

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

            pipeline = self.create_pipeline(root)

            result = pipeline.localize(
                html,
                "es",
            )

            self.assertEqual(
                result.localized_paragraphs,
                [0, 1],
            )

            self.assertEqual(
                result.screenshot_replacements,
                1,
            )

            self.assertEqual(
                result.missing_screenshots,
                [],
            )

            self.assertIn(
                "SuperDocs",
                result.html,
            )

            self.assertIn(
                "Ctrl + K",
                result.html,
            )

            self.assertIn(
                "es/create-project.png",
                result.html,
            )

            self.assertIn(
                "Figure 1: Create Project",
                result.html,
            )

    def test_incremental_run_localizes_only_changed_paragraph(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            spanish = root / "es"

            english.mkdir()
            spanish.mkdir()

            (english / "create-project.png").touch()
            (spanish / "create-project.png").touch()

            old_html = """
            <article>
                <p>Open SuperDocs.</p>
                <p>Press Ctrl + K.</p>
                <p>Click Create Project.</p>

                <figure>
                    <img src="screenshots/en/create-project.png">
                    <figcaption>Figure 1</figcaption>
                </figure>
            </article>
            """

            new_html = """
            <article>
                <p>Open SuperDocs.</p>
                <p>Press Ctrl + Shift + K.</p>
                <p>Click Create Project.</p>

                <figure>
                    <img src="screenshots/en/create-project.png">
                    <figcaption>Figure 1</figcaption>
                </figure>
            </article>
            """

            pipeline = self.create_pipeline(root)

            result = pipeline.localize(
                new_html,
                "es",
                previous_source_html=old_html,
            )

            self.assertEqual(
                result.changed_paragraphs,
                [1],
            )

            self.assertEqual(
                result.localized_paragraphs,
                [1],
            )

            self.assertEqual(
                result.screenshot_replacements,
                1,
            )

            self.assertIn(
                "Press Ctrl + Shift + K.",
                result.html,
            )

            self.assertIn(
                "es/create-project.png",
                result.html,
            )

    def test_missing_screenshot_is_reported_in_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            english.mkdir()

            (english / "create-project.png").touch()

            html = """
            <article>
                <p>Open SuperDocs.</p>

                <figure>
                    <img src="screenshots/en/create-project.png">
                    <figcaption>Figure 1</figcaption>
                </figure>
            </article>
            """

            pipeline = self.create_pipeline(root)

            result = pipeline.localize(
                html,
                "fr",
            )

            self.assertEqual(
                result.screenshot_replacements,
                0,
            )

            self.assertEqual(
                len(result.missing_screenshots),
                1,
            )

            self.assertTrue(
                result.missing_screenshots[0].source
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

    def test_preserves_inline_code_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            spanish = root / "es"

            english.mkdir()
            spanish.mkdir()

            html = """
            <article>
                <p>
                    Run <code>npm install</code>
                    before starting the application.
                </p>
            </article>
            """

            pipeline = self.create_pipeline(root)

            result = pipeline.localize(
                html,
                "es",
            )

            self.assertIn(
                "<code>npm install</code>",
                result.html,
            )

            self.assertEqual(
                result.html.count(
                    "<code>npm install</code>"
                ),
                1,
            )

            self.assertNotIn(
                "Run npm install before",
                result.html,
            )

    def test_missing_screenshot_is_not_used_in_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            english.mkdir()

            (english / "create-project.svg").touch()

            html = """
            <article>
                <p>Open SuperDocs.</p>

                <figure>
                    <img
                        src="screenshots/en/create-project.svg"
                        alt="Create Project"
                    >
                    <figcaption>Figure 1</figcaption>
                </figure>
            </article>
            """

            pipeline = self.create_pipeline(root)

            result = pipeline.localize(
                html,
                "fr",
            )

            self.assertEqual(
                result.screenshot_replacements,
                0,
            )

            self.assertEqual(
                len(result.missing_screenshots),
                1,
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
                'src="screenshots/en/create-project.svg"',
                result.html,
            )


if __name__ == "__main__":
    unittest.main()

# Additional contract tests for the real provider-shaped pipeline.
class RecordingTranslationProvider:
    def __init__(self):
        self.calls = []

    def translate(self, text, locale):
        self.calls.append((text, locale))
        return f"TR:{text}"


class PipelineContractTests(unittest.TestCase):
    def test_only_changed_paragraph_is_sent_to_provider_and_attributes_survive(self):
        provider = RecordingTranslationProvider()
        localizer = Localizer(provider=provider, product_names=["SuperDocs"])

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=Path(temp_dir),
            )

            old_html = """
            <article>
                <p data-chunk-id="one">Open SuperDocs.</p>
                <p data-chunk-id="two">Click Create Project.</p>
            </article>
            """
            new_html = """
            <article>
                <p data-chunk-id="one">Open SuperDocs.</p>
                <p data-chunk-id="two">Click Create Project now.</p>
            </article>
            """

            result = pipeline.localize(
                new_html,
                "es",
                previous_source_html=old_html,
            )

        self.assertEqual(result.changed_paragraphs, [1])
        self.assertEqual(result.localized_paragraphs, [1])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][0], "Click Create Project now.")
        self.assertIn('data-chunk-id="one"', result.html)
        self.assertIn('data-chunk-id="two"', result.html)
        self.assertIn("Open SuperDocs.", result.html)
        self.assertIn("TR:Click Create Project now.", result.html)

    def test_inline_code_is_preserved_while_surrounding_text_is_translated(self):
        provider = RecordingTranslationProvider()
        localizer = Localizer(provider=provider, product_names=["SuperDocs"])

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=Path(temp_dir),
            )

            html = """
            <article>
                <p>Run <code>npm install</code> before starting the application.</p>
            </article>
            """

            result = pipeline.localize(html, "es")



        self.assertEqual(len(provider.calls), 1)
        self.assertIn("__INLINE_CODE_0__", provider.calls[0][0])
        self.assertIn("<code>npm install</code>", result.html)
        self.assertEqual(result.html.count("<code>npm install</code>"), 1)
    def test_localizes_heading_figcaption_and_image_alt(self):
        provider = RecordingTranslationProvider()
        localizer = Localizer(
            provider=provider,
            product_names=["SuperDocs"],
        )

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

                <p>Open SuperDocs.</p>

                <figure>
                    <img
                        src="screenshots/en/create-project.png"
                        alt="Create Project screen"
                    >
                    <figcaption>
                        Figure 1: Create Project
                    </figcaption>
                </figure>

                <h2>Install the CLI</h2>
            </article>
            """

            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=root,
            )

            result = pipeline.localize(
                html,
                "es",
            )

        # Paragraph + h1 + figcaption + h2 + image alt
        self.assertEqual(
            len(provider.calls),
            5,
        )

        self.assertIn(
            "TR:Open SuperDocs.",
            result.html,
        )

        self.assertIn(
            "TR:How to create a project",
            result.html,
        )

        self.assertIn(
            "TR:Figure 1: Create Project",
            result.html,
        )

        self.assertIn(
            "TR:Install the CLI",
            result.html,
        )

        self.assertIn(
            'alt="TR:Create Project screen"',
            result.html,
        )

        # Screenshot source must be swapped,
        # not translated by the localization provider.
        self.assertIn(
            "es/create-project.png",
            result.html,
        )

        self.assertNotIn(
            "en/create-project.png",
            result.html,
        )

    def test_image_src_is_preserved_when_alt_is_localized(self):
        provider = RecordingTranslationProvider()
        localizer = Localizer(
            provider=provider,
            product_names=["SuperDocs"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            english = root / "en"
            spanish = root / "es"

            english.mkdir()
            spanish.mkdir()

            (english / "create-project.svg").touch()
            (spanish / "create-project.svg").touch()

            html = """
            <article>
                <p>Open SuperDocs.</p>

                <img
                    src="screenshots/en/create-project.svg"
                    alt="Create Project screen"
                    width="800"
                    data-image-id="image-1"
                >
            </article>
            """

            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=root,
            )

            result = pipeline.localize(
                html,
                "es",
            )

        self.assertIn(
            "/es/create-project.svg",
            result.html.replace("\\", "/"),
        )

        self.assertIn(
            'alt="TR:Create Project screen"',
            result.html,
        )

        self.assertIn(
            'width="800"',
            result.html,
        )

        self.assertIn(
            'data-image-id="image-1"',
            result.html,
        )

        self.assertNotIn(
            'src="screenshots/en/create-project.svg"',
            result.html,
        )

    def test_incremental_heading_change_only_calls_provider_for_heading(self):
        provider = RecordingTranslationProvider()

        localizer = Localizer(
            provider=provider,
            product_names=["SuperDocs"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=Path(temp_dir),
            )

            old_html = """
            <article>
                <h1>How to create a project</h1>
                <p>Open SuperDocs.</p>
                <figcaption>Figure 1: Create Project</figcaption>
            </article>
            """

            new_html = """
            <article>
                <h1>How to create a new project</h1>
                <p>Open SuperDocs.</p>
                <figcaption>Figure 1: Create Project</figcaption>
            </article>
            """

            result = pipeline.localize(
                new_html,
                "es",
                previous_source_html=old_html,
            )

        self.assertEqual(
            len(provider.calls),
            1,
        )

        self.assertEqual(
            provider.calls[0][0],
            "How to create a new project",
        )

        self.assertIn(
            "TR:How to create a new project",
            result.html,
        )

    def test_incremental_alt_change_only_calls_provider_for_alt(self):
        provider = RecordingTranslationProvider()

        localizer = Localizer(
            provider=provider,
            product_names=["SuperDocs"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=Path(temp_dir),
            )

            old_html = """
            <article>
                <h1>How to create a project</h1>
                <p>Open SuperDocs.</p>
                <img alt="Create Project screen">
            </article>
            """

            new_html = """
            <article>
                <h1>How to create a project</h1>
                <p>Open SuperDocs.</p>
                <img alt="Project creation screen">
            </article>
            """

            result = pipeline.localize(
                new_html,
                "es",
                previous_source_html=old_html,
            )

        self.assertEqual(
            len(provider.calls),
            1,
        )

        self.assertEqual(
            provider.calls[0][0],
            "Project creation screen",
        )

        self.assertIn(
            'alt="TR:Project creation screen"',
            result.html,
        )

    def test_heading_attributes_are_preserved(self):
        provider = RecordingTranslationProvider()
        localizer = Localizer(
            provider=provider,
            product_names=["SuperDocs"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=Path(temp_dir),
            )

            html = """
            <article>
                <h1
                    data-chunk-id="heading-1"
                    id="create-project"
                    class="article-heading"
                >
                    How to create a project
                </h1>

                <p>Open SuperDocs.</p>
            </article>
            """

            result = pipeline.localize(
                html,
                "es",
            )

        self.assertIn(
            "TR:How to create a project",
            result.html,
        )

        self.assertIn(
            'data-chunk-id="heading-1"',
            result.html,
        )

        self.assertIn(
            'id="create-project"',
            result.html,
        )

        self.assertIn(
            'class="article-heading"',
            result.html,
        )

    def test_inline_code_is_preserved_in_non_paragraph_content(self):
        provider = RecordingTranslationProvider()
        localizer = Localizer(
            provider=provider,
            product_names=["SuperDocs"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = LocalizationPipeline(
                localizer=localizer,
                screenshot_root=Path(temp_dir),
            )

            html = """
            <article>
                <h2>
                    Run <code>npm install</code>
                    to install the CLI
                </h2>

                <p>Open SuperDocs.</p>
            </article>
            """

            result = pipeline.localize(
                html,
                "es",
            )

        self.assertIn(
            "<code>npm install</code>",
            result.html,
        )

        self.assertEqual(
            result.html.count(
                "<code>npm install</code>"
            ),
            1,
        )

        self.assertNotIn(
            "__INLINE_CODE_0__",
            result.html,
        )