import base64
import hashlib
import re
from pathlib import PurePath
from uuid import UUID, uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from series_bible.infrastructure.database import AuditEvent, Document
from series_bible.infrastructure.superdocs_service import SuperDocsService, UploadDocumentRequest

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,254}$")
ALLOWED_SUFFIXES = {".docx", ".pdf", ".txt", ".rtf", ".md", ".html", ".tex"}

class IngestionService:
    def __init__(self, session: AsyncSession, superdocs: SuperDocsService, max_bytes: int) -> None:
        self.session, self.superdocs, self.max_bytes = session, superdocs, max_bytes

    async def ingest(self, series_id: UUID, filename: str, content: bytes, actor: str) -> Document:
        safe = PurePath(filename).name
        if safe != filename or not SAFE_NAME.fullmatch(safe) or PurePath(safe).suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError("invalid or unsupported filename")
        if not content or len(content) > self.max_bytes:
            raise ValueError("file is empty or exceeds upload limit")
        digest = hashlib.sha256(content).hexdigest()
        existing = await self.session.scalar(select(Document).where(Document.series_id == series_id, Document.content_hash == digest))
        if existing:
            return existing
        session_id = f"series-{series_id}-document-{uuid4()}"
        result = await self.superdocs.upload_document(UploadDocumentRequest(filename=safe, file_base64=base64.b64encode(content).decode(), session_id=session_id, return_html=False))
        document = Document(series_id=series_id, filename=safe, content_hash=digest, superdocs_session_id=session_id, superdocs_document_id=result.get("document_id"), status="IMPORTED")
        self.session.add(document)
        await self.session.flush()
        self.session.add(AuditEvent(actor=actor, entity="document", entity_id=str(document.id), operation="DOCUMENT_UPLOADED", metadata_json={"filename": safe, "content_hash": digest}))
        return document
