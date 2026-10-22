"""SuperDocs primary intelligence layer.

SuperDocs is the document substrate and the AI review loop. This service drives
PII detection, privilege analysis, and redaction proposals through the
SuperDocs **async chat API** with ``approval_mode="ask_every_time"`` so every
proposal surfaces as a native SuperDocs ``pending_change`` that a human must
approve or reject one-by-one (or in batches) before any data is modified.

The local PyMuPDF/regex/OCR path (`app.services.fallback_detection`) is a
strictly labeled fallback used only when SuperDocs is unavailable (no real API
key, network failure, or upstream error).
"""

import asyncio
import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.domain.document import Document, ProcessingStatus
from app.domain.privilege import PrivilegeCategory as DBPrivilegeCategory
from app.domain.privilege import PrivilegeDecision, PrivilegeStatus
from app.domain.redaction import RedactionCandidate, RedactionCategory, RedactionStatus
from app.services.superdocs_adapter import SuperDocsRESTAdapter
from app.services.superdocs_port import (
    ExportResult,
    JobStatus,
    PIICategory,
    PIIDetectionResult,
    PIIEntity,
    ProposedChange,
    ProposedChangeBatch,
    SuperDocsPort,
)

logger = logging.getLogger(__name__)

PROVENANCE_SUPERDOCS = "superdocs"
PROVENANCE_LOCAL_FALLBACK = "local_fallback"

# Structured instruction contract sent over the chat API. The platform's native
# pending_changes carry `ai_explanation` free text; we pin it to a
# machine-readable form so proposals map 1:1 back to DB rows. See BUGS.md.
PII_ANALYSIS_INSTRUCTION = (
    "You are a litigation redaction analyst. Review the attached document and propose "
    "one pending change for every personally identifiable information (PII) instance "
    "you find, and exactly one pending change if the document is privileged.\n"
    "Rules:\n"
    "- PII categories: ssn, email, phone, account_number, medical_term, name, address, "
    "date_of_birth, credit_card, drivers_license, passport, other.\n"
    "- For each PII instance propose operation 'replace' whose new_html replaces the "
    "matched text with '[REDACTED]'.\n"
    "- Set ai_explanation EXACTLY to the machine-readable form:\n"
    "  PII|<category>|<exact matched text>|<1-based page number>\n"
    "- If the document is privileged, propose exactly one change whose ai_explanation is:\n"
    "  PRIVILEGE|<category>|<reason>  (category: attorney_client, work_product, "
    "joint_defense, common_interest, other)\n"
    "- Do NOT propose changes for Bates-style labels, invoice numbers, docket numbers, "
    "or calendar dates.\n"
    "- Never redact privilege markers themselves.\n"
    "- Do not apply any change: await human approval before modifying the document."
)

PII_EXPLANATION_RE = re.compile(r"^PII\|([a-z_]+)\|(.*)\|(\d+)$", re.DOTALL)
PRIVILEGE_EXPLANATION_RE = re.compile(r"^PRIVILEGE\|([a-z_]+)\|(.*)$", re.DOTALL)

PII_CATEGORY_TO_DB = {
    "ssn": RedactionCategory.SSN,
    "email": RedactionCategory.EMAIL,
    "phone": RedactionCategory.PHONE,
    "account_number": RedactionCategory.ACCOUNT_NUMBER,
    "medical_term": RedactionCategory.MEDICAL_TERM,
    "name": RedactionCategory.NAME,
    "address": RedactionCategory.ADDRESS,
    "date_of_birth": RedactionCategory.OTHER,
    "credit_card": RedactionCategory.OTHER,
    "drivers_license": RedactionCategory.OTHER,
    "passport": RedactionCategory.OTHER,
    "other": RedactionCategory.OTHER,
}

PRIVILEGE_CATEGORY_TO_DB = {
    "attorney_client": DBPrivilegeCategory.ATTORNEY_CLIENT,
    "work_product": DBPrivilegeCategory.WORK_PRODUCT,
    "joint_defense": DBPrivilegeCategory.OTHER,
    "common_interest": DBPrivilegeCategory.OTHER,
    "other": DBPrivilegeCategory.OTHER,
}


class SuperDocsIntelligenceError(Exception):
    """Raised when the primary intelligence path cannot complete; callers
    degrade to the local fallback path."""


