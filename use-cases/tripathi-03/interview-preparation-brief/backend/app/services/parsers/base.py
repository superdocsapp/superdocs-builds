"""Document parser interfaces and factory."""

from abc import ABC, abstractmethod
from pathlib import Path

from app.core.exceptions import UnsupportedFileTypeError


class BaseParser(ABC):
    """Parse a binary document into plain text."""

    @abstractmethod
    def parse(self, file_path: Path) -> str:
        raise NotImplementedError


def get_parser_for_filename(filename: str) -> BaseParser:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        from app.services.parsers.pdf_parser import PdfParser

        return PdfParser()
    if lower.endswith(".docx"):
        from app.services.parsers.docx_parser import DocxParser

        return DocxParser()
    raise UnsupportedFileTypeError(
        f"Unsupported file type for '{filename}'. Allowed: .pdf, .docx"
    )


def parse_file(file_path: Path, filename: str | None = None) -> str:
    parser = get_parser_for_filename(filename or file_path.name)
    text = parser.parse(file_path)
    if not text.strip():
        from app.core.exceptions import DocumentParseError

        raise DocumentParseError(f"No extractable text found in '{filename or file_path.name}'")
    return text.strip()
