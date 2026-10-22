import hashlib
import logging
from pathlib import Path

import fitz
import pdfplumber
from PIL import Image
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.document import Document, ProcessingStatus
from app.domain.page import Page
from app.services.ingestion import IngestionService
from app.time import utc_now

settings = get_settings()
logger = logging.getLogger(__name__)


def calculate_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


async def process_document(document_id: str):
    async with async_session_maker() as session:
        document = await session.get(Document, document_id)
        if not document:
            return

        document.processing_status = ProcessingStatus.PROCESSING
        await session.commit()

        try:
            ext = Path(document.original_filename).suffix
            original_path = settings.originals_path / f"{document.sha256}{ext}"

            if not original_path.exists():
                document.processing_status = ProcessingStatus.FAILED
                document.processing_error = "Original file not found"
                await session.commit()
                return

            session.add(AuditEvent(
                packet_id=document.packet_id,
                document_id=document.id,
                event_type=AuditEventType.PROCESSING_STARTED,
                user_id="system",
                event_metadata={"filename": document.original_filename, "retry": document.retry_count},
            ))

            document.processing_status = ProcessingStatus.OCR
            document.last_completed_step = "ocr"
            await session.commit()

            page_count = 0
            extracted_text = ""
            is_searchable = False

            if document.document_type.value in ("pdf", "scanned_pdf"):
                doc = fitz.open(original_path)
                page_count = doc.page_count
                doc.close()

                if document.document_type.value == "scanned_pdf":
                    try:
                        import pytesseract
                        from pdf2image import convert_from_path

                        images = convert_from_path(original_path, dpi=300)
                        text_parts = []
                        for i, image in enumerate(images):
                            text = pytesseract.image_to_string(image, lang=settings.tesseract_lang)
                            if text.strip():
                                text_parts.append(f"[Page {i+1}]\n{text}")
                        extracted_text = "\n\n".join(text_parts)
                        is_searchable = len(extracted_text.strip()) > 0

                        output_path = settings.processed_path / f"{original_path.stem}_searchable.pdf"
                        doc = fitz.open(original_path)
                        for page_num in range(len(doc)):
                            page = doc[page_num]
                            pix = page.get_pixmap(dpi=300)
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            pdf_bytes = pytesseract.image_to_pdf_or_hocr(img, extension="pdf")
                            pdf_page = fitz.open("pdf", pdf_bytes)
                            page.insert_pdf(pdf_page)
                        doc.save(output_path)
                        doc.close()

                        document.processed_sha256 = calculate_sha256(output_path)
                    except Exception as e:
                        logger.warning(f"OCR unavailable for scanned PDF {document.id}: {e}")
                        extracted_text = ""
                        is_searchable = False
                else:
                    with pdfplumber.open(original_path) as pdf:
                        text_parts = []
                        for page in pdf.pages:
                            text = page.extract_text()
                            if text:
                                text_parts.append(text)
                        extracted_text = "\n\n".join(text_parts)
                        is_searchable = len(extracted_text.strip()) > 0

            elif document.document_type.value == "docx":
                from docx import Document as DocxDocument
                doc = DocxDocument(original_path)
                text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
                extracted_text = "\n\n".join(text_parts)
                is_searchable = len(extracted_text.strip()) > 0

                converted = IngestionService().convert_to_pdf(original_path, document.document_type)
                if converted is None:
                    raise RuntimeError("LibreOffice unavailable: cannot convert DOCX to PDF")
                with fitz.open(converted) as converted_doc:
                    page_count = converted_doc.page_count
                document.processed_sha256 = calculate_sha256(converted)

            elif document.document_type.value == "image":
                try:
                    import pytesseract
                    image = Image.open(original_path)
                    extracted_text = pytesseract.image_to_string(image, lang=settings.tesseract_lang)
                except Exception as e:
                    logger.warning(f"OCR unavailable for image {document.id}: {e}")
                    extracted_text = ""
                is_searchable = len(extracted_text.strip()) > 0
                page_count = 1

                converted = IngestionService().convert_to_pdf(original_path, document.document_type)
                if converted is not None:
                    document.processed_sha256 = calculate_sha256(converted)

            document.page_count = page_count
            document.is_searchable = is_searchable
            document.processing_status = ProcessingStatus.COMPLETED
            document.processing_error = None
            document.retry_count = 0
            document.processed_at = utc_now()
            document.completed_at = utc_now()
            document.last_completed_step = "completed"

            result = await session.execute(
                select(Page).where(Page.document_id == document.id).order_by(Page.page_number)
            )
            existing_pages = result.scalars().all()

            if len(existing_pages) != page_count:
                for page in existing_pages:
                    await session.delete(page)

                for page_num in range(1, page_count + 1):
                    page = Page(
                        document_id=document.id,
                        page_number=page_num,
                        has_text=is_searchable,
                        extracted_text=extracted_text[:1000000] if extracted_text else None,
                    )
                    session.add(page)

            session.add(AuditEvent(
                packet_id=document.packet_id,
                document_id=document.id,
                event_type=AuditEventType.PROCESSING_COMPLETED,
                user_id="system",
                event_metadata={
                    "filename": document.original_filename,
                    "page_count": page_count,
                    "is_searchable": is_searchable,
                },
            ))
            await session.commit()

        except Exception as e:
            document.processing_status = ProcessingStatus.FAILED
            document.processing_error = str(e)
            document.retry_count += 1
            session.add(AuditEvent(
                packet_id=document.packet_id,
                document_id=document.id,
                event_type=AuditEventType.PROCESSING_FAILED,
                user_id="system",
                event_metadata={"filename": document.original_filename, "error": str(e)},
            ))
            await session.commit()


async def process_packet_documents(packet_id: str):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Document).where(
                Document.packet_id == packet_id,
                Document.processing_status.in_([ProcessingStatus.QUEUED, ProcessingStatus.FAILED])
            )
        )
        documents = result.scalars().all()

    for doc in documents:
        await process_document(str(doc.id))