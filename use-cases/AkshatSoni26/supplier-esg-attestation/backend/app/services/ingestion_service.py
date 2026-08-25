import io
import os
import time
import uuid
import zipfile
import docx
import pypdf
import pypdf.errors
from typing import BinaryIO
from app.core.config import settings
from app.core.logger import get_logger
from app.services.superdocs_service import SuperDocsClientService

logger = get_logger("ingestion_service")


class IngestionService:
    """Service to handle multi-format response intake (PDF, DOCX, TXT, Markdown, JSON)."""

    def __init__(self, superdocs_client: SuperDocsClientService | None = None):
        self.superdocs = superdocs_client or SuperDocsClientService()

    def extract_text_from_stream(self, filename: str, file_bytes: bytes) -> str:
        """Extract plain text from multiple document formats safely."""
        ext = os.path.splitext(filename)[1].lower()

        if ext in [".txt", ".md", ".json"]:
            return file_bytes.decode("utf-8", errors="ignore")

        if ext == ".pdf":
            try:
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                text_parts = []
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text_parts.append(extracted)
                return "\n".join(text_parts) if text_parts else file_bytes.decode("utf-8", errors="ignore")
            except (
                ValueError, TypeError, KeyError, OSError, io.UnsupportedOperation,
                pypdf.errors.PdfStreamError, pypdf.errors.EmptyFileError,
                pypdf.errors.PdfReadError,
            ) as err:
                logger.warning(f"PDF parse failed for '{filename}' ({type(err).__name__}: {err}); falling back to raw bytes decode.")
                return file_bytes.decode("utf-8", errors="ignore")

        if ext in [".docx", ".doc"]:
            try:
                doc = docx.Document(io.BytesIO(file_bytes))
                return "\n".join([p.text for p in doc.paragraphs if p.text])
            except (
                ValueError, TypeError, KeyError, OSError, io.UnsupportedOperation,
                zipfile.BadZipFile,
            ) as err:
                logger.warning(f"DOCX parse failed for '{filename}' ({type(err).__name__}: {err}); falling back to raw bytes decode.")
                return file_bytes.decode("utf-8", errors="ignore")

        return file_bytes.decode("utf-8", errors="ignore")

    async def process_incoming_response(
        self,
        attestation_id: str,
        filename: str,
        file_bytes: bytes
    ) -> tuple[str, str, str]:
        """
        Saves uploaded response file locally and registers it with SuperDocs.
        Returns (saved_local_path, extracted_text, superdocs_doc_id).
        """
        t_start = time.monotonic()
        ext = os.path.splitext(filename)[1].lower()
        unique_name = f"{attestation_id}_{uuid.uuid4().hex[:8]}{ext}"
        local_path = os.path.join(settings.UPLOADS_DIR, unique_name)

        if len(file_bytes) == 0:
            logger.warning(f"Empty file received: '{filename}' — skipping extraction.")

        with open(local_path, "wb") as f:
            f.write(file_bytes)

        extracted_text = self.extract_text_from_stream(filename, file_bytes)

        # Upload to SuperDocs for provenance & editing
        sd_upload = await self.superdocs.upload_document(filename, file_bytes)

        elapsed = time.monotonic() - t_start
        logger.info(
            f"Ingestion complete | attestation={attestation_id} file='{filename}' "
            f"size={len(file_bytes)}B chars_extracted={len(extracted_text)} "
            f"superdocs_id={sd_upload.document_id} elapsed={elapsed:.3f}s"
        )
        return local_path, extracted_text, sd_upload.document_id
