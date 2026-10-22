"""Redaction detection and application services.

PRIMARY INTELLIGENCE LAYER (SuperDocs async chat API):
  - PII detection, privilege analysis, and redaction proposals flow through
    SuperDocsIntelligenceService with ``approval_mode="ask_every_time"``.
    Every finding surfaces as a native SuperDocs ``pending_change`` that a
    human reviewer must approve or reject before any byte is modified.
  - After human approval, approved redactions are applied as true
    byte-scrubbing (PyMuPDF redact annotations) from the pristine base PDF.
  - The scrubbed artifact is then re-imported into SuperDocs so the final
    packet is a native SuperDocs document, not a pure local PDF assembly.

FALLBACK PATH (LOCAL):
  - When SuperDocs is unreachable (no real API key, network failure, or
    upstream error), the local regex engine (fallback_detection) provides
    deterministic PII detection with provenance tag ``local_fallback``.
  - The fallback path is explicitly labeled in every proposal row so
    provenance is never ambiguous.
"""

import logging
from typing import cast
from uuid import UUID

import fitz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.domain.document import Document
from app.domain.redaction import (
    RedactionApproval,
    RedactionCategory,
    RedactionStatus,
)
from app.domain.redaction import (
    RedactionCandidate as DBRedactionCandidate,
)
from app.services.fallback_detection import PROVENANCE_LOCAL_FALLBACK, RedactionMatch, detect_in_pdf
from app.services.storage import base_pdf_source, redacted_pdf_path_for
from app.services.superdocs_intelligence import (
    PROVENANCE_SUPERDOCS,
    SuperDocsIntelligenceService,
)
from app.services.superdocs_port import PIICategory, PIIDetectionResult, PIIEntity
from app.services.superdocs_port import RedactionCandidate as PortRedactionCandidate
from app.time import utc_now

logger = logging.getLogger(__name__)
settings: Settings = get_settings()

__all__ = [
    "RedactionMatch",
    "RedactionDetectionService",
    "RedactionApplicationService",
    "db_candidates_to_superdocs",
]


def _match_to_entity(match: RedactionMatch) -> PIIEntity:
    category_map = {
        RedactionCategory.SSN: PIICategory.SSN,
        RedactionCategory.EMAIL: PIICategory.EMAIL,
        RedactionCategory.PHONE: PIICategory.PHONE,
        RedactionCategory.ACCOUNT_NUMBER: PIICategory.ACCOUNT_NUMBER,
        RedactionCategory.MEDICAL_TERM: PIICategory.MEDICAL_TERM,
        RedactionCategory.NAME: PIICategory.NAME,
        RedactionCategory.ADDRESS: PIICategory.ADDRESS,
        RedactionCategory.OTHER: PIICategory.OTHER,
    }
    return PIIEntity(
        category=category_map.get(match.category, PIICategory.OTHER),
        text=match.matched_text,
        page_number=match.page_number,
        start_offset=0,
        end_offset=len(match.matched_text),
        confidence=1.0,
        context_before=match.context_before,
        context_after=match.context_after,
        x0=match.x0,
        y0=match.y0,
        x1=match.x1,
        y1=match.y1,
    )


def _candidate_to_entity(candidate: DBRedactionCandidate) -> PIIEntity:
    category_map = {
        RedactionCategory.SSN: PIICategory.SSN,
        RedactionCategory.EMAIL: PIICategory.EMAIL,
        RedactionCategory.PHONE: PIICategory.PHONE,
        RedactionCategory.ACCOUNT_NUMBER: PIICategory.ACCOUNT_NUMBER,
        RedactionCategory.MEDICAL_TERM: PIICategory.MEDICAL_TERM,
        RedactionCategory.NAME: PIICategory.NAME,
        RedactionCategory.ADDRESS: PIICategory.ADDRESS,
        RedactionCategory.OTHER: PIICategory.OTHER,
    }
    return PIIEntity(
        category=category_map.get(candidate.category, PIICategory.OTHER),
        text=candidate.matched_text,
        page_number=candidate.page_number,
        start_offset=0,
        end_offset=len(candidate.matched_text),
        confidence=1.0,
        context_before=candidate.context_before or "",
        context_after=candidate.context_after or "",
        superdocs_change_id=candidate.superdocs_change_id,
    )


