"""Document ingestion: parse, persist, chunk, embed."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError, http_bad_request
from app.core.logging import get_logger
from app.models.document import Document, IngestSession
from app.schemas.document import DocumentSource, DocumentUploadResponse
from app.services.parsers.base import parse_file
from app.services.rag.ingestion import IngestionService

logger = get_logger(__name__)


class DocumentService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def ingest(
        self,
        *,
        resume: UploadFile,
        job_description: UploadFile | None,
        job_description_text: str | None,
        company_name: str,
        company_url: str | None,
    ) -> DocumentUploadResponse:
        if not company_name.strip():
            raise http_bad_request("company_name is required")

        jd_text = (job_description_text or "").strip()
        if job_description is None and not jd_text:
            raise http_bad_request("Provide job_description file or job_description_text")

        upload_root = Path(self.settings.upload_dir)
        upload_root.mkdir(parents=True, exist_ok=True)

        session = IngestSession(
            id=uuid.uuid4(),
            company_name=company_name.strip(),
            company_url=(company_url or None),
        )
        self.db.add(session)
        await self.db.flush()

        resume_path = await self._save_upload(resume, upload_root / str(session.id))
        try:
            resume_text = parse_file(resume_path, resume.filename)
        except AppError as exc:
            raise http_bad_request(exc.message) from exc

        resume_doc = Document(
            id=uuid.uuid4(),
            session_id=session.id,
            source=DocumentSource.RESUME.value,
            filename=resume.filename,
            content_text=resume_text,
        )
        self.db.add(resume_doc)

        jd_filename: str | None = None
        if job_description is not None and job_description.filename:
            jd_path = await self._save_upload(job_description, upload_root / str(session.id))
            try:
                jd_text = parse_file(jd_path, job_description.filename)
            except AppError as exc:
                raise http_bad_request(exc.message) from exc
            jd_filename = job_description.filename

        if not jd_text.strip():
            raise http_bad_request("Job description text is empty after parsing")

        jd_doc = Document(
            id=uuid.uuid4(),
            session_id=session.id,
            source=DocumentSource.JD.value,
            filename=jd_filename or "job_description.txt",
            content_text=jd_text.strip(),
        )
        self.db.add(jd_doc)
        await self.db.flush()

        ingestion = IngestionService(self.db)
        await ingestion.index_document(
            session_id=session.id,
            document_id=resume_doc.id,
            source=DocumentSource.RESUME.value,
            text=resume_text,
        )
        await ingestion.index_document(
            session_id=session.id,
            document_id=jd_doc.id,
            source=DocumentSource.JD.value,
            text=jd_text.strip(),
        )

        await self.db.flush()
        logger.info(
            "Ingested session=%s resume=%s jd=%s company=%s",
            session.id,
            resume_doc.id,
            jd_doc.id,
            session.company_name,
        )
        return DocumentUploadResponse(
            session_id=session.id,
            resume_document_id=resume_doc.id,
            jd_document_id=jd_doc.id,
            company_name=session.company_name,
        )

    async def _save_upload(self, upload: UploadFile, dest_dir: Path) -> Path:
        if not upload.filename:
            raise http_bad_request("Uploaded file is missing a filename")

        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        content = await upload.read()
        if len(content) > max_bytes:
            raise http_bad_request(
                f"File exceeds max upload size of {self.settings.max_upload_mb}MB"
            )
        if not content:
            raise http_bad_request(f"Uploaded file '{upload.filename}' is empty")

        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(upload.filename).name
        dest = dest_dir / f"{uuid.uuid4().hex}_{safe_name}"
        dest.write_bytes(content)
        logger.info("Saved upload %s (%s bytes)", dest.name, len(content))
        return dest
