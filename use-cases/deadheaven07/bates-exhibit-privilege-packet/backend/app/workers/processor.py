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
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.page import Page
from app.services.description_generator import generate_description
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

            session.add(
                AuditEvent(
                    packet_id=document.packet_id,
                    document_id=document.id,
                    event_type=AuditEventType.PROCESSING_STARTED,
                    user_id="system",
                    event_metadata={
                        "filename": document.original_filename,
                        "retry": document.retry_count,
                    },
                )
            )

            document.processing_status = ProcessingStatus.OCR
            document.last_completed_step = "ocr"
            await session.commit()

            page_count = 0
            extracted_text = ""
            per_page_texts: list[str] = []
            is_searchable = False

            if document.document_type.value in ("pdf", "scanned_pdf"):
                doc = fitz.open(original_path)
                page_count = doc.page_count
                doc.close()

                with pdfplumber.open(original_path) as pdf:
                    text_parts = []
                    per_page_texts = []
                    for page in pdf.pages:
                        text = page.extract_text() or ""
                        text_parts.append(text)
                        per_page_texts.append(text)
                    extracted_text = "\n\n".join(t for t in text_parts if t.strip())
                    is_searchable = len(extracted_text.strip()) > 0

                # If no native text in PDF, attempt OCR (for scanned or image-based PDFs)
                if not is_searchable or document.document_type.value == "scanned_pdf":
                    try:
                        import pytesseract

                        images = []
                        try:
                            doc = fitz.open(original_path)
                            for p in doc:
                                pix = p.get_pixmap(dpi=150)
                                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                images.append(img)
                            doc.close()
                        except Exception:
                            from pdf2image import convert_from_path

                            images = convert_from_path(original_path, dpi=150)

                        ocr_text_parts = []
                        ocr_per_page_texts = []
                        for i, image in enumerate(images):
                            text = pytesseract.image_to_string(
                                image, lang=settings.tesseract_lang
                            ).strip()
                            if text:
                                ocr_text_parts.append(f"[Page {i + 1}]\n{text}")
                                ocr_per_page_texts.append(text)
                            else:
                                ocr_per_page_texts.append("")

                        ocr_extracted = "\n\n".join(ocr_text_parts)
                        if ocr_extracted.strip():
                            extracted_text = ocr_extracted
                            per_page_texts = ocr_per_page_texts
                            is_searchable = True
                            document.document_type = DocumentType.SCANNED_PDF

                            try:
                                output_path = (
                                    settings.processed_path / f"{original_path.stem}_searchable.pdf"
                                )
                                searchable_doc = fitz.open()
                                for img in images:
                                    pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                                        img, extension="pdf"
                                    )
                                    ocr_page_doc = fitz.open("pdf", pdf_bytes)
                                    searchable_doc.insert_pdf(ocr_page_doc)
                                    ocr_page_doc.close()
                                searchable_doc.save(output_path)
                                searchable_doc.close()
                                document.processed_sha256 = calculate_sha256(output_path)
                            except Exception as ocr_err:
                                logger.info(
                                    f"Searchable PDF layer generation skipped for {document.id}: {ocr_err}"
                                )
                    except Exception as e:
                        logger.warning(f"OCR unavailable for scanned PDF {document.id}: {e}")

            elif document.document_type.value == "docx":
                from docx import Document as DocxDocument

                doc = DocxDocument(original_path)
                text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
                extracted_text = "\n\n".join(text_parts)
                per_page_texts = [extracted_text]
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
                    extracted_text = pytesseract.image_to_string(
                        image, lang=settings.tesseract_lang
                    ).strip()
                except Exception as e:
                    logger.warning(f"OCR unavailable for image {document.id}: {e}")
                    extracted_text = ""
                per_page_texts = [extracted_text] if extracted_text else [""]
                is_searchable = len(extracted_text.strip()) > 0
                page_count = 1

                converted = IngestionService().convert_to_pdf(original_path, document.document_type)
                if converted is not None:
                    document.processed_sha256 = calculate_sha256(converted)

            desc_result = generate_description(
                text=extracted_text,
                filename=document.original_filename,
            )
            if desc_result.description and not document.description:
                document.description = desc_result.description
                document.description_source = desc_result.source
                document.description_generated_at = utc_now()

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
                for p in existing_pages:
                    await session.delete(p)
                existing_pages = []

            if not existing_pages:
                for page_num in range(1, page_count + 1):
                    page_idx = page_num - 1
                    page_text = (
                        per_page_texts[page_idx]
                        if page_idx < len(per_page_texts) and per_page_texts[page_idx]
                        else (extracted_text if page_count == 1 else "")
                    )
                    page = Page(
                        document_id=document.id,
                        page_number=page_num,
                        has_text=is_searchable and bool(page_text and page_text.strip()),
                        extracted_text=page_text[:1000000] if page_text else None,
                    )
                    session.add(page)
            else:
                for p in existing_pages:
                    page_idx = p.page_number - 1
                    page_text = (
                        per_page_texts[page_idx]
                        if page_idx < len(per_page_texts) and per_page_texts[page_idx]
                        else (extracted_text if page_count == 1 else "")
                    )
                    p.has_text = is_searchable and bool(page_text and page_text.strip())
                    p.extracted_text = page_text[:1000000] if page_text else None

            session.add(
                AuditEvent(
                    packet_id=document.packet_id,
                    document_id=document.id,
                    event_type=AuditEventType.PROCESSING_COMPLETED,
                    user_id="system",
                    event_metadata={
                        "filename": document.original_filename,
                        "page_count": page_count,
                        "is_searchable": is_searchable,
                    },
                )
            )
            await session.commit()

        except Exception as e:
            document.processing_status = ProcessingStatus.FAILED
            document.processing_error = str(e)
            document.retry_count += 1
            session.add(
                AuditEvent(
                    packet_id=document.packet_id,
                    document_id=document.id,
                    event_type=AuditEventType.PROCESSING_FAILED,
                    user_id="system",
                    event_metadata={"filename": document.original_filename, "error": str(e)},
                )
            )
            await session.commit()


async def process_packet_documents(packet_id: str):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Document).where(
                Document.packet_id == packet_id,
                Document.processing_status.in_([ProcessingStatus.QUEUED, ProcessingStatus.FAILED]),
            )
        )
        documents = result.scalars().all()

    for doc in documents:
        await process_document(str(doc.id))
