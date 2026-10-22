"""SuperDocs integration service.

PRIMARY INTELLIGENCE LAYER (see ARCHITECTURE.md):

- PII detection, privilege analysis, and redaction proposals are driven
  through the SuperDocs async chat API with `approval_mode: "ask_every_time"`.
  Every suggestion surfaces as a native SuperDocs `pending_change` that a
  human reviewer must approve or reject (one-by-one or in batches) before any
  byte is modified.
- After human approval, redactions are applied as true byte-scrubbing
  (PyMuPDF) by the application layer, and the scrubbed artifact is re-imported
  into SuperDocs so the final packet is a native SuperDocs document.

LEGACY/FALLBACK ENDPOINTS:
- `detect_pii`, `analyze_privilege`, `apply_redactions`,
  `get_redaction_preview` are the legacy REST endpoints. They remain wired
  for backward compatibility and as a platform-level fallback, but the
  primary path is the chat proposal flow above. The local regex engine
  (`app.services.local_engine`) is the offline fallback used only when the
  platform is unreachable.
"""

import asyncio
import json
import logging
from pathlib import Path

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
    PIIEntity,
    PrivilegeAnalysisResult,
    PrivilegeCategory,
    PrivilegeSuggestion,
    ProposedChange,
    ProposedChangeBatch,
    RedactionCandidate,
    SuperDocsPort,
)

logger = logging.getLogger(__name__)

PII_DETECTION_PROMPT = (
    "Analyze the uploaded document for personally identifiable information "
    "(PII). Identify every instance of: social security numbers, email "
    "addresses, phone numbers, account numbers, names, addresses, medical "
    "terms, dates of birth, credit card numbers, driver's license numbers, "
    "and passport numbers. For each instance, propose a redaction as a "
    "pending change. Do not propose redactions for invoice reference numbers, "
    "statement codes, dates, or page markers."
)

PRIVILEGE_ANALYSIS_PROMPT = (
    "Analyze the uploaded document for attorney-client privilege, work "
    "product, joint defense, or common interest privilege. If privileged "
    "language is present, propose a single pending change marking the "
    "document as privileged with the privilege category and the exact "
    "language that triggers the finding."
)


class ProposalError(Exception):
    """A SuperDocs chat proposal job failed or exceeded its wait budget."""

    def __init__(self, message: str, job_id: str = "", status: str = ""):
        super().__init__(message)
        self.job_id = job_id
        self.status = status


