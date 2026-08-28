"""Incremental update API — add a document to a pile without a full pipeline re-run.

Provides:
- POST /piles/{pile_id}/incremental — upload files that trigger focused incremental
  updates to the most recent completed/approved deliverable for that pile.
- PATCH /piles/{pile_id}/watch — configure a watched folder path for the pile.

How the incremental path differs from a full run:
1. It does NOT re-run all 13 pipeline nodes.
2. It only text-extracts + classifies + extracts claims from the NEW document.
3. It rebuilds the existing deliverable from the latest completed run's state.
4. It identifies which existing sections could be affected by the new claims.
5. It detects contradictions and routes them to the approval_queue (never silent).
6. Unaffected sections remain byte-identical (verifiable via section hashes).
7. Conflicts appear as approval_queue items with item_type="conflict".
8. It re-uses the existing human gate and audit_events infrastructure.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.database import SessionLocal
from src.pipeline.history_sql import emit_incremental_update_event
from src.models.audit import AuditEvent
from src.models.documents import Document, DocumentVersion
from src.models.piles import Pile, PileDocument
from src.models.runs import Run, RunStep
from src.pipeline.approval import ApprovalService, InMemoryApprovalStore
from src.pipeline.deliverable import Deliverable, SectionClaim
from src.pipeline.incremental import (
    ClaimTypeRetrievalLayer,
    IncrementalUpdateEngine,
    IncrementalUpdateResult,
)

logger = logging.getLogger(__name__)

# Upload directory (shared with piles_api)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

EXTENSION_MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".text": "text/plain",
}

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class IncrementalUpdateResponse(BaseModel):
    """Response from a successful incremental update."""

    pile_id: str
    document_id: str
    run_id: str
    affected_sections: list[str]
    unaffected_sections: list[str]
    conflicts_detected: int
    sections_updated: int
    approval_items_created: list[str]
    section_hashes: dict[str, str]


class WatchConfigRequest(BaseModel):
    """Request to configure a watched folder for a pile."""

    watched_folder_path: Optional[str] = Field(
        None, description="Absolute path to folder to watch. Set to null to disable."
    )


class WatchConfigResponse(BaseModel):
    """Response after updating watched folder configuration."""

    pile_id: str
    watched_folder_path: Optional[str]


# ---------------------------------------------------------------------------
# Module-level approval service injection
# ---------------------------------------------------------------------------

_approval_service: Optional[ApprovalService] = None


def set_incremental_approval_service(service: Optional[ApprovalService]) -> None:
    """Inject the approval service (called from main.py lifespan)."""
    global _approval_service
    _approval_service = service


def get_approval_service() -> ApprovalService:
    """Get the current approval service, creating a fallback if needed."""
    global _approval_service
    if _approval_service is None:
        store = InMemoryApprovalStore()
        _approval_service = ApprovalService(store)
    return _approval_service


# ---------------------------------------------------------------------------
# Core incremental logic
# ---------------------------------------------------------------------------


def _extract_text_from_bytes(raw_content: bytes, mime_type: str) -> str:
    """Extract text from document bytes (same logic as demo_executor)."""
    if mime_type == "text/plain":
        return raw_content.decode("utf-8", errors="replace")
    elif mime_type == "application/pdf":
        try:
            import pdfplumber
            import io
            with pdfplumber.open(io.BytesIO(raw_content)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    pages.append(text)
                return "\n\n".join(pages)
        except Exception as e:
            raise RuntimeError(f"PDF extraction failed: {e}")
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            import zipfile
            import io
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(io.BytesIO(raw_content)) as zf:
                with zf.open("word/document.xml") as doc_xml:
                    tree = ET.parse(doc_xml)
                    root = tree.getroot()
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    paragraphs = []
                    for para in root.iter(f"{{{ns['w']}}}p"):
                        texts = [t.text for t in para.iter(f"{{{ns['w']}}}t") if t.text]
                        if texts:
                            paragraphs.append("".join(texts))
                    return "\n".join(paragraphs)
        except Exception as e:
            raise RuntimeError(f"DOCX extraction failed: {e}")
    else:
        raise RuntimeError(f"Unsupported MIME type: {mime_type}")


async def _extract_claims_from_text(
    text: str, document_type: str, document_id: str
) -> list[SectionClaim]:
    """Extract claims from document text using LLM or regex fallback.

    Returns SectionClaim instances (compatible with Deliverable model).
    """
    from src.llm.deepseek_client import chat_completion_json

    # Chunk the text for extraction
    chunk_max_size = 1000
    chunk_overlap = 200
    stride = chunk_max_size - chunk_overlap
    chunks = []
    offset = 0
    idx = 0
    while offset < len(text):
        end = min(offset + chunk_max_size, len(text))
        chunks.append({"index": idx, "text": text[offset:end], "start_offset": offset, "end_offset": end})
        idx += 1
        offset += stride
        if end == len(text):
            break

    if not chunks:
        return []

    system_prompt = f"""You are a compliance document analyst. Extract all factual claims from the given text of a {document_type} document.

