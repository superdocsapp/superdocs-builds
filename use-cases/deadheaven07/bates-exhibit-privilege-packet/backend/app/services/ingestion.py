import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import magic

from app.config import get_settings
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.time import utc_now

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    document: Document
    page_count: int
    extracted_text: str
    is_searchable: bool
    processed_file_path: str


class FileValidationError(Exception):
    pass


class IngestionService:
    SUPPORTED_MIME_TYPES = {
        "application/pdf": DocumentType.PDF,
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document": DocumentType.DOCX,
        "image/jpeg": DocumentType.IMAGE,
        "image/png": DocumentType.IMAGE,
        "image/tiff": DocumentType.IMAGE,
        "image/webp": DocumentType.IMAGE,
    }

    MAX_FILE_SIZE = 100 * 1024 * 1024

    def __init__(self):
        settings.ensure_directories()

    def validate_file(self, file: BinaryIO, filename: str) -> tuple[str, int]:
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)

        if file_size > self.MAX_FILE_SIZE:
            raise FileValidationError(f"File size {file_size} exceeds maximum {self.MAX_FILE_SIZE}")

        mime_type = magic.from_buffer(file.read(2048), mime=True)
        file.seek(0)

        if mime_type not in self.SUPPORTED_MIME_TYPES:
            raise FileValidationError(f"Unsupported file type: {mime_type}")

        return mime_type, file_size

    def calculate_sha256(self, file: BinaryIO) -> str:
        sha256 = hashlib.sha256()
        file.seek(0)
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)
        file.seek(0)
        return sha256.hexdigest()

    def save_original(self, file: BinaryIO, sha256: str, original_filename: str) -> Path:
        ext = Path(original_filename).suffix
        stored_filename = f"{sha256}{ext}"
        stored_path = settings.originals_path / stored_filename

        file.seek(0)
        with open(stored_path, "wb") as f:
            shutil.copyfileobj(file, f)
        file.seek(0)

        return stored_path

    def detect_document_type(self, mime_type: str, file_path: Path) -> DocumentType:
        return self.SUPPORTED_MIME_TYPES.get(mime_type, DocumentType.UNKNOWN)

    def count_pages(self, file_path: Path, document_type: DocumentType) -> int:
        try:
            if document_type in (DocumentType.PDF, DocumentType.SCANNED_PDF):
                import fitz

                doc = fitz.open(file_path)
                count = int(doc.page_count)
                doc.close()
                if count == 0:
                    raise FileValidationError("PDF contains no pages")
                return count
            elif document_type == DocumentType.DOCX:
                return self._count_docx_pages(file_path)
            elif document_type == DocumentType.IMAGE:
                return 1
            return 0
        except FileValidationError:
            raise
        except Exception as e:
            raise FileValidationError(f"Corrupt or unreadable PDF: {e}") from e

    def _count_docx_pages(self, file_path: Path) -> int:
        try:
            import subprocess

            _ = subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    "/tmp",
                    str(file_path),
                ],
                capture_output=True,
                timeout=60,
            )
            pdf_path = Path("/tmp") / (file_path.stem + ".pdf")
            if pdf_path.exists():
                import fitz

                doc = fitz.open(pdf_path)
                count = int(doc.page_count)
                doc.close()
                pdf_path.unlink(missing_ok=True)
                return count
        except Exception:
            pass
        return 1

    def convert_to_pdf(self, file_path: Path, document_type: DocumentType) -> Path | None:
        """Convert DOCX/image originals to a buildable PDF at processed/{sha256}.pdf."""
        output_path = settings.processed_path / f"{file_path.stem}.pdf"
        try:
            if document_type == DocumentType.DOCX:
                import subprocess

                subprocess.run(
                    [
                        "libreoffice",
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(output_path.parent),
                        str(file_path),
                    ],
                    capture_output=True,
                    timeout=120,
                )
                if output_path.exists():
                    return output_path
                return None
            elif document_type == DocumentType.IMAGE:
                from PIL import Image

                image = Image.open(file_path)
                image.convert("RGB").save(output_path, "PDF", resolution=100.0)
                return output_path
            return None
        except Exception as e:
            logger.warning(f"Failed to convert {file_path} to PDF: {e}")
            return None

    def extract_text(self, file_path: Path, document_type: DocumentType) -> tuple[str, bool]:
        """Extract text from a file, returning (text, is_searchable).

        Text PDFs are read directly via PyMuPDF. Scanned/OCR content falls
        back to tesseract when available; otherwise an empty (non-searchable)
        result is returned — SuperDocs is the primary intelligence layer for
        OCR, so local extraction is best-effort only.
        """
        try:
            if document_type in (DocumentType.PDF, DocumentType.SCANNED_PDF):
                import fitz

                doc = fitz.open(file_path)
                try:
                    text = "".join(page.get_text() for page in doc)
                finally:
                    doc.close()
                if text.strip():
                    return text, True
                return self._ocr_text(file_path)

            if document_type == DocumentType.DOCX:
                return self._extract_docx_text(file_path)

            if document_type == DocumentType.IMAGE:
                return self._ocr_text(file_path)

            return "", False
        except Exception as e:
            logger.warning(f"Failed to extract text from {file_path}: {e}")
            return "", False

    def _ocr_text(self, file_path: Path) -> tuple[str, bool]:
        """Best-effort local OCR via tesseract."""
        try:
            import pytesseract
            from PIL import Image

            if file_path.suffix.lower() == ".pdf":
                import fitz

                doc = fitz.open(file_path)
                page_texts = []
                for page in doc:
                    pix = page.get_pixmap(dpi=150)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    pt = pytesseract.image_to_string(img, lang=settings.tesseract_lang).strip()
                    if pt:
                        page_texts.append(pt)
                doc.close()
                text = "\n\n".join(page_texts).strip()
                return text, bool(text)
            else:
                image = Image.open(file_path)
                text = pytesseract.image_to_string(image, lang=settings.tesseract_lang).strip()
                return text, bool(text)
        except Exception as e:
            logger.warning(f"Local OCR unavailable for {file_path}: {e}")
            return "", False

    def _extract_docx_text(self, file_path: Path) -> tuple[str, bool]:
        try:
            import zipfile
            from xml.etree import ElementTree

            with zipfile.ZipFile(file_path) as zf:
                xml = zf.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            paragraphs = ["".join(node.itertext()) for node in root.iter(f"{{{w_ns}}}p")]
            text = "\n".join(p for p in paragraphs if p.strip())
            return text, bool(text)
        except Exception as e:
            logger.warning(f"Failed to extract DOCX text from {file_path}: {e}")
            return "", False

    def create_searchable_pdf(self, file_path: Path, document_type: DocumentType) -> Path | None:
        """Produce a searchable PDF for packet building.

        Text PDFs are already searchable. DOCX/image originals are converted
        via LibreOffice/Pillow; OCR'd text is layered on by SuperDocs in the
        primary flow, so local conversion is best-effort only.
        """
        if document_type in (DocumentType.PDF, DocumentType.SCANNED_PDF):
            return file_path
        return self.convert_to_pdf(file_path, document_type)

    def extract_text_from_superdocs(self, document) -> tuple[str, bool]:
        """Extract text from SuperDocs HTML output if available."""
        return "", False

    async def ingest_file(
        self,
        file: BinaryIO,
        original_filename: str,
        packet_id: str,
        display_order: int,
    ) -> "IngestionResult":
        from app.services.description_generator import generate_description

        mime_type, file_size = self.validate_file(file, original_filename)
        sha256 = self.calculate_sha256(file)

        original_path = self.save_original(file, sha256, original_filename)

        document_type = self.detect_document_type(mime_type, original_path)
        page_count = self.count_pages(original_path, document_type)

        # Convert DOCX/images to PDF for packet building
        processed_path = None
        if document_type in (DocumentType.DOCX, DocumentType.IMAGE):
            processed_path = self.convert_to_pdf(original_path, document_type)
            if processed_path is None:
                document = Document(
                    packet_id=packet_id,
                    display_order=display_order,
                    original_filename=original_filename,
                    mime_type=mime_type,
                    file_size=file_size,
                    sha256=sha256,
                    document_type=document_type,
                    page_count=page_count,
                    processing_status=ProcessingStatus.FAILED,
                    original_sha256=sha256,
                    processed_sha256=None,
                    is_searchable=False,
                    processing_error="Conversion to PDF failed (LibreOffice unavailable)",
                    last_completed_step="conversion_failed",
                )
                return IngestionResult(
                    document=document,
                    page_count=page_count,
                    extracted_text="",
                    is_searchable=False,
                    processed_file_path=str(original_path),
                )

        processed_sha256 = None
        if processed_path and processed_path != original_path:
            with open(processed_path, "rb") as f:
                processed_sha256 = self.calculate_sha256(f)

        extracted_text, is_searchable = self.extract_text(
            processed_path or original_path, document_type
        )
        desc_result = generate_description(
            text=extracted_text,
            filename=original_filename,
        )

        document = Document(
            packet_id=packet_id,
            display_order=display_order,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            sha256=sha256,
            document_type=document_type,
            page_count=page_count,
            processing_status=ProcessingStatus.COMPLETED,
            original_sha256=sha256,
            processed_sha256=processed_sha256,
            is_searchable=is_searchable,
            description=desc_result.description if desc_result else None,
            description_source=desc_result.source if desc_result else None,
            description_generated_at=utc_now() if desc_result else None,
            processed_at=utc_now(),
            completed_at=utc_now(),
            last_completed_step="ingestion_completed",
        )

        return IngestionResult(
            document=document,
            page_count=page_count,
            extracted_text=extracted_text,
            is_searchable=is_searchable,
            processed_file_path=str(processed_path or original_path),
        )