class SuperDocsIntegrationService:
    def __init__(self, adapter: SuperDocsPort | None = None, settings: Settings | None = None):
        self.adapter = adapter or SuperDocsRESTAdapter()
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Upload / session management                                        #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # PRIMARY: async chat proposal flow (approval_mode: ask_every_time)  #
    # ------------------------------------------------------------------ #

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
        if not document.superdocs_session_id:
            raise ValueError("Failed to upload document to SuperDocs")

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
                return self.adapter.parse_proposed_change_batch(json.dumps(content))

        return ProposedChangeBatch(
            batch_id="",
            batch_total=0,
            changes=[],
            awaiting_kind="approval",
        )

    async def propose_analysis(
        self,
        session: AsyncSession,
        document: Document,
        instruction: str,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
        max_wait: float = 300.0,
        poll_interval: float = 2.0,
    ) -> ProposedChangeBatch:
        """Run a chat job in ask_every_time mode and wait for the platform to
        return `awaiting_approval` with a batch of native pending changes."""
        job_id = await self.request_ai_analysis(
            session, document, instruction, approval_mode=approval_mode, model_tier=model_tier
        )
        if not job_id:
            raise ProposalError("SuperDocs chat job returned no job_id")

        deadline = asyncio.get_event_loop().time() + max_wait
        while True:
            status = await self.adapter.poll_job(job_id)
            if status.status == "awaiting_approval":
                batch = await self.get_proposed_changes(job_id)
                logger.info(
                    f"Proposal job {job_id} for document {document.id} returned "
                    f"{len(batch.changes)} pending changes"
                )
                return batch
            if status.status in ("failed", "cancelled", "error"):
                raise ProposalError(
                    f"SuperDocs proposal job failed: {status.error or status.status}",
                    job_id=job_id,
                    status=status.status,
                )
            if asyncio.get_event_loop().time() > deadline:
                raise ProposalError(
                    f"SuperDocs proposal job {job_id} timed out after {max_wait}s "
                    f"(still {status.status})",
                    job_id=job_id,
                    status=status.status,
                )
            await asyncio.sleep(poll_interval)

    async def propose_pii_detection(
        self,
        session: AsyncSession,
        document: Document,
        categories: list[PIICategory] | None = None,
        max_wait: float = 300.0,
    ) -> PIIDetectionResult:
        """PRIMARY PII detection: chat API with ask_every_time.

        Every detected PII instance is a native pending_change that the
        reviewer must approve before any redaction is applied.
        """
        instruction = PII_DETECTION_PROMPT
        if categories:
            instruction += (
                " Only propose redactions in these categories: "
                + ", ".join(c.value for c in categories)
                + "."
            )

        batch = await self.propose_analysis(session, document, instruction, max_wait=max_wait)

        entities: list[PIIEntity] = []
        for change in batch.changes:
            entity = _pii_entity_from_change(change)
            if entity is None:
                logger.warning(
                    f"Pending change {change.change_id} is not a structured PII proposal "
                    f"(operation={change.operation}); skipped. Platform quirk SD-PROSE-01"
                )
                continue
            if categories and entity.category not in categories:
                continue
            entities.append(entity)

        logger.info(
            f"Detected {len(entities)} PII entities in document {document.id} "
            f"via chat proposal flow (batch {batch.batch_id})"
        )
        return PIIDetectionResult(
            entities=entities,
            total_count=len(entities),
            session_id=document.superdocs_session_id or "",
            document_id=document.superdocs_document_id or str(document.id),
            batch_id=batch.batch_id,
            job_id=batch.continue_prompt.get("job_id", "") if batch.continue_prompt else "",
        )

    async def propose_privilege_analysis(
        self,
        session: AsyncSession,
        document: Document,
        max_wait: float = 300.0,
    ) -> PrivilegeSuggestion:
        """PRIMARY privilege analysis: chat API with ask_every_time."""
        batch = await self.propose_analysis(
            session, document, PRIVILEGE_ANALYSIS_PROMPT, max_wait=max_wait
        )

        for change in batch.changes:
            suggestion = _privilege_suggestion_from_change(change)
            if suggestion is not None:
                suggestion.batch_id = batch.batch_id
                suggestion.job_id = (
                    batch.continue_prompt.get("job_id", "") if batch.continue_prompt else ""
                )
                logger.info(
                    f"Privilege suggestion for document {document.id}: "
                    f"privileged={suggestion.is_privileged} category={suggestion.category}"
                )
                return suggestion

        logger.info(
            f"No structured privilege proposal for document {document.id} "
            f"(batch {batch.batch_id}); treating as not privileged by default"
        )
        return PrivilegeSuggestion(
            is_privileged=False,
            category=None,
            reason="No privilege proposal surfaced by SuperDocs chat flow",
            confidence=0.0,
            key_phrases=[],
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

    # ------------------------------------------------------------------ #
    # Post-approval: re-import scrubbed artifact into SuperDocs           #
    # ------------------------------------------------------------------ #

    async def scrub_and_reimport(
        self,
        session: AsyncSession,
        document: Document,
        local_pdf_path,
    ) -> ExportResult:
        """Upload the locally byte-scrubbed PDF into the document's SuperDocs
        session and export it as a native SuperDocs document.

        Raises `SuperDocsUnavailableError` when the platform is unreachable;
        callers must fall back to the local artifact.
        """
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)
        if not document.superdocs_session_id:
            raise ValueError("Failed to upload document to SuperDocs")

        with open(local_pdf_path, "rb") as f:
            file_bytes = f.read()

        stem = Path(local_pdf_path).stem
        upload = await self.adapter.upload_document(
            file_bytes=file_bytes,
            filename=f"{stem}_superdocs.pdf",
            session_id=document.superdocs_session_id,
            return_html=False,
        )
        return await self.adapter.export_document(
            session_id=upload.session_id,
            format="pdf",
            options={"filename": f"{stem}_superdocs.pdf"},
        )

    async def export_artifact(self, file_bytes: bytes, filename: str) -> ExportResult:
        """Upload an assembled artifact (e.g. the final packet PDF) into a
        fresh SuperDocs session and export it as a native SuperDocs document."""
        upload = await self.adapter.upload_document(
            file_bytes=file_bytes,
            filename=filename,
            return_html=False,
        )
        return await self.adapter.export_document(
            session_id=upload.session_id,
            format="pdf",
            options={"filename": filename},
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

    # ------------------------------------------------------------------ #
    # LEGACY REST endpoints (platform fallback, not the primary path)     #
    # ------------------------------------------------------------------ #

    async def detect_pii(
        self,
        session: AsyncSession,
        document: Document,
        categories: list[PIICategory] | None = None,
    ) -> PIIDetectionResult:
        """Legacy REST detection endpoint. Prefer `propose_pii_detection`
        (chat + ask_every_time). Kept as a platform-level fallback."""
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)
        if not document.superdocs_session_id or not document.superdocs_document_id:
            raise ValueError("Failed to upload document to SuperDocs")

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
        """Legacy REST privilege endpoint. Prefer
        `propose_privilege_analysis` (chat + ask_every_time)."""
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)
        if not document.superdocs_session_id or not document.superdocs_document_id:
            raise ValueError("Failed to upload document to SuperDocs")

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
        """Legacy REST apply endpoint. The primary path applies true
        byte-scrubbing locally after approval and re-imports via
        `scrub_and_reimport`."""
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)
        if not document.superdocs_session_id or not document.superdocs_document_id:
            raise ValueError("Failed to upload document to SuperDocs")

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
        if not document.superdocs_session_id or not document.superdocs_document_id:
            raise ValueError("Failed to upload document to SuperDocs")

        result = await self.adapter.get_redaction_preview(
            session_id=document.superdocs_session_id,
            document_id=document.superdocs_document_id,
            candidates=candidates,
        )

        logger.info(f"Generated redaction preview for document {document.id}")
        return result

    async def close(self):
        await self.adapter.close()


