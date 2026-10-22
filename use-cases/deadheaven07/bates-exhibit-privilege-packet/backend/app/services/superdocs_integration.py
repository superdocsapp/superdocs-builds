import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.domain.document import Document, ProcessingStatus
from app.services.superdocs_adapter import SuperDocsRESTAdapter
from app.services.superdocs_port import (
    DocumentUploadResult,
    ExportResult,
    JobStatus,
    PIICategory,
    PIIDetectionResult,
    PrivilegeAnalysisResult,
    ProposedChangeBatch,
    RedactionCandidate,
    SuperDocsPort,
)

logger = logging.getLogger(__name__)


class SuperDocsIntegrationService:
    def __init__(self, adapter: SuperDocsPort | None = None, settings: Settings | None = None):
        self.adapter = adapter or SuperDocsRESTAdapter()
        self.settings = settings or get_settings()

    async def upload_document_to_superdocs(
        self,
        session: AsyncSession,
        document: Document,
    ) -> DocumentUploadResult:
        if document.superdocs_session_id and document.superdocs_document_id:
            logger.info(f"Document {document.id} already uploaded to SuperDocs")
            return DocumentUploadResult(
                session_id=document.superdocs_session_id,
                document_id=document.superdocs_document_id,
                chunks_count=0,
                version_id="",
                page_setup={},
            )

        ext = (
            document.original_filename.split(".")[-1]
            if "." in document.original_filename
            else "pdf"
        )
        original_path = self.settings.originals_path / f"{document.sha256}.{ext}"

        if not original_path.exists():
            raise FileNotFoundError(f"Original file not found: {original_path}")

        with open(original_path, "rb") as f:
            file_bytes = f.read()

        result = await self.adapter.upload_document(
            file_bytes=file_bytes,
            filename=document.original_filename,
            return_html=True,
        )

        document.superdocs_session_id = result.session_id
        document.superdocs_document_id = result.document_id
        document.processing_status = ProcessingStatus.AI_ANALYSIS
        await session.commit()

        logger.info(f"Uploaded document {document.id} to SuperDocs session {result.session_id}")
        return result

    async def request_ai_analysis(
        self,
        session: AsyncSession,
        document: Document,
        instruction: str,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
    ) -> str:
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)

        job_id = await self.adapter.chat_async(
            message=instruction,
            session_id=document.superdocs_session_id,
            approval_mode=approval_mode,
            model_tier=model_tier,
        )

        logger.info(f"Started AI analysis job {job_id} for document {document.id}")
        return job_id

    async def poll_ai_job(self, job_id: str) -> JobStatus:
        return await self.adapter.poll_job(job_id)

    async def get_proposed_changes(self, job_id: str) -> ProposedChangeBatch:
        job_status = await self.adapter.poll_job(job_id)
        if job_status.status != "awaiting_approval":
            return ProposedChangeBatch(
                batch_id="",
                batch_total=0,
                changes=[],
                awaiting_kind=job_status.metadata.get("awaiting_kind", "approval")
                if job_status.metadata
                else "approval",
            )

        if job_status.metadata and "pending_changes" in job_status.metadata:
            content = job_status.metadata["pending_changes"]
            if isinstance(content, str):
                return self.adapter.parse_proposed_change_batch(content)
            elif isinstance(content, dict):
                import json

                return self.adapter.parse_proposed_change_batch(json.dumps(content))

        return ProposedChangeBatch(
            batch_id="",
            batch_total=0,
            changes=[],
            awaiting_kind="approval",
        )

    async def approve_changes(
        self,
        document: Document,
        job_id: str,
        approved: bool,
        changes: list[dict],
        feedback: str | None = None,
    ) -> JobStatus:
        if not document.superdocs_session_id:
            raise ValueError("Document not uploaded to SuperDocs")

        return await self.adapter.approve_changes(
            session_id=document.superdocs_session_id,
            job_id=job_id,
            approved=approved,
            changes=changes,
            feedback=feedback,
        )

    async def continue_job(
        self,
        document: Document,
        job_id: str,
        continue_job: bool,
    ) -> JobStatus:
        if not document.superdocs_session_id:
            raise ValueError("Document not uploaded to SuperDocs")

        return await self.adapter.continue_job(
            session_id=document.superdocs_session_id,
            job_id=job_id,
            continue_job=continue_job,
        )

    async def export_document(
        self,
        document: Document,
        format: str = "pdf",
        options: dict | None = None,
    ) -> ExportResult:
        if not document.superdocs_session_id:
            raise ValueError("Document not uploaded to SuperDocs")

        return await self.adapter.export_document(
            session_id=document.superdocs_session_id,
            format=format,
            options=options,
        )

    async def get_session_history(self, document: Document) -> dict:
        if not document.superdocs_session_id:
            raise ValueError("Document not uploaded to SuperDocs")

        return await self.adapter.get_session_history(document.superdocs_session_id)

    async def detect_pii(
        self,
        session: AsyncSession,
        document: Document,
        categories: list[PIICategory] | None = None,
    ) -> PIIDetectionResult:
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)

        result = await self.adapter.detect_pii(
            session_id=document.superdocs_session_id,
            document_id=document.superdocs_document_id,
            categories=categories,
        )

        logger.info(f"Detected {result.total_count} PII entities in document {document.id}")
        return result

    async def analyze_privilege(
        self,
        session: AsyncSession,
        document: Document,
    ) -> PrivilegeAnalysisResult:
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)

        result = await self.adapter.analyze_privilege(
            session_id=document.superdocs_session_id,
            document_id=document.superdocs_document_id,
        )

        logger.info(
            f"Privilege analysis for document {document.id}: "
            f"privileged={result.is_privileged}, category={result.category}"
        )
        return result

    async def create_redaction_candidates(
        self,
        session: AsyncSession,
        document: Document,
        pii_result: PIIDetectionResult,
        categories: list[PIICategory] | None = None,
    ) -> list[RedactionCandidate]:
        """Create redaction candidates from PII detection results,
        optionally filtered by category."""
        candidates = []
        for entity in pii_result.entities:
            if categories and entity.category not in categories:
                continue
            candidates.append(
                RedactionCandidate(
                    entity=entity,
                    approved=False,
                )
            )

        logger.info(f"Created {len(candidates)} redaction candidates for document {document.id}")
        return candidates

    async def apply_redactions(
        self,
        session: AsyncSession,
        document: Document,
        candidates: list[RedactionCandidate],
    ) -> JobStatus:
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)

        result = await self.adapter.apply_redactions(
            session_id=document.superdocs_session_id,
            document_id=document.superdocs_document_id,
            candidates=candidates,
        )

        logger.info(f"Applied redactions to document {document.id}, job_id={result.job_id}")
        return result

    async def get_redaction_preview(
        self,
        session: AsyncSession,
        document: Document,
        candidates: list[RedactionCandidate],
    ) -> ExportResult:
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)

        result = await self.adapter.get_redaction_preview(
            session_id=document.superdocs_session_id,
            document_id=document.superdocs_document_id,
            candidates=candidates,
        )

        logger.info(f"Generated redaction preview for document {document.id}")
        return result

    async def close(self):
        await self.adapter.close()


async def get_superdocs_service() -> SuperDocsIntegrationService:
    return SuperDocsIntegrationService()