For each claim, identify:
- field_name: A structured field identifier (e.g., "interest_rate", "borrower_name", "principal_amount")
- value: The exact value extracted
- confidence: How confident you are (0.0-1.0)

Respond with JSON: {{"claims": [{{"field_name": "...", "value": "...", "confidence": 0.9}}]}}

Extract ALL factual claims — amounts, rates, dates, party names, obligations, etc."""

    all_claims: list[SectionClaim] = []

    # Process chunks in batches
    batch_size = 3
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        combined_text = "\n\n".join(
            f"[Chunk {c['index']}]:\n{c['text']}" for c in batch
        )

        try:
            result, _inp, _out = await chat_completion_json(
                system_prompt=system_prompt,
                user_prompt=f"Extract claims from:\n\n{combined_text}",
                max_tokens=4096,
            )

            raw_claims = result.get("claims", [])
            for claim_data in raw_claims:
                field_name = claim_data.get("field_name", "unknown")
                value = claim_data.get("value", "")
                confidence = float(claim_data.get("confidence", 0.7))

                claim_type = f"{document_type}.{field_name}"
                all_claims.append(SectionClaim(
                    claim_id=f"{claim_type}_{len(all_claims)}",
                    claim_type=claim_type,
                    extracted_text=value,
                    confidence=confidence,
                    source_document_id=document_id,
                ))
        except Exception as e:
            logger.warning("LLM extraction failed (batch %d), using regex fallback: %s", i, e)
            # Regex fallback: extract basic patterns
            import re
            for c in batch:
                chunk_text = c["text"]
                for m in re.finditer(r'(\w+[\w\s]*?):\s*(.+)', chunk_text):
                    field_name = m.group(1).strip().lower().replace(" ", "_")[:50]
                    value = m.group(2).strip()[:200]
                    claim_type = f"{document_type}.{field_name}"
                    all_claims.append(SectionClaim(
                        claim_id=f"{claim_type}_{len(all_claims)}",
                        claim_type=claim_type,
                        extracted_text=value,
                        confidence=0.5,
                        source_document_id=document_id,
                    ))

    return all_claims


async def _classify_document_text(text: str) -> str:
    """Classify a document by its text content. Returns a classification label."""
    from src.llm.deepseek_client import chat_completion_json

    sample = text[:3000]

    system_prompt = """You are a document classification expert for microfinance/lending documents.
Classify the document into exactly one of these categories:
- loan_agreement: A loan agreement, promissory note, or credit facility document
- modification_agreement: A loan modification, restructuring, or amendment document
- repayment_statement: A repayment schedule, payment history, or account statement