def db_candidates_to_superdocs(
    candidates: list[DBRedactionCandidate],
    approvals: dict | None = None,
) -> list[PortRedactionCandidate]:
    """Convert DB proposal rows into the port candidates expected by the
    SuperDocs apply endpoint (approved flag mirrors the human decision).

    ``approvals`` (candidate_id -> RedactionApproval) avoids lazy-loading the
    relationship from an async session; when omitted, only already-loaded
    approvals are used (module-level usage by the offline suite)."""
    converted = []
    for candidate in candidates:
        approval = (
            approvals.get(candidate.id)
            if approvals is not None
            else candidate.__dict__.get("approval")
        )
        converted.append(
            PortRedactionCandidate(
                entity=_candidate_to_entity(candidate),
                approved=candidate.status == RedactionStatus.APPROVED,
                approved_by=approval.approver if approval else None,
                approved_at=approval.approved_at.isoformat()
                if approval and approval.approved_at
                else None,
            )
        )
    return converted


class RedactionDetectionService:
    """Primary path: SuperDocs intelligence layer (async chat,
    ``approval_mode="ask_every_time"``, native pending_changes).
    Fallback path: local regex engine, explicitly labeled `local_fallback`.

    The injected ``superdocs`` object is duck-typed: it only needs a
    ``detect_pii(session, document, categories)`` method. Tests inject the
    in-memory FakeSuperDocsService; production uses the chat-driven
    SuperDocsIntelligenceService (or the legacy integration service).
    """

    def __init__(
        self,
        superdocs=None,
        config: Settings | None = None,
    ):
        self.config = config or get_settings()
        self._injected = superdocs
        self._default_superdocs = None

    async def _get_superdocs(self):
        if self._injected is not None:
            return self._injected
        if self.config.superdocs_available:
            if self._default_superdocs is None:
                self._default_superdocs = SuperDocsIntelligenceService(settings=self.config)
            return self._default_superdocs
        return None

    async def detect_pii_in_document(
        self,
        session: AsyncSession,
        document_id: str | UUID,
        categories: list[PIICategory] | None = None,
        siblings: list[Document] | None = None,
    ) -> PIIDetectionResult:
        document = await session.get(Document, document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        service = await self._get_superdocs()
        if service is not None:
            try:
                res = await service.detect_pii(session, document, categories, siblings=siblings)
                return cast(PIIDetectionResult, res)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"SuperDocs detection unavailable for {document.id} "
                    f"({type(exc).__name__}: {exc}); degrading to local fallback"
                )
                await self._mark_fallback(session, document, str(exc))
        else:
            logger.info(f"SuperDocs unavailable; using local fallback detection for {document.id}")

        return await self._detect_via_fallback(document)

    async def _detect_via_fallback(self, document: Document) -> PIIDetectionResult:
        source = base_pdf_source(document)
        if source is None or not source.exists():
            return PIIDetectionResult(
                entities=[], total_count=0, session_id="", document_id=str(document.id)
            )
        matches = detect_in_pdf(str(source))
        entities = [_match_to_entity(m) for m in matches]
        return PIIDetectionResult(
            entities=entities,
            total_count=len(entities),
            session_id="",
            document_id=str(document.id),
        )

    async def create_redaction_candidates(
        self,
        session: AsyncSession,
        document_id,
        pii_result: PIIDetectionResult | None = None,
    ) -> list[DBRedactionCandidate]:
        """Materialize DB candidate rows from a detection result.

        ``pii_result`` may come from the SuperDocs intelligence layer (native
        pending_changes) or the fallback engine. When omitted, fallback
        detection runs now (used by the offline unit suite).
        """
        if isinstance(document_id, Document):
            document = document_id
        else:
            document = await session.get(Document, document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        if pii_result is None:
            pii_result = await self._detect_via_fallback(document)

        provenance = PROVENANCE_SUPERDOCS if pii_result.session_id else PROVENANCE_LOCAL_FALLBACK
        candidates = []
        for entity in pii_result.entities:
            candidates.append(
                DBRedactionCandidate(
                    document_id=document.id,
                    page_number=entity.page_number,
                    category=self._map_pii_category(entity.category),
                    matched_text=entity.text,
                    context_before=entity.context_before,
                    context_after=entity.context_after,
                    x0=getattr(entity, "x0", 0) or 0,
                    y0=getattr(entity, "y0", 0) or 0,
                    x1=getattr(entity, "x1", 0) or 0,
                    y1=getattr(entity, "y1", 0) or 0,
                    status=RedactionStatus.PROPOSED,
                    proposed_by=provenance,
                    superdocs_change_id=getattr(entity, "superdocs_change_id", None),
                )
            )
        return candidates

    async def reconcile_candidates(
        self,
        session: AsyncSession,
        document_id: str | UUID,
        candidates: list[DBRedactionCandidate],
    ) -> tuple[list[DBRedactionCandidate], int]:
        """Return (new_candidates, skipped_count) so repeated detection never
        duplicates existing candidates."""
        target_doc_id = UUID(str(document_id)) if isinstance(document_id, str) else document_id
        result = await session.execute(
            select(DBRedactionCandidate).where(DBRedactionCandidate.document_id == target_doc_id)
        )
        existing_keys = {self._candidate_identity(c) for c in result.scalars().all()}

        created: list[DBRedactionCandidate] = []
        skipped = 0
        for candidate in candidates:
            key = self._candidate_identity(candidate)
            if key in existing_keys:
                skipped += 1
            else:
                created.append(candidate)
                existing_keys.add(key)

        return created, skipped

    @staticmethod
    def _candidate_identity(candidate) -> tuple:
        return (
            candidate.document_id,
            candidate.page_number,
            candidate.category,
            candidate.matched_text,
            candidate.x0,
            candidate.y0,
            candidate.x1,
            candidate.y1,
        )

    def _map_pii_category(self, pii_category: PIICategory) -> RedactionCategory:
        mapping = {
            PIICategory.SSN: RedactionCategory.SSN,
            PIICategory.EMAIL: RedactionCategory.EMAIL,
            PIICategory.PHONE: RedactionCategory.PHONE,
            PIICategory.ACCOUNT_NUMBER: RedactionCategory.ACCOUNT_NUMBER,
            PIICategory.MEDICAL_TERM: RedactionCategory.MEDICAL_TERM,
            PIICategory.NAME: RedactionCategory.NAME,
            PIICategory.ADDRESS: RedactionCategory.ADDRESS,
            PIICategory.DATE_OF_BIRTH: RedactionCategory.OTHER,
            PIICategory.CREDIT_CARD: RedactionCategory.OTHER,
            PIICategory.DRIVERS_LICENSE: RedactionCategory.OTHER,
            PIICategory.PASSPORT: RedactionCategory.OTHER,
            PIICategory.OTHER: RedactionCategory.OTHER,
        }
        return mapping.get(pii_category, RedactionCategory.OTHER)

    async def _mark_fallback(self, session: AsyncSession, document: Document, error: str) -> None:
        from app.domain.audit import AuditEvent, AuditEventType

        session.add(
            AuditEvent(
                packet_id=document.packet_id,
                document_id=document.id,
                event_type=AuditEventType.AI_ANALYSIS_FAILED,
                user_id="system",
                event_metadata={
                    "error": error,
                    "degraded_to": PROVENANCE_LOCAL_FALLBACK,
                },
            )
        )
        await session.commit()


class RedactionApplicationService:
    """Applies human-approved redactions through the SuperDocs-primary pipeline:

    1. Byte-scrub the source PDF with PyMuPDF (local, deterministic).
    2. Verify the scrubbed file (text truly gone).
    3. Sync the human decision to SuperDocs (``apply_redactions``).
    4. Re-import the scrubbed artifact into SuperDocs and export the native
       document so the final packet is assembled from a SuperDocs document.

    The local byte-scrub at step 1 is the authoritative source of truth;
    steps 3-4 keep the platform-side document consistent but degrade
    gracefully if SuperDocs is unreachable.
    """

    def __init__(
        self,
        superdocs=None,
        config: Settings | None = None,
    ):
        self.config = config or get_settings()
        self._injected = superdocs
        self._default_superdocs = None

    async def _get_superdocs(self):
        if self._injected is not None:
            return self._injected
        if self.config.superdocs_available:
            if self._default_superdocs is None:
                self._default_superdocs = SuperDocsIntelligenceService(settings=self.config)
            return self._default_superdocs
        return None

    # ------------------------------------------------------------------ #
    # Local byte-scrubbing engine (PyMuPDF)
    # ------------------------------------------------------------------ #
    def apply_redactions_to_pdf(
        self,
        input_path,
        output_path,
        candidates: list[DBRedactionCandidate],
    ) -> dict:
        """Scrub approved candidates from a source PDF and write a new file.

        True byte-scrubbing: each matched text span receives a redaction
        annotation (slightly expanded so glyphs are covered), then
        ``apply_redactions`` removes the covered content from the content
        stream — this is not a paint-over. Scrub from the pristine base so
        re-application is deterministic.
        """
        results: dict = {}
        doc = fitz.open(input_path)
        try:
            per_page: dict[int, list[fitz.Rect]] = {}
            for candidate in candidates:
                if candidate.status not in (RedactionStatus.APPROVED, RedactionStatus.APPLIED):
                    continue
                cid = str(candidate.id)
                page_index = candidate.page_number - 1
                if page_index < 0 or page_index >= len(doc):
                    results[cid] = {
                        "applied": False,
                        "error": f"Page {candidate.page_number} not found",
                    }
                    continue

                page = doc[page_index]
                spans = page.search_for(candidate.matched_text)

                if not spans:
                    # Fallback for scanned/image PDFs: use the candidate's
                    # explicit coordinates from detection.
                    if (
                        candidate.x0 is not None
                        and candidate.y0 is not None
                        and candidate.x1 is not None
                        and candidate.y1 is not None
                    ):
                        rect = fitz.Rect(
                            float(candidate.x0),
                            float(candidate.y0),
                            float(candidate.x1),
                            float(candidate.y1),
                        )
                        # Expand slightly so glyphs are fully covered
                        rect = rect + fitz.Rect(-2, -2, 2, 2)
                        page.add_redact_annot(rect, fill=(0, 0, 0))
                        per_page.setdefault(page_index, []).append(rect)
                        results[cid] = {"applied": True, "page": candidate.page_number}
                    else:
                        results[cid] = {
                            "applied": True,
                            "texts_not_found": [candidate.matched_text],
                            "page": candidate.page_number,
                        }
                    continue

                for span in spans:
                    per_page.setdefault(page_index, []).append(span)
                results[cid] = {"applied": True, "page": candidate.page_number}

            for page_index, spans in per_page.items():
                page = doc[page_index]
                for span in spans:
                    page.add_redact_annot(span + fitz.Rect(-2, -2, 2, 2))
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            doc.save(output_path, garbage=4, deflate=True)
        finally:
            doc.close()
        return results

    def _verify_redactions_pdf(
        self,
        pdf_path,
        candidates: list[DBRedactionCandidate],
    ) -> dict:
        """Confirm redacted text is truly gone from the output file."""
        results: dict = {}
        doc = fitz.open(pdf_path)
        try:
            pages = [page.get_text().lower() for page in doc]
        finally:
            doc.close()

        for candidate in candidates:
            page_index = (candidate.page_number or 1) - 1
            page_text = pages[page_index] if 0 <= page_index < len(pages) else "\n".join(pages)
            present = candidate.matched_text.lower() in page_text
            results[str(candidate.id)] = {
                "verified": not present,
                "text_still_present": present,
            }
        return results

    async def verify_redactions(
        self,
        session: AsyncSession,
        document: Document,
        candidates: list[DBRedactionCandidate],
    ) -> dict:
        """Verify the redacted artifact for a document (public surface used by
        the build gate and the offline suite)."""
        redacted = redacted_pdf_path_for(document)
        if not redacted.exists():
            return {
                str(c.id): {
                    "verified": False,
                    "text_still_present": True,
                    "error": "redacted file missing",
                }
                for c in candidates
            }
        return self._verify_redactions_pdf(redacted, candidates)

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #
    async def apply_redactions(
        self,
        session: AsyncSession,
        document,
        candidates: list[DBRedactionCandidate],
    ) -> dict:
        """Full human-approved redaction cycle.

        1. Byte-scrub the source PDF with PyMuPDF (local, deterministic).
        2. Verify the scrubbed file (text truly gone).
        3. In primary mode: sync the human decision to SuperDocs
           (``apply_redactions``) and re-export the native artifact.
        4. Return per-candidate results incl. verification evidence.
        """
        document = await session.get(Document, document.id)
        if not document:
            raise ValueError("Document not found")

        source = base_pdf_source(document)
        if source is None or not source.exists():
            raise ValueError(f"No PDF source available for {document.original_filename}")

        appliable = [
            c for c in candidates if c.status in (RedactionStatus.APPROVED, RedactionStatus.APPLIED)
        ]
        output_path = redacted_pdf_path_for(document)
        results = self.apply_redactions_to_pdf(source, output_path, appliable)
        if output_path.exists():
            verification = self._verify_redactions_pdf(output_path, appliable)
            for cid, entry in verification.items():
                results.setdefault(cid, {})["verified"] = entry["verified"]
                results.setdefault(cid, {})["text_still_present"] = entry["text_still_present"]

        approvals = {
            a.candidate_id: a
            for a in (
                await session.execute(
                    select(RedactionApproval).where(
                        RedactionApproval.candidate_id.in_([c.id for c in appliable])
                    )
                )
            ).scalars()
        }

        job_id = await self._sync_and_reexport(session, document, appliable, output_path, approvals)

        for candidate in appliable:
            entry = results.get(str(candidate.id), {})
            if entry.get("applied") and entry.get("verified"):
                candidate.status = RedactionStatus.APPLIED
                approval = approvals.get(candidate.id)
                if approval:
                    approval.applied_at = utc_now()
                    approval.applied_by = approval.approver
                    approval.verified_at = utc_now()
                    approval.verification_passed = True
                    approval.verification_details = (
                        f"superdocs_job={job_id}" if job_id else "local_byte_scrub"
                    )
            if job_id and entry.get("applied"):
                entry["job_id"] = job_id

        return results

    async def _sync_and_reexport(
        self,
        session: AsyncSession,
        document: Document,
        candidates: list[DBRedactionCandidate],
        output_path,
        approvals: dict | None = None,
    ) -> str | None:
        """Sync the human approval to SuperDocs and re-export the native
        artifact so the packet can be assembled from a SuperDocs document."""
        service = await self._get_superdocs()
        if service is None or not candidates:
            return None

        payload = db_candidates_to_superdocs(candidates, approvals)
        job_id = None
        try:
            status = await service.apply_redactions(session, document, payload)
            job_id = getattr(status, "job_id", None)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"SuperDocs apply sync failed for {document.id}: {exc}; "
                "local byte-scrub remains authoritative"
            )
            return None

        reexporter = getattr(service, "scrub_and_reimport", None)
        if reexporter is not None:
            try:
                await reexporter(session, document, output_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"SuperDocs re-export failed for {document.id}: {exc}; "
                    "local artifact remains authoritative"
                )
        return job_id
