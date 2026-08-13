from __future__ import annotations

from pathlib import Path

from ..document import Document
from .docx import parse_docx
from .latex import parse_latex


def parse_document(path: str | Path) -> Document:
    """
    Parse a supported document using the appropriate format adapter.
    """

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    suffix = file_path.suffix.lower()

    if suffix in {".html", ".htm"}:
        return Document.from_file(file_path)

    if suffix in {".tex", ".latex"}:
        return parse_latex(file_path)

    if suffix == ".docx":
        return parse_docx(file_path)

    raise ValueError(
        f"Unsupported document format: {suffix}. "
        "Supported formats: HTML, LaTeX, DOCX."
    )