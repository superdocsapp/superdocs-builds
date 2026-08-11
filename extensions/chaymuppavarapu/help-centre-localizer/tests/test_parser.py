import unittest

from src.parser import ArticleParser


class ArticleParserTests(unittest.TestCase):

    def setUp(self):
        self.parser = ArticleParser()

        self.html = """
        <article>
            <h1>How to create a project</h1>

            <p>
                Open SuperDocs and press
                <code>Ctrl + K</code>.
            </p>

            <figure>
                <img
                    src="screenshots/en/create-project.png"
                    alt="Create project screen"
                >
                <figcaption>
                    Figure 1: Create Project
                </figcaption>
            </figure>

            <p>Continue with the next step.</p>
        </article>
        """

    def test_extracts_image_metadata(self):
        article = self.parser.parse(self.html)

        self.assertEqual(len(article.images), 1)

        image = article.images[0]

        self.assertEqual(
            image.src,
            "screenshots/en/create-project.png",
        )

        self.assertEqual(
            image.alt,
            "Create project screen",
        )

        self.assertEqual(
            image.caption,
            "Figure 1: Create Project",
        )

    def test_replaces_only_image_source(self):
        updated = self.parser.replace_image(
            self.html,
            image_index=0,
            new_src="screenshots/es/create-project.png",
        )

        self.assertIn(
            "screenshots/es/create-project.png",
            updated,
        )

        self.assertIn(
            "Figure 1: Create Project",
            updated,
        )

        self.assertIn(
            "Create project screen",
            updated,
        )

        self.assertIn(
            "<h1>How to create a project</h1>",
            updated,
        )


if __name__ == "__main__":
    unittest.main()