Respond with JSON: {"label": "<category>"}"""

    try:
        result, _inp, _out = await chat_completion_json(
            system_prompt=system_prompt,
            user_prompt=f"Classify this document:\n\n---\n{sample}\n---",
        )
        label = result.get("label", "loan_agreement")
        valid_labels = {"loan_agreement", "modification_agreement", "repayment_statement"}
        if label not in valid_labels:
            label = "loan_agreement"
        return label
    except Exception:
        # Keyword fallback
        text_lower = text.lower()
        if "modification" in text_lower or "amendment" in text_lower:
            return "modification_agreement"
        elif "repayment" in text_lower or "payment schedule" in text_lower:
            return "repayment_statement"
        return "loan_agreement"


def _build_deliverable_from_run_state(run_state: dict) -> Deliverable:
    """Reconstruct a Deliverable from a completed run's output state.

    Thin wrapper over the shared builder in deliverable_store — the same
    implementation the finalize node now uses, so both paths produce
    byte-identical section hashes.
    """
    from src.pipeline.deliverable_store import build_deliverable_from_state

    return build_deliverable_from_state(run_state)


def _get_latest_completed_run_for_pile(pile_id: str) -> Optional[dict]:
    """Find the most recent completed (or approved) run for a pile.

    Returns the final output_state of that run's last completed step, or None.
    """
    session = SessionLocal()
    try:
        # Find the latest run with status in (completed, approved)
        run = session.execute(
            select(Run)
            .where(Run.pile_id == uuid.UUID(pile_id))
            .where(Run.status.in_(["completed", "approved"]))
            .order_by(Run.started_at.desc())
        ).scalars().first()

        if run is None:
            return None

        # Get the last step's output_state
        last_step = session.execute(
            select(RunStep)
            .where(RunStep.run_id == run.id)
            .where(RunStep.status.in_(["completed", "skipped"]))
            .order_by(RunStep.step_order.desc())
        ).scalars().first()

        if last_step is None:
            return None

        return {
            "run_id": str(run.id),
            "output_state": last_step.output_state,
        }
    finally:
        session.close()


def _emit_audit_event(
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: str,
    previous_state: Optional[dict],
    new_state: dict,
    source_ref: Optional[str] = None,
) -> None:
    """Append an audit event to the audit_events table."""
    session = SessionLocal()
    try:
        event = AuditEvent(
            id=uuid.uuid4(),
            event_timestamp=datetime.now(timezone.utc),
            entity_type=entity_type,
            entity_id=uuid.UUID(entity_id) if entity_id else uuid.uuid4(),
            action=action,
            actor_id=actor_id,
            previous_state=previous_state,
            new_state=new_state,
            source_ref=source_ref,
        )
        session.add(event)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Failed to emit audit event: %s", e)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/piles", tags=["piles-incremental"])


@router.post("/{pile_id}/incremental", response_model=IncrementalUpdateResponse)
async def incremental_add_document(
    pile_id: str,
    files: list[UploadFile] = File(...),
) -> IncrementalUpdateResponse:
    """Upload document(s) and trigger a focused incremental update.

    Unlike POST /piles/{pile_id}/documents which just stores files,
    or POST /runs/start which starts a full 13-node pipeline run,
    this endpoint:

    1. Stores the new document (same as regular upload).
    2. Finds the latest completed run for this pile.
    3. Rebuilds the deliverable from that run's state.
    4. Extracts claims from ONLY the new document (text extract → classify → extract claims).
    5. Identifies which existing sections are affected.
    6. Detects contradictions → routes to approval queue.
    7. Applies non-conflicting updates to affected sections.
    8. Leaves unaffected sections byte-identical.

    Returns section hashes proving byte-identity of unaffected sections.
    """
    session = SessionLocal()
    try:
        # Verify pile exists
        pile = session.execute(
            select(Pile).where(Pile.id == uuid.UUID(pile_id))
        ).scalar_one_or_none()
        if pile is None:
            raise HTTPException(status_code=404, detail="Pile not found")
    finally:
        session.close()

    # Find latest completed run for this pile
    run_info = _get_latest_completed_run_for_pile(pile_id)
    if run_info is None:
        raise HTTPException(
            status_code=422,
            detail="No completed run exists for this pile. Run a full pipeline first.",
        )

    run_id = run_info["run_id"]
    run_state = run_info["output_state"]

    # Rebuild deliverable from the completed run's state
    deliverable = _build_deliverable_from_run_state(run_state)

    # Snapshot hashes before update
    hashes_before = deliverable.compute_all_hashes()

    # Set up incremental engine
    approval_service = get_approval_service()
    retrieval_layer = ClaimTypeRetrievalLayer()
    engine = IncrementalUpdateEngine(
        retrieval_layer=retrieval_layer,
        approval_service=approval_service,
        run_id=run_id,
    )

    # Process only the first file (can extend to multiple later)
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")

    file = files[0]
    filename = file.filename or "unnamed"
    mime_type = file.content_type or ""

    # Infer MIME from extension if generic
    if mime_type in ("application/octet-stream", ""):
        ext = Path(filename).suffix.lower()
        mime_type = EXTENSION_MIME_MAP.get(ext, mime_type)

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {mime_type}",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="File is empty")

    # Store the document (same as regular upload)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(content).hexdigest()
    doc_id = uuid.uuid4()
    version_id = uuid.uuid4()
    ext = Path(filename).suffix or ".bin"
    stored_filename = f"{doc_id}{ext}"
    storage_path = UPLOAD_DIR / stored_filename
    storage_path.write_bytes(content)

    # Create DB records
    session = SessionLocal()
    try:
        doc = Document(
            id=doc_id,
            filename=filename,
            mime_type=mime_type,
            ingested_at=datetime.now(timezone.utc),
            metadata_={},
        )
        session.add(doc)

        version = DocumentVersion(
            id=version_id,
            document_id=doc_id,
            content_hash=content_hash,
            storage_ref=str(storage_path),
            version_number=1,
        )
        session.add(version)

        # Link to pile
        pile_doc = PileDocument(
            pile_id=uuid.UUID(pile_id),
            document_id=doc_id,
            added_at=datetime.now(timezone.utc),
        )
        session.add(pile_doc)
        session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to store document: {e}")
    finally:
        session.close()

    # --- Incremental extraction pipeline (only for the new doc) ---
    doc_id_str = str(doc_id)

    # Step 1: Extract text from new document
    try:
        extracted_text = _extract_text_from_bytes(content, mime_type)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from document")

    # Step 2: Classify the new document
    document_type = await _classify_document_text(extracted_text)

    # Step 3: Extract claims from new document only
    new_claims = await _extract_claims_from_text(extracted_text, document_type, doc_id_str)

    # Step 4: Run incremental update engine
    result = engine.update(
        deliverable=deliverable,
        new_document_claims=new_claims,
        new_document_id=doc_id_str,
    )

    # Recompute hashes after update
    hashes_after = deliverable.compute_all_hashes()

    # Emit audit event — entity_type/action must conform to migration 006
    # CHECK constraints ('pile'/'incremental_update' were silently rejected).
    emit_incremental_update_event(
        SessionLocal,
        run_id=run_id,
        pile_id=pile_id,
        new_document_id=doc_id_str,
        affected_sections=list(result.affected_sections),
        conflicts_detected=len(result.conflicts),
        approval_items_created=result.approval_items_created,
        hashes_before=hashes_before,
        hashes_after=hashes_after,
    )

    return IncrementalUpdateResponse(
        pile_id=pile_id,
        document_id=doc_id_str,
        run_id=run_id,
        affected_sections=sorted(result.affected_sections),
        unaffected_sections=sorted(result.unaffected_sections),
        conflicts_detected=len(result.conflicts),
        sections_updated=len(result.sections_updated),
        approval_items_created=result.approval_items_created,
        section_hashes=hashes_after,
    )


@router.patch("/{pile_id}/watch", response_model=WatchConfigResponse)
async def configure_watch(pile_id: str, request: WatchConfigRequest) -> WatchConfigResponse:
    """Configure a watched folder path for a pile.

    When set, the FolderWatcher can be started to monitor this directory
    and trigger incremental updates automatically when new files appear.
    Set to null to disable watching.
    """
    session = SessionLocal()
    try:
        pile = session.execute(
            select(Pile).where(Pile.id == uuid.UUID(pile_id))
        ).scalar_one_or_none()
        if pile is None:
            raise HTTPException(status_code=404, detail="Pile not found")

        # Store watched folder in pile metadata
        metadata = dict(pile.metadata_ or {})
        previous_path = metadata.get("watched_folder_path")

        if request.watched_folder_path:
            metadata["watched_folder_path"] = request.watched_folder_path
        else:
            metadata.pop("watched_folder_path", None)

        pile.metadata_ = metadata
        pile.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Audit event (entity_type 'pile' allowed since migration 012)
        _emit_audit_event(
            entity_type="pile",
            entity_id=pile_id,
            action="updated",
            actor_id="api",
            previous_state={"watched_folder_path": previous_path},
            new_state={
                "watched_folder_path": request.watched_folder_path,
                "type": "watch_configured",
            },
        )

        return WatchConfigResponse(
            pile_id=pile_id,
            watched_folder_path=request.watched_folder_path,
        )
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to configure watch: {e}")
    finally:
        session.close()