@dataclass
class ParsedIntelligenceChange:
    kind: str  # "pii" | "privilege" | "other"
    category: str | None = None
    matched_text: str | None = None
    page_number: int | None = None
    reason: str | None = None


@dataclass
class IntelligenceAnalysis:
    job_id: str
    batch: ProposedChangeBatch
    redaction_candidates: list[RedactionCandidate] = field(default_factory=list)
    privilege_proposal: PrivilegeDecision | None = None
    changes: list[dict] = field(default_factory=list)


def _strip_tags(fragment: str | None) -> str:
    if not fragment:
        return ""
    text = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(text).strip()


def parse_intelligence_change(change: ProposedChange) -> ParsedIntelligenceChange:
    """Map a native SuperDocs pending_change to a typed proposal.

    Primary signal is the structured ``ai_explanation`` (see
    PII_ANALYSIS_INSTRUCTION); when the platform returns free-form
    explanations, we fall back to the change payload itself (operation,
    old_html) and label the result ``other``.
    """
    explanation = (change.ai_explanation or "").strip()

    pii_match = PII_EXPLANATION_RE.match(explanation)
    if pii_match:
        category, text, page_str = pii_match.groups()
        try:
            page = int(page_str)
        except ValueError:
            page = None
        return ParsedIntelligenceChange(
            kind="pii",
            category=category,
            matched_text=text.strip(),
            page_number=page,
        )

    priv_match = PRIVILEGE_EXPLANATION_RE.match(explanation)
    if priv_match:
        category, reason = priv_match.groups()
        return ParsedIntelligenceChange(
            kind="privilege",
            category=category,
            reason=reason.strip(),
        )

    # Free-form fallback: derive the matched text from old_html and treat the
    # change as an untyped redaction proposal (category `other`).
    return ParsedIntelligenceChange(
        kind="other",
        category="other",
        matched_text=_strip_tags(change.old_html) or None,
        page_number=None,
    )


