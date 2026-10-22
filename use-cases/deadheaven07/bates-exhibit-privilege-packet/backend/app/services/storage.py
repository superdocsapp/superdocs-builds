from pathlib import Path

from app.config import get_settings
from app.domain.document import Document, DocumentType
from sqlalchemy import select

settings = get_settings()


def original_path_for(document: Document) -> Path:
    ext = Path(document.original_filename).suffix
    return settings.originals_path / f"{document.sha256}{ext}"


def redacted_pdf_path_for(document: Document) -> Path:
    return settings.working_path / f"{document.sha256}_redacted.pdf"


def processed_pdf_path_for(document: Document) -> Path | None:
    converted = settings.processed_path / f"{document.sha256}.pdf"
    if converted.exists():
        return converted
    searchable = settings.processed_path / f"{document.sha256}_searchable.pdf"
    if searchable.exists():
        return searchable
    return None


def base_pdf_source(document: Document) -> Path | None:
    processed = processed_pdf_path_for(document)
    if processed is not None:
        return processed
    if document.document_type in (DocumentType.PDF, DocumentType.SCANNED_PDF):
        original = original_path_for(document)
        if original.exists():
            return original
    return None


def resolve_pdf_source(document: Document) -> Path | None:
    redacted = redacted_pdf_path_for(document)
    if redacted.exists():
        return redacted
    return base_pdf_source(document)


async def cleanup_unreferenced_original(session, sha256: str, filename: str) -> bool:
    """Remove a saved original file only if no document references it.

    Used when ingestion fails after the original has been written to disk but
    before a document row exists (e.g. corrupt PDF detected by count_pages).
    """
    from app.domain.document import Document as DocumentModel

    result = await session.execute(
        select(DocumentModel.id).where(DocumentModel.sha256 == sha256)
    )
    if result.first() is not None:
        return False

    ext = Path(filename).suffix
    path = settings.originals_path / f"{sha256}{ext}"
    if path.exists():
        path.unlink()
        return True
    return False


async def cleanup_document_files(session, document: Document) -> list[str]:
    """Remove storage files for a document, skipping files still referenced by
    another document that shares the same sha256 (cross-packet dedup)."""
    from app.domain.document import Document as DocumentModel

    result = await session.execute(
        select(DocumentModel.id).where(
            DocumentModel.sha256 == document.sha256,
            DocumentModel.id != document.id,
        )
    )
    if result.first() is not None:
        return []

    removed = []

    for path in [
        redacted_pdf_path_for(document),
        settings.working_path / f"{document.sha256}_stamped.pdf",
    ]:
        if path.exists():
            path.unlink()
            removed.append(str(path))

    processed = processed_pdf_path_for(document)
    if processed is not None:
        processed.unlink(missing_ok=True)
        removed.append(str(processed))

    original = original_path_for(document)
    if original.exists():
        original.unlink()
        removed.append(str(original))

    return removed