# ---------------------------------------------------------------------- #
# Structured pending-change envelope parsing                              #
#                                                                         #
# Platform quirk SD-PROSE-01: SuperDocs returns proposal rationale as     #
# free-form prose in `ai_explanation`. For machine-verifiable redaction   #
# candidates we instruct the model to embed a JSON envelope there.        #
# ---------------------------------------------------------------------- #


def _parse_change_envelope(change: ProposedChange) -> dict | None:
    try:
        return json.loads(change.ai_explanation or "{}")
    except json.JSONDecodeError:
        return None


def _pii_entity_from_change(change: ProposedChange) -> PIIEntity | None:
    envelope = _parse_change_envelope(change)
    if envelope is None:
        return None
    if envelope.get("kind") not in ("pii", "redaction") and change.operation != "redact_pii":
        return None

    category_value = envelope.get("category")
    if category_value not in {c.value for c in PIICategory}:
        return None
    text = envelope.get("text")
    if not text:
        return None

    try:
        page_number = int(envelope.get("page_number", 1))
    except (TypeError, ValueError):
        page_number = 1

    return PIIEntity(
        category=PIICategory(category_value),
        text=text,
        page_number=page_number,
        start_offset=int(envelope.get("start_offset", 0)),
        end_offset=int(envelope.get("end_offset", len(text))),
        confidence=float(envelope.get("confidence", 0.9)),
        context_before=envelope.get("context_before", ""),
        context_after=envelope.get("context_after", ""),
        change_id=change.change_id,
    )


def _privilege_suggestion_from_change(change: ProposedChange) -> PrivilegeSuggestion | None:
    envelope = _parse_change_envelope(change)
    if envelope is None:
        return None
    if envelope.get("kind") not in ("privilege",) and change.operation != "mark_privilege":
        return None

    category_value = envelope.get("category")
    category = None
    if category_value in {c.value for c in PrivilegeCategory}:
        category = PrivilegeCategory(category_value)

    return PrivilegeSuggestion(
        is_privileged=bool(envelope.get("is_privileged", True)),
        category=category,
        reason=envelope.get("reason", "") or change.ai_explanation,
        confidence=float(envelope.get("confidence", 0.9)),
        key_phrases=list(envelope.get("key_phrases", [])),
        change_id=change.change_id,
    )


async def get_superdocs_service() -> SuperDocsIntegrationService:
    return SuperDocsIntegrationService()
