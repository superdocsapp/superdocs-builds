import base64
import hashlib
import re
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from series_bible.application.embeddings import HashEmbeddingProvider
from series_bible.application.episodic import record_story_event
from series_bible.infrastructure.database import AuditEvent, Chapter, Document, DocumentChunk
from series_bible.infrastructure.superdocs_service import SuperDocsService, UploadDocumentRequest

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,254}$")
ALLOWED_SUFFIXES = {".docx", ".pdf", ".txt", ".rtf", ".md", ".html", ".tex"}

class IngestionService:
    def __init__(self, session: AsyncSession, superdocs: SuperDocsService, max_bytes: int) -> None:
        self.session, self.superdocs, self.max_bytes = session, superdocs, max_bytes
        self.embeddings = HashEmbeddingProvider()

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
        result = await self.superdocs.upload_document(UploadDocumentRequest(filename=safe, file_base64=base64.b64encode(content).decode(), session_id=session_id, return_html=True))
        document = Document(series_id=series_id, filename=safe, content_hash=digest, superdocs_session_id=session_id, superdocs_document_id=result.get("document_id"), status="IMPORTED")
        self.session.add(document)
        await self.session.flush()
        html = self._find_html(result)
        text = self._html_to_text(html) if html else self._decode_text(content, PurePath(safe).suffix.lower())
        if not text:
            raise ValueError("SuperDocs imported the document but returned no extractable text")
        if text:
            chapter = Chapter(
                document_id=document.id,
                number=self._chapter_number(safe),
                title=text.splitlines()[0].lstrip("# ").strip() or safe,
            )
            self.session.add(chapter)
            await self.session.flush()
            for paragraph, passage in enumerate(self._paragraphs(text), start=1):
                chunk_hash = hashlib.sha256(passage.encode()).hexdigest()
                self.session.add(
                    DocumentChunk(
                        document_id=document.id,
                        chapter_id=chapter.id,
                        source_chunk_id=f"{digest[:12]}-{paragraph}",
                        section=chapter.title,
                        paragraph=paragraph,
                        text=passage,
                        content_hash=chunk_hash,
                        embedding=self.embeddings.embed(passage),
                    )
                )
        self.session.add(AuditEvent(actor=actor, entity="document", entity_id=str(document.id), operation="DOCUMENT_UPLOADED", metadata_json={"filename": safe, "content_hash": digest}))
        await record_story_event(
            self.session,
            series_id=series_id,
            event_type="DOCUMENT_UPLOADED",
            description=f"{safe} was uploaded and imported for analysis.",
            actor=actor,
            document_id=document.id,
            source=safe,
        )
        return document

    @classmethod
    def _find_html(cls, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("document_html", "html", "content_html"):
                candidate = value.get(key)
                if isinstance(candidate, str) and "<" in candidate:
                    return candidate
            for candidate in value.values():
                if found := cls._find_html(candidate):
                    return found
        if isinstance(value, list):
            for candidate in value:
                if found := cls._find_html(candidate):
                    return found
        return None

    @staticmethod
    def _html_to_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style"]):
            element.decompose()
        blocks = []
        for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
            text = element.get_text(" ", strip=True)
            if text:
                blocks.append(text)
        return "\n\n".join(blocks) or soup.get_text("\n", strip=True)

    @staticmethod
    def _decode_text(content: bytes, suffix: str) -> str | None:
        if suffix not in {".txt", ".md", ".html", ".tex"}:
            return None
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("text documents must use UTF-8") from error

    @staticmethod
    def _paragraphs(text: str) -> list[str]:
        return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]

    @staticmethod
    def _chapter_number(filename: str) -> int:
        match = re.search(r"chapter[-_ ]?(\d+)", filename, re.IGNORECASE)
        return int(match.group(1)) if match else 1
