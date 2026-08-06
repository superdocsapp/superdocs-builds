"""PDF text extraction via PyMuPDF."""

from pathlib import Path

import fitz

from app.core.exceptions import DocumentParseError
from app.core.logging import get_logger
from app.services.parsers.base import BaseParser

logger = get_logger(__name__)


class PdfParser(BaseParser):
    def parse(self, file_path: Path) -> str:
        try:
            parts: list[str] = []
            with fitz.open(file_path) as doc:
                for page in doc:
                    parts.append(page.get_text("text"))
            text = "\n".join(parts).strip()
            logger.info("Parsed PDF %s (%s chars)", file_path.name, len(text))
            return text
        except Exception as exc:  # noqa: BLE001
            raise DocumentParseError(f"Failed to parse PDF: {exc}") from exc
