from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .source import SourceDocument


@dataclass(frozen=True)
class DocumentElement:
    """
    Normalized representation of one meaningful document element.

    The adapter layer can populate these elements from HTML, Markdown,
    LaTeX, DOCX, etc. The fingerprinting layer only works with this
    normalized representation.
    """

    element_type: str
    index: int
    text: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    formatting: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """
    A normalized document representation.

    `source_format` identifies the adapter that produced the document.
    `elements` preserves document order.

    `raw_content` preserves the original source document so that
    DocShield never has to reconstruct the original HTML from the
    normalized representation.
    """

    source_format: str
    elements: list[DocumentElement] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_content: str | None = None
    source: SourceDocument | None = None

    @classmethod
    def from_html(cls, html: str) -> "Document":
        """
        Parse HTML into the normalized representation.

        This deliberately records structure and attributes rather than
        attempting to render HTML. Rendering fidelity is validated by
        comparing structural information before and after an edit.
        """

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        elements: list[DocumentElement] = []
        counters: dict[str, int] = {}

        localizable_tags = {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "li",
            "blockquote",
            "pre",
            "code",
            "figcaption",
            "img",
            "a",
            "table",
        }

        for node in soup.find_all(localizable_tags):
            tag = node.name
            index = counters.get(tag, 0)
            counters[tag] = index + 1

            attributes: dict[str, str] = {}

            for key, value in node.attrs.items():
                if isinstance(value, list):
                    attributes[key] = " ".join(str(v) for v in value)
                else:
                    attributes[key] = str(value)

            if tag == "img":
                text = attributes.get("alt", "")
            else:
                text = node.get_text(" ", strip=True)

            formatting: dict[str, Any] = {}

            if tag.startswith("h"):
                formatting["heading_level"] = int(tag[1:])

            if tag == "table":
                rows = node.find_all("tr")
                formatting["row_count"] = len(rows)
                formatting["column_counts"] = [
                    len(row.find_all(["th", "td"]))
                    for row in rows
                ]

            if tag == "img":
                formatting["has_src"] = bool(
                    attributes.get("src")
                )
                formatting["has_alt"] = "alt" in attributes

            elements.append(
                DocumentElement(
                    element_type=tag,
                    index=index,
                    text=text,
                    attributes=attributes,
                    formatting=formatting,
                )
            )

        return cls(
            source_format="html",
            elements=elements,
            metadata={
                "title": (
                    soup.title.get_text(strip=True)
                    if soup.title
                    else None
                ),
                "html_lang": (
                    soup.html.get("lang")
                    if soup.html
                    else None
                ),
            },
            raw_content=html,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "Document":
        """
        Load a supported document from disk.

        HTML is supported by the first adapter implementation.
        Additional formats can be added without changing the
        fingerprint/validation model.
        """

        file_path = Path(path)

        if not file_path.exists():
            raise FileNotFoundError(file_path)

        suffix = file_path.suffix.lower()

        if suffix in {".html", ".htm"}:
            source = SourceDocument.load(file_path)

            document = cls.from_html(
                source.data.decode("utf-8")
            )

            document.source = source

            return document

        raise ValueError(
            f"Unsupported document format: {suffix}. "
            "Currently supported: .html, .htm"
        )

    def structure(self) -> list[dict[str, Any]]:
        """
        Return a JSON-serializable structural representation.
        """

        return [
            {
                "type": element.element_type,
                "index": element.index,
                "text": element.text,
                "attributes": dict(
                    sorted(element.attributes.items())
                ),
                "formatting": element.formatting,
            }
            for element in self.elements
        ]

    def element_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}

        for element in self.elements:
            counts[element.element_type] = (
                counts.get(element.element_type, 0) + 1
            )

        return counts