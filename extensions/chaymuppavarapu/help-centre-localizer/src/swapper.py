from dataclasses import dataclass

from bs4 import BeautifulSoup

from src.parser import ArticleParser
from src.screenshots import ScreenshotResolver


@dataclass
class ScreenshotFlag:
    image_index: int
    source: str
    locale: str
    reason: str


@dataclass
class SwapResult:
    html: str
    replaced: int
    flags: list[ScreenshotFlag]


class ScreenshotSwapper:
    """
    Replaces article screenshots with locale-specific screenshots.

    Missing locale screenshots are reported as flags rather than
    falling back to the source-language screenshot.
    """

    def __init__(self, screenshot_root):
        self.parser = ArticleParser()
        self.resolver = ScreenshotResolver(screenshot_root)

    def swap(self, html: str, locale: str) -> SwapResult:
        article = self.parser.parse(html)

        updated_html = html
        flags = []
        replaced = 0

        # Work backwards so changing an image source never changes
        # the index of images that still need to be processed.
        for image in reversed(article.images):
            result = self.resolver.resolve(
                image.src,
                locale,
            )

            if result.missing:
                flags.append(
                    ScreenshotFlag(
                        image_index=image.index,
                        source=image.src,
                        locale=locale,
                        reason="Locale screenshot is missing",
                    )
                )

                # Explicitly mark the missing asset in the document
                # instead of silently retaining the source-language
                # screenshot.
                soup = BeautifulSoup(
                    updated_html,
                    "html.parser",
                )

                images = soup.find_all("img")

                if image.index < len(images):
                    images[image.index]["src"] = ""
                    images[image.index][
                        "data-localization-missing"
                    ] = "true"
                    images[image.index][
                        "data-missing-locale"
                    ] = locale

                updated_html = str(soup)

                continue

            updated_html = self.parser.replace_image(
                updated_html,
                image.index,
                result.resolved,
            )

            replaced += 1

        flags.reverse()

        return SwapResult(
            html=updated_html,
            replaced=replaced,
            flags=flags,
        )