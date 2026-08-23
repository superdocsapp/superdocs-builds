from dataclasses import dataclass

from bs4 import BeautifulSoup

from src.incremental import (
    ContentUnit,
    IncrementalAnalyzer,
)
from src.localizer import Localizer
from src.swapper import ScreenshotSwapper


@dataclass
class PipelineResult:
    html: str
    localized_paragraphs: list[int]
    screenshot_replacements: int
    missing_screenshots: list
    changed_paragraphs: list[int]


class LocalizationPipeline:
    """
    Localize changed article content and swap screenshots.

    Responsibilities:
    - detect changed paragraphs
    - localize changed paragraphs
    - localize human-readable headings/captions/alt text
    - preserve inline code
    - preserve product names and protected content
    - preserve HTML structure
    - preserve existing attributes
    - preserve data-chunk-id attributes
    - swap locale screenshots
    - report missing screenshots
    """

    # HTML elements whose text is human-readable documentation
    # but which are not paragraphs.
    TRANSLATABLE_TEXT_TAGS = (
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "figcaption",
    )

    def __init__(
        self,
        localizer: Localizer,
        screenshot_root,
    ):
        self.localizer = localizer
        self.swapper = ScreenshotSwapper(
            screenshot_root
        )
        self.incremental = IncrementalAnalyzer()

    @staticmethod
    def _paragraphs(
        html: str,
    ) -> list[str]:
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        return [
            paragraph.get_text(
                " ",
                strip=True,
            )
            for paragraph in soup.find_all("p")
        ]

    @classmethod
    def _content_units(
        cls,
        html: str,
    ) -> list[ContentUnit]:
        """
        Extract every human-readable piece of article content
        that participates in incremental localization.

        Supported:
            - h1-h6
            - p
            - figcaption
            - img alt

        Technical attributes such as img src are deliberately
        excluded because screenshot swapping owns those.
        """

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        counters = {
            "h1": 0,
            "h2": 0,
            "h3": 0,
            "h4": 0,
            "h5": 0,
            "h6": 0,
            "p": 0,
            "figcaption": 0,
            "img-alt": 0,
        }

        units = []

        for element in soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "p",
                "figcaption",
                "img",
            ]
        ):
            if element.name == "img":
                if not element.has_attr("alt"):
                    continue

                text = element.get(
                    "alt",
                    "",
                ).strip()

                if not text:
                    continue

                kind = "img-alt"

            else:
                text = element.get_text(
                    " ",
                    strip=True,
                )

                if not text:
                    continue

                kind = element.name

            index = counters[kind]

            counters[kind] += 1

            units.append(
                ContentUnit(
                    key=f"{kind}:{index}",
                    kind=kind,
                    index=index,
                    text=text,
                )
            )

        return units

    @staticmethod
    def _extract_translated_content(
        translated: str,
    ) -> str:
        """
        Accept plain text or a single paragraph returned
        by the localization provider.
        """

        translated = translated.strip()

        if not translated:
            raise RuntimeError(
                "Localization provider returned "
                "an empty translation."
            )

        soup = BeautifulSoup(
            translated,
            "html.parser",
        )

        paragraph = soup.find("p")

        if paragraph is not None:
            return paragraph.decode_contents()

        return translated

    @staticmethod
    def _extract_translated_text(
        translated: str,
    ) -> str:
        """
        Extract human-readable text from a provider response.

        SuperDocs may return:
            plain text
        or:
            <p>translated text</p>
        """

        translated = translated.strip()

        if not translated:
            raise RuntimeError(
                "Localization provider returned "
                "an empty translation."
            )

        soup = BeautifulSoup(
            translated,
            "html.parser",
        )

        paragraph = soup.find("p")

        if paragraph is not None:
            return paragraph.get_text(
                " ",
                strip=True,
            )

        return soup.get_text(
            " ",
            strip=True,
        )

    def _localize_paragraph(
        self,
        paragraph,
        locale: str,
    ) -> None:
        """
        Translate one paragraph while preserving
        inline HTML such as <code>.
        """

        protected_elements = paragraph.find_all(
            ["code", "pre"]
        )

        protected_html = {}

        for index, element in enumerate(
            protected_elements
        ):
            token = (
                f"__INLINE_CODE_{index}__"
            )

            protected_html[token] = str(
                element
            )

            element.replace_with(token)

        source_text = paragraph.get_text(
            " ",
            strip=True,
        )

        result = self.localizer.localize(
            source_text,
            locale,
        )

        translated_content = (
            self._extract_translated_content(
                result.localized
            )
        )

        if (
            source_text
            and translated_content.strip()
            == source_text.strip()
        ):
            raise RuntimeError(
                "SuperDocs did not translate "
                "the changed paragraph."
            )

        for token, original_html in (
            protected_html.items()
        ):
            translated_content = (
                translated_content.replace(
                    f"`{token}`",
                    original_html,
                )
            )

            translated_content = (
                translated_content.replace(
                    token,
                    original_html,
                )
            )

        paragraph.clear()

        content_soup = BeautifulSoup(
            translated_content,
            "html.parser",
        )

        for node in list(
            content_soup.contents
        ):
            paragraph.append(node)

    @staticmethod
    def _remove_leading_source_echo(
        translated_text: str,
        source_text: str,
    ) -> str:
        """
        Remove an echoed source sentence only when it appears
        as a complete leading segment followed by translated
        content.

        Examples:

            "How to create a project Cómo crear un proyecto"
                -> "Cómo crear un proyecto"

            "TR:How to create a project"
                -> unchanged

            "Cómo crear un proyecto"
                -> unchanged
        """

        translated = translated_text.strip()
        source = source_text.strip()

        if not translated or not source:
            return translated

        if translated == source:
            return translated

        if not translated.startswith(source):
            return translated

        remainder = translated[len(source):]

        # The source must end at a textual boundary.
        if not remainder:
            return translated

        if not remainder[0].isspace():
            return translated

        remainder = remainder.strip()

        if not remainder:
            return translated

        return remainder

    def _localize_element_text(
        self,
        element,
        locale: str,
    ) -> None:
        """
        Translate the human-readable text of a
        heading or figcaption.

        HTML attributes and element structure are
        preserved.
        """

        source_text = element.get_text(
            " ",
            strip=True,
        )

        if not source_text:
            return

        # Preserve inline code if a heading/caption
        # happens to contain one.
        protected_elements = element.find_all(
            ["code", "pre"]
        )

        protected_html = {}

        for index, child in enumerate(
            protected_elements
        ):
            token = (
                f"__INLINE_CODE_{index}__"
            )

            protected_html[token] = str(
                child
            )

            child.replace_with(token)

        source_text = element.get_text(
            " ",
            strip=True,
        )

        result = self.localizer.localize(
            source_text,
            locale,
        )

        translated_text = (
            self._extract_translated_text(
                result.localized
            )
        )

        translated_text = self._remove_leading_source_echo(
            translated_text,
            source_text,
        )

        if (
            source_text
            and translated_text.strip()
            == source_text.strip()
        ):
            raise RuntimeError(
                "SuperDocs did not translate "
                f"<{element.name}> content: "
                f"{source_text}"
            )

        for token, original_html in (
            protected_html.items()
        ):
            translated_text = (
                translated_text.replace(
                    f"`{token}`",
                    original_html,
                )
            )

            translated_text = (
                translated_text.replace(
                    token,
                    original_html,
                )
            )

        element.clear()

        content_soup = BeautifulSoup(
            translated_text,
            "html.parser",
        )

        for node in list(
            content_soup.contents
        ):
            element.append(node)

    def _localize_image_alt(
        self,
        image,
        locale: str,
    ) -> None:
        """
        Translate an image's alt attribute.

        The image src and every other attribute
        remain unchanged.
        """

        if not image.has_attr("alt"):
            return

        source_text = (
            image.get("alt", "").strip()
        )

        if not source_text:
            return

        result = self.localizer.localize(
            source_text,
            locale,
        )

        translated_text = (
            self._extract_translated_text(
                result.localized
            )
        )

        if (
            source_text
            and translated_text.strip()
            == source_text.strip()
        ):
            raise RuntimeError(
                "SuperDocs did not translate "
                f"image alt text: {source_text}"
            )

        image["alt"] = translated_text

    def _localize_content_unit(
        self,
        soup,
        unit: ContentUnit,
        locale: str,
    ) -> None:
        """
        Localize exactly one changed content unit.
        """

        counters = {
            "h1": 0,
            "h2": 0,
            "h3": 0,
            "h4": 0,
            "h5": 0,
            "h6": 0,
            "p": 0,
            "figcaption": 0,
            "img-alt": 0,
        }

        if unit.kind == "img-alt":
            elements = soup.find_all("img")

            for image in elements:
                if not image.has_attr("alt"):
                    continue

                if not image.get("alt", "").strip():
                    continue

                if counters["img-alt"] == unit.index:
                    self._localize_image_alt(
                        image,
                        locale,
                    )
                    return

                counters["img-alt"] += 1

            return

        elements = soup.find_all(unit.kind)

        if unit.index >= len(elements):
            return

        element = elements[unit.index]

        if unit.kind == "p":
            self._localize_paragraph(
                element,
                locale,
            )
        else:
            self._localize_element_text(
                element,
                locale,
            )

    def _localize_non_paragraph_content(
        self,
        soup,
        locale: str,
    ) -> None:
        """
        Localize human-readable document elements
        outside paragraphs.

        Currently:
        - h1-h6
        - figcaption
        - img alt
        """

        for tag_name in (
            self.TRANSLATABLE_TEXT_TAGS
        ):
            for element in soup.find_all(
                tag_name
            ):
                self._localize_element_text(
                    element,
                    locale,
                )

        for image in soup.find_all("img"):
            self._localize_image_alt(
                image,
                locale,
            )

    def localize(
        self,
        source_html: str,
        locale: str,
        previous_source_html: str | None = None,
    ) -> PipelineResult:
        """
        Localize changed human-readable content and swap
        locale-specific screenshots.

        First run:
            localizes every supported content unit.

        Incremental run:
            localizes only content units that changed.
        """

        current_units = self._content_units(
            source_html
        )

        if previous_source_html is None:
            changed_units = current_units

        else:
            previous_units = self._content_units(
                previous_source_html
            )

            comparison = (
                self.incremental.compare_units(
                    previous_units,
                    current_units,
                )
            )

            changed_keys = set(
                comparison.changed_keys
            )

            changed_units = [
                unit
                for unit in current_units
                if unit.key in changed_keys
            ]

        soup = BeautifulSoup(
            source_html,
            "html.parser",
        )

        html_element = soup.find("html")

        if html_element is not None:
            html_element["lang"] = locale

        localized_paragraphs = []

        for unit in changed_units:
            self._localize_content_unit(
                soup,
                unit,
                locale,
            )

            if unit.kind == "p":
                localized_paragraphs.append(
                    unit.index
                )

        updated_html = str(soup)

        screenshot_result = (
            self.swapper.swap(
                updated_html,
                locale,
            )
        )

        return PipelineResult(
            html=screenshot_result.html,
            localized_paragraphs=(
                localized_paragraphs
            ),
            screenshot_replacements=(
                screenshot_result.replaced
            ),
            missing_screenshots=(
                screenshot_result.flags
            ),
            changed_paragraphs=(
                localized_paragraphs
            ),
        )