class SuperDocsIntelligenceService:
    """Primary intelligence provider over the SuperDocs async chat API."""

    def __init__(
        self,
        adapter: SuperDocsPort | None = None,
        settings: Settings | None = None,
        poll_interval: float = 1.0,
        max_polls: int = 300,
    ):
        self.adapter = adapter or SuperDocsRESTAdapter()
        self.settings = settings or get_settings()
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    # ------------------------------------------------------------------ #
    # Analysis
    # ------------------------------------------------------------------ #
    async def analyze_document(
        self,
        session: AsyncSession,
        document: Document,
        instruction: str = PII_ANALYSIS_INSTRUCTION,
        sibling_documents: list[Document] | None = None,
    ) -> IntelligenceAnalysis:
        """Run the intelligence pass over one document.

        Uploads the document (reusing the persisted session when present),
        starts an async chat job with ``approval_mode="ask_every_time"``,
        polls it to ``awaiting_approval``, and materializes every native
        ``pending_change`` into DB proposal rows (redaction candidates and,
        at most, one privilege proposal).

        When *sibling_documents* is provided the instruction is augmented
        with a brief packet manifest so SuperDocs understands the document
        is part of a litigation exhibit set.
        """
        if not document.superdocs_session_id:
            await self._ensure_uploaded(session, document)
            await session.refresh(document)

        effective_instruction = instruction
        if sibling_documents:
            manifest_lines = [
                f"- {s.display_order}. {s.original_filename} ({s.page_count} pages)"
                for s in sibling_documents
            ]
            effective_instruction += (
                "\n\nThis document is one exhibit in a Bates-stamped litigation packet "
                "containing the following documents:\n"
                + "\n".join(manifest_lines)
                + "\nUse this context when assessing privilege: documents that share "
                "overlapping content with other exhibits in the same packet are more "
                "likely to be work product or exhibits that have been produced to a "
                "third party."
            )

        job_id = await self.adapter.chat_async(
            message=effective_instruction,
            session_id=document.superdocs_session_id,
            approval_mode="ask_every_time",
            model_tier="core",
        )
        job_status = await self._poll_until_terminal(job_id)

        if job_status.status == "awaiting_approval":
            batch = await self._fetch_proposed_changes(job_id)
            analysis = self._materialize_proposals(document, batch)
            analysis.job_id = job_id
            analysis.batch = batch
            return analysis

        if job_status.status == "failed":
            raise SuperDocsIntelligenceError(
                f"SuperDocs analysis job {job_id} failed: {job_status.error}"
            )

        # "completed" with no pending changes: nothing proposed.
        return IntelligenceAnalysis(
            job_id=job_id,
            batch=ProposedChangeBatch(
                batch_id="", batch_total=0, changes=[], awaiting_kind="approval"
            ),
        )

    async def _ensure_uploaded(self, session: AsyncSession, document: Document) -> None:
        from app.services.superdocs_integration import SuperDocsIntegrationService

        integration = SuperDocsIntegrationService(adapter=self.adapter, settings=self.settings)
        await integration.upload_document_to_superdocs(session, document)
        document.processing_status = ProcessingStatus.AI_ANALYSIS
        await session.commit()

    async def _poll_until_terminal(self, job_id: str) -> JobStatus:
        terminal = {"awaiting_approval", "completed", "failed"}
        for _ in range(self.max_polls):
            status = await self.adapter.poll_job(job_id)
            if status.status in terminal:
                return status
            await asyncio.sleep(self.poll_interval)
        raise SuperDocsIntelligenceError(f"SuperDocs job {job_id} did not reach a terminal state")

    async def _fetch_proposed_changes(self, job_id: str) -> ProposedChangeBatch:
        status = await self.adapter.poll_job(job_id)
        if status.status != "awaiting_approval":
            return ProposedChangeBatch(batch_id="", batch_total=0, changes=[])
        if status.metadata and "pending_changes" in status.metadata:
            content = status.metadata["pending_changes"]
            if isinstance(content, str):
                return self.adapter.parse_proposed_change_batch(content)
            if isinstance(content, dict):
                import json

                return self.adapter.parse_proposed_change_batch(json.dumps(content))
        return ProposedChangeBatch(batch_id="", batch_total=0, changes=[])

    def _materialize_proposals(
        self, document: Document, batch: ProposedChangeBatch
    ) -> IntelligenceAnalysis:
        analysis = IntelligenceAnalysis(job_id="", batch=batch)
        seen_privilege = False

        for change in batch.changes:
            parsed = parse_intelligence_change(change)
            if parsed.kind == "pii":
                candidate = RedactionCandidate(
                    document_id=document.id,
                    page_number=parsed.page_number or 1,
                    category=PII_CATEGORY_TO_DB.get(
                        (parsed.category or "").lower(), RedactionCategory.OTHER
                    ),
                    matched_text=parsed.matched_text or "",
                    context_before="",
                    context_after="",
                    x0=0,
                    y0=0,
                    x1=0,
                    y1=0,
                    status=RedactionStatus.PROPOSED,
                    proposed_by=PROVENANCE_SUPERDOCS,
                    reason=change.ai_explanation,
                    superdocs_change_id=change.change_id,
                )
                analysis.redaction_candidates.append(candidate)
            elif parsed.kind == "privilege" and not seen_privilege:
                seen_privilege = True
                analysis.privilege_proposal = PrivilegeDecision(
                    packet_id=document.packet_id,
                    document_id=document.id,
                    status=PrivilegeStatus.PENDING,
                    category=PRIVILEGE_CATEGORY_TO_DB.get(
                        (parsed.category or "").lower(), DBPrivilegeCategory.OTHER
                    ),
                    reason=parsed.reason,
                    proposed_by=PROVENANCE_SUPERDOCS,
                    superdocs_change_id=change.change_id,
                )

        return analysis

    # ------------------------------------------------------------------ #
    # Human approval sync + native re-export
    # ------------------------------------------------------------------ #
    async def sync_approval(
        self,
        document: Document,
        job_id: str,
        approved: bool,
        changes: list[dict],
        feedback: str | None = None,
    ) -> JobStatus:
        """Propagate the human one-by-one/batch decision back to SuperDocs so
        the platform-side document stays consistent with local state."""
        if not document.superdocs_session_id:
            raise ValueError("Document not uploaded to SuperDocs")
        return await self.adapter.approve_changes(
            session_id=document.superdocs_session_id,
            job_id=job_id,
            approved=approved,
            changes=changes,
            feedback=feedback,
        )

    async def reexport_document(self, document: Document, format: str = "pdf") -> Path:
        """Re-export the post-approval artifact through SuperDocs so the final
        packet is built from a native SuperDocs document, not a pure local
        assembly. Returns the local cache path of the exported PDF."""
        if not document.superdocs_session_id:
            raise ValueError("Document not uploaded to SuperDocs")
        result = await self.adapter.export_document(
            session_id=document.superdocs_session_id,
            format=format,
        )
        if not result.download_url:
            raise SuperDocsIntelligenceError(
                f"SuperDocs export returned no download_url for {document.id}"
            )
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            response = await client.get(result.download_url)
            response.raise_for_status()
            payload = response.content

        export_path = self.settings.working_path / f"{document.sha256}_superdocs_export.pdf"
        export_path.write_bytes(payload)
        logger.info(
            f"Re-exported SuperDocs-native artifact for {document.id} "
            f"({len(payload)} bytes) -> {export_path.name}"
        )
        return export_path

    # ------------------------------------------------------------------ #
    # Duck-typed port surface (same shape as FakeSuperDocsService and the
    # legacy integration service) so RedactionDetectionService / Redaction
    # ApplicationService treat the primary and fallback providers uniformly.
    # ------------------------------------------------------------------ #
    async def detect_pii(
        self,
        session: AsyncSession,
        document: Document,
        categories: list[PIICategory] | None = None,
        siblings: list[Document] | None = None,
    ) -> PIIDetectionResult:
        """PRIMARY PII detection: async chat + ask_every_time, where every
        finding is a native pending_change awaiting human approval."""
        analysis = await self.analyze_document(session, document, sibling_documents=siblings)
        _REVERSE_CATEGORY = {
            RedactionCategory.SSN: PIICategory.SSN,
            RedactionCategory.EMAIL: PIICategory.EMAIL,
            RedactionCategory.PHONE: PIICategory.PHONE,
            RedactionCategory.ACCOUNT_NUMBER: PIICategory.ACCOUNT_NUMBER,
            RedactionCategory.MEDICAL_TERM: PIICategory.MEDICAL_TERM,
            RedactionCategory.NAME: PIICategory.NAME,
            RedactionCategory.ADDRESS: PIICategory.ADDRESS,
            RedactionCategory.OTHER: PIICategory.OTHER,
        }
        entities = []
        for candidate in analysis.redaction_candidates:
            pii_category = _REVERSE_CATEGORY.get(candidate.category, PIICategory.OTHER)
            if categories and pii_category not in categories:
                continue
            entities.append(
                PIIEntity(
                    category=pii_category,
                    text=candidate.matched_text,
                    page_number=candidate.page_number,
                    start_offset=0,
                    end_offset=len(candidate.matched_text),
                    confidence=0.95,
                    context_before=candidate.context_before or "",
                    context_after=candidate.context_after or "",
                    superdocs_change_id=candidate.superdocs_change_id,
                    change_id=candidate.superdocs_change_id or "",
                )
            )
        return PIIDetectionResult(
            entities=entities,
            total_count=len(entities),
            session_id=document.superdocs_session_id or "",
            document_id=document.superdocs_document_id or str(document.id),
            job_id=analysis.job_id,
        )

    async def apply_redactions(
        self,
        session: AsyncSession,
        document: Document,
        candidates: list,
    ) -> JobStatus:
        """Sync the human-approved candidate set back to the SuperDocs
        session (platform-side consistency after the local byte-scrub)."""
        if not document.superdocs_session_id or not document.superdocs_document_id:
            raise ValueError("Document not uploaded to SuperDocs")
        return await self.adapter.apply_redactions(
            session_id=document.superdocs_session_id,
            document_id=document.superdocs_document_id,
            candidates=candidates,
        )

    async def scrub_and_reimport(
        self,
        session: AsyncSession,
        document: Document,
        local_pdf_path: Path,
    ) -> "ExportResult":
        """Upload the locally byte-scrubbed PDF back into the document's
        SuperDocs session and export the native artifact."""
        from app.services.superdocs_integration import SuperDocsIntegrationService

        integration = SuperDocsIntegrationService(adapter=self.adapter, settings=self.settings)
        return await integration.scrub_and_reimport(session, document, local_pdf_path)

    async def close(self):
        await self.adapter.close()


def provenance_for(settings: Settings | None = None) -> str:
    """Which intelligence source will be used: 'superdocs' or 'local_fallback'."""
    settings = settings or get_settings()
    return PROVENANCE_SUPERDOCS if settings.superdocs_available else PROVENANCE_LOCAL_FALLBACK
