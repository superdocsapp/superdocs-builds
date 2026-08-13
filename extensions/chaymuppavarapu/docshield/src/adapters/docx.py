from __future__ import annotations

from pathlib import Path
from typing import Any
import zipfile
import hashlib

from docx import Document as WordDocument

from ..document import Document, DocumentElement


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def _run_formatting(run: Any) -> dict[str, Any]:
    formatting: dict[str, Any] = {
        "bold": bool(run.bold),
        "italic": bool(run.italic),
        "underline": bool(run.underline),
    }

    if run.font.name:
        formatting["font_name"] = run.font.name

    if run.font.size is not None:
        formatting["font_size_emu"] = run.font.size.emu

    if run.font.color is not None:
        if run.font.color.type is not None:
            formatting["color_type"] = str(run.font.color.type)

        if run.font.color.rgb is not None:
            formatting["color"] = str(run.font.color.rgb)

    return formatting


def _paragraph_formatting(paragraph: Any) -> dict[str, Any]:
    fmt = paragraph.paragraph_format

    result: dict[str, Any] = {
        "alignment": (
            str(paragraph.alignment)
            if paragraph.alignment is not None
            else None
        ),
        "style": (
            paragraph.style.name
            if paragraph.style is not None
            else None
        ),
    }

    if fmt.left_indent is not None:
        result["left_indent_emu"] = fmt.left_indent.emu

    if fmt.right_indent is not None:
        result["right_indent_emu"] = fmt.right_indent.emu

    if fmt.first_line_indent is not None:
        result["first_line_indent_emu"] = fmt.first_line_indent.emu

    if fmt.space_before is not None:
        result["space_before_emu"] = fmt.space_before.emu

    if fmt.space_after is not None:
        result["space_after_emu"] = fmt.space_after.emu

    if fmt.line_spacing is not None:
        result["line_spacing"] = fmt.line_spacing

    return result


def _document_package_hash(path: Path) -> str:
    """
    Hash the original DOCX package.

    A DOCX is a ZIP/XML package. Preserving its package identity is
    important because reconstructing it from normalized elements can
    silently destroy formatting information.
    """
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def parse_docx(path: str | Path) -> Document:
    """
    Parse a DOCX into DocShield's normalized representation.

    The original DOCX bytes are preserved separately in metadata so
    validation never needs to reconstruct the original document from
    normalized elements.
    """

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    if file_path.suffix.lower() != ".docx":
        raise ValueError(
            f"Expected a .docx file, got: {file_path.suffix}"
        )

    if not zipfile.is_zipfile(file_path):
        raise ValueError("The file is not a valid DOCX ZIP package.")

    word_document = WordDocument(str(file_path))

    elements: list[DocumentElement] = []

    paragraph_index = 0

    for paragraph in word_document.paragraphs:
        text = paragraph.text

        runs = []

        for run in paragraph.runs:
            runs.append(
                {
                    "text": run.text,
                    "formatting": _run_formatting(run),
                }
            )

        formatting = _paragraph_formatting(paragraph)
        formatting["run_count"] = len(paragraph.runs)
        formatting["runs"] = runs

        style_name = (
            paragraph.style.name
            if paragraph.style is not None
            else ""
        )

        if style_name.lower().startswith("heading"):
            formatting["heading_style"] = style_name

        elements.append(
            DocumentElement(
                element_type="paragraph",
                index=paragraph_index,
                text=text,
                attributes={
                    "style": style_name,
                },
                formatting=formatting,
            )
        )

        paragraph_index += 1

    table_index = 0

    for table in word_document.tables:
        row_count = len(table.rows)
        column_counts = [
            len(row.cells)
            for row in table.rows
        ]

        rows: list[list[str]] = []

        for row in table.rows:
            rows.append(
                [_safe_text(cell.text) for cell in row.cells]
            )

        table_text = " ".join(
            cell
            for row in rows
            for cell in row
        )

        elements.append(
            DocumentElement(
                element_type="table",
                index=table_index,
                text=table_text,
                formatting={
                    "row_count": row_count,
                    "column_counts": column_counts,
                    "rows": rows,
                },
            )
        )

        table_index += 1

    sections = []

    for section in word_document.sections:
        sections.append(
            {
                "page_width_emu": (
                    section.page_width.emu
                    if section.page_width is not None
                    else None
                ),
                "page_height_emu": (
                    section.page_height.emu
                    if section.page_height is not None
                    else None
                ),
                "left_margin_emu": (
                    section.left_margin.emu
                    if section.left_margin is not None
                    else None
                ),
                "right_margin_emu": (
                    section.right_margin.emu
                    if section.right_margin is not None
                    else None
                ),
                "top_margin_emu": (
                    section.top_margin.emu
                    if section.top_margin is not None
                    else None
                ),
                "bottom_margin_emu": (
                    section.bottom_margin.emu
                    if section.bottom_margin is not None
                    else None
                ),
                "orientation": str(section.orientation),
            }
        )

    metadata = {
        "package_sha256": _document_package_hash(file_path),
        "paragraph_count": len(word_document.paragraphs),
        "table_count": len(word_document.tables),
        "section_count": len(word_document.sections),
        "sections": sections,
    }

    return Document(
        source_format="docx",
        elements=elements,
        metadata=metadata,
        raw_content=file_path.read_bytes().hex(),
    )


def load_docx(path: str | Path) -> Document:
    """Alias for parse_docx()."""
    return parse_docx(path)

