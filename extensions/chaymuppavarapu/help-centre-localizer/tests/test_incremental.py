import unittest

from src.incremental import (
    ContentUnit,
    IncrementalAnalyzer,
)


class IncrementalAnalyzerTests(unittest.TestCase):

    def setUp(self):
        self.analyzer = IncrementalAnalyzer()

    def test_only_changed_paragraph_is_detected(self):
        old = [
            "Create a project.",
            "Open the dashboard.",
            "Click Create.",
        ]

        new = [
            "Create a project.",
            "Open the new dashboard.",
            "Click Create.",
        ]

        result = self.analyzer.compare(old, new)

        self.assertEqual(
            result.changed_indices,
            [1],
        )

    def test_identical_article_has_no_changes(self):
        paragraphs = [
            "Create a project.",
            "Open the dashboard.",
            "Click Create.",
        ]

        result = self.analyzer.compare(
            paragraphs,
            paragraphs,
        )

        self.assertEqual(
            result.changed_indices,
            [],
        )

    def test_added_paragraph_is_detected(self):
        old = [
            "Create a project.",
            "Open the dashboard.",
        ]

        new = [
            "Create a project.",
            "Open the dashboard.",
            "Click Create.",
        ]

        result = self.analyzer.compare(old, new)

        self.assertEqual(
            result.changed_indices,
            [2],
        )

    def test_removed_paragraph_is_detected(self):
        old = [
            "Create a project.",
            "Open the dashboard.",
            "Click Create.",
        ]

        new = [
            "Create a project.",
            "Open the dashboard.",
        ]

        result = self.analyzer.compare(old, new)

        self.assertEqual(
            result.changed_indices,
            [2],
        )

    def test_whitespace_only_change_is_not_translation_change(self):
        old = [
            "Create a project.",
        ]

        new = [
            "  Create   a project. ",
        ]

        result = self.analyzer.compare(old, new)

        self.assertEqual(
            result.changed_indices,
            [],
        )

    def test_heading_change_is_detected(self):
        old = [
            ContentUnit(
                key="h1:0",
                kind="h1",
                index=0,
                text="How to create a project",
            ),
        ]

        new = [
            ContentUnit(
                key="h1:0",
                kind="h1",
                index=0,
                text="How to create a new project",
            ),
        ]

        result = self.analyzer.compare_units(
            old,
            new,
        )

        self.assertEqual(
            result.changed_keys,
            ["h1:0"],
        )

    def test_figcaption_change_is_detected(self):
        old = [
            ContentUnit(
                key="figcaption:0",
                kind="figcaption",
                index=0,
                text="Figure 1: Create Project",
            ),
        ]

        new = [
            ContentUnit(
                key="figcaption:0",
                kind="figcaption",
                index=0,
                text="Figure 1: Project Creation",
            ),
        ]

        result = self.analyzer.compare_units(
            old,
            new,
        )

        self.assertEqual(
            result.changed_keys,
            ["figcaption:0"],
        )

    def test_image_alt_change_is_detected(self):
        old = [
            ContentUnit(
                key="img-alt:0",
                kind="img-alt",
                index=0,
                text="Create Project screen",
            ),
        ]

        new = [
            ContentUnit(
                key="img-alt:0",
                kind="img-alt",
                index=0,
                text="Project creation screen",
            ),
        ]

        result = self.analyzer.compare_units(
            old,
            new,
        )

        self.assertEqual(
            result.changed_keys,
            ["img-alt:0"],
        )

    def test_unchanged_mixed_content_has_no_changes(self):
        units = [
            ContentUnit(
                key="h1:0",
                kind="h1",
                index=0,
                text="How to create a project",
            ),
            ContentUnit(
                key="p:0",
                kind="p",
                index=0,
                text="Open SuperDocs.",
            ),
            ContentUnit(
                key="figcaption:0",
                kind="figcaption",
                index=0,
                text="Figure 1: Create Project",
            ),
            ContentUnit(
                key="img-alt:0",
                kind="img-alt",
                index=0,
                text="Create Project screen",
            ),
        ]

        result = self.analyzer.compare_units(
            units,
            units,
        )

        self.assertEqual(
            result.changed_keys,
            [],
        )

    def test_inserted_paragraph_does_not_shift_other_units(self):
        old = [
            ContentUnit(
                key="p:0",
                kind="p",
                index=0,
                text="First paragraph.",
            ),
            ContentUnit(
                key="p:1",
                kind="p",
                index=1,
                text="Second paragraph.",
            ),
        ]

        new = [
            ContentUnit(
                key="p:0",
                kind="p",
                index=0,
                text="First paragraph.",
            ),
            ContentUnit(
                key="p:1",
                kind="p",
                index=1,
                text="Inserted paragraph.",
            ),
            ContentUnit(
                key="p:2",
                kind="p",
                index=2,
                text="Second paragraph.",
            ),
        ]

        result = self.analyzer.compare_units(
            old,
            new,
        )

        self.assertEqual(
            result.changed_keys,
            ["p:1"],
        )


if __name__ == "__main__":
    unittest.main()