from __future__ import annotations

from html.parser import HTMLParser


SUPPORTED_BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
}


class _BlockTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self.lines: list[str] = []

        self._active_tag: str | None = None
        self._parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:
        tag = tag.lower()

        if tag in SUPPORTED_BLOCK_TAGS:
            self._flush()

            self._active_tag = tag
            self._parts = []

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self._active_tag is not None:
            self._parts.append(
                data
            )

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        tag = tag.lower()

        if (
            self._active_tag is not None
            and tag == self._active_tag
        ):
            self._flush()

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._active_tag is None:
            return

        text = " ".join(
            part.strip()
            for part in self._parts
            if part.strip()
        )

        text = " ".join(
            text.split()
        )

        if text:
            self.lines.append(
                text
            )

        self._active_tag = None
        self._parts = []


def extract_lines_from_superdocs_html(
    html: str,
) -> list[str]:
    if not isinstance(
        html,
        str,
    ):
        raise TypeError(
            "SuperDocs HTML must be a string."
        )

    if not html.strip():
        raise ValueError(
            "SuperDocs returned empty HTML."
        )

    parser = _BlockTextParser()

    parser.feed(
        html
    )

    parser.close()

    if not parser.lines:
        raise ValueError(
            "No supported document blocks "
            "were found in SuperDocs HTML."
        )

    return parser.lines