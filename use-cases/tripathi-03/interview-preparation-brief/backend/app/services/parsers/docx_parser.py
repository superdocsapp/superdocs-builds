"""DOCX text extraction via python-docx."""

from pathlib import Path

from docx import Document

from app.core.exceptions import DocumentParseError
from app.core.logging import get_logger
from app.services.parsers.base import BaseParser

logger = get_logger(__name__)


class DocxParser(BaseParser):
    def parse(self, file_path: Path) -> str:
        try:
            document = Document(str(file_path))
            paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
            # Include simple table cell text
            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        cell_text = cell.text.strip()
                        if cell_text:
                            paragraphs.append(cell_text)
            text = "\n".join(paragraphs).strip()
            logger.info("Parsed DOCX %s (%s chars)", file_path.name, len(text))
            return text
        except Exception as exc:  # noqa: BLE001
            raise DocumentParseError(f"Failed to parse DOCX: {exc}") from exc
