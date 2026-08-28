"""Document fact view API — every fact extracted from a document.

Backs the document detail view: field name, extracted value,
extraction method, and citation per fact; plus the original source
text with span offsets so the UI can highlight inline.

Every value is served from durable storage (claims/source_locations
tables + the stored document file). Fields recorded as not_found by
the extractors are returned as rows with extracted_value=null so the
UI can render "not found" instead of silently omitting them.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from src.database import SessionLocal

router = APIRouter(prefix="/documents", tags=["document-facts"])


class FactCitation(BaseModel):
    start_offset: int
    end_offset: int
    snippet: str
    page_number: int | None = None
    section_id: str | None = None


class DocumentFact(BaseModel):
    """One extracted fact — or an expected field that was not extracted."""

    field_name: str
    extracted_value: str | None  # null ⇒ "not found"
    confidence: float | None
    extraction_method: str | None  # structured | llm | llm_fallback | regex_fallback
    citation_status: str  # "grounded" | "unverifiable" | "not_found"
    cited_span: FactCitation | None


class DocumentFactsResponse(BaseModel):
    document_id: str
    document_version_id: str
    filename: str
    classification: str | None
    run_id: str | None
    source_text: str  # full text for the raw-text tab's inline highlights
    facts: list[DocumentFact]


def _load_source_text(storage_ref: str) -> str:
    path = Path(storage_ref)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Stored document file missing: {storage_ref}",
        )
    return path.read_bytes().decode("utf-8", errors="replace")


@router.get("/{document_id}/facts", response_model=DocumentFactsResponse)
def get_document_facts(
    document_id: str,
    run_id: Optional[str] = Query(default=None),
) -> DocumentFactsResponse:
    """All facts extracted from a document, with real resolved spans.

    - cited_span.snippet is sliced from the STORED SOURCE TEXT using the
      persisted character offsets — the UI never reconstructs it.
    - Expected-but-missing fields come back as extracted_value=null
      ("not found"), sourced from the extractor registry for the
      document's classification.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")

    session = SessionLocal()
    try:
        doc = session.execute(
            text("SELECT filename FROM documents WHERE id = CAST(:id AS uuid)"),
            {"id": doc_uuid},
        ).first()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")

        # Latest version unless a specific run pins one.
        version = session.execute(
            text(
                """
                SELECT dv.id, dv.storage_ref
                FROM document_versions dv
                WHERE dv.document_id = CAST(:id AS uuid)
                ORDER BY dv.version_number DESC
                LIMIT 1
                """
            ),
            {"id": doc_uuid},
        ).first()
        if version is None:
            raise HTTPException(status_code=404, detail="Document has no versions")

        # Choose the run: explicit run_id wins, else latest run that
        # classified this document version.
        if run_id:
            run = session.execute(
                text(
                    """
                    SELECT r.id FROM runs r
                    JOIN run_steps rs ON rs.run_id = r.id
                    WHERE r.id = CAST(:rid AS uuid)
                      AND rs.step_name = 'classify_document'
                    ORDER BY rs.step_order DESC LIMIT 1
                    """
                ),
                {"rid": uuid.UUID(run_id)},
            ).first()
        else:
            run = session.execute(
                text(
                    """
                    SELECT rs.run_id AS id
                    FROM run_steps rs
                    WHERE rs.step_name = 'classify_document'
                      AND rs.output_state->>'document_version_id' = :vid
                    ORDER BY rs.started_at DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"vid": str(version.id)},
            ).first()

        classification: Optional[str] = None
        run_id_str: Optional[str] = None
        if run is not None:
            run_id_str = str(run.id)
            cls_row = session.execute(
                text(
                    """
                    SELECT output_state->>'classification_label' AS label
                    FROM run_steps
                    WHERE run_id = CAST(:rid AS uuid)
                      AND step_name = 'classify_document'
                    ORDER BY step_order DESC LIMIT 1
                    """
                ),
                {"rid": uuid.UUID(run_id_str)},
            ).first()
            classification = cls_row.label if cls_row else None

        source_text = _load_source_text(version.storage_ref)

        # Scope claims to a single run: the pinned run if given, else the
        # latest run that extracted claims for this version. Every pile
        # start re-extracts the pile's documents, so a version accumulates
        # claims from multiple runs — showing all of them would mix stale
        # extractions (e.g. pre-fix unverifiable spans) with current ones.
        # Older runs' claims remain as durable audit rows.
        claim_run_id: Optional[str] = run_id
        if claim_run_id is None:
            latest_claim_run = session.execute(
                text(
                    """
                    SELECT run_id FROM claims
                    WHERE document_version_id = CAST(:vid AS uuid)
                    ORDER BY extracted_at DESC
                    LIMIT 1
                    """
                ),
                {"vid": version.id},
            ).first()
            claim_run_id = str(latest_claim_run.run_id) if latest_claim_run else None

        claim_rows = session.execute(
            text(
                """
                SELECT c.id, c.extracted_text, c.claim_type, c.confidence,
                       c.field_name, c.extraction_method,
                       sl.start_offset, sl.end_offset,
                       sl.page_number, sl.section_id
                FROM claims c
                LEFT JOIN source_locations sl ON sl.claim_id = c.id
                WHERE c.document_version_id = CAST(:vid AS uuid)
                  AND (CAST(:rid AS uuid) IS NULL OR c.run_id = CAST(:rid AS uuid))
                ORDER BY COALESCE(sl.start_offset, 2147483647)
                """
            ),
            {"vid": version.id, "rid": claim_run_id},
        ).mappings().all()

        def _citation(row) -> FactCitation | None:
            if row["start_offset"] is None:
                return None
            start, end = int(row["start_offset"]), int(row["end_offset"])
            if not (0 <= start < end <= len(source_text)):
                return None  # corrupt span — degrade to unverifiable
            return FactCitation(
                start_offset=start,
                end_offset=end,
                snippet=source_text[start:end],
                page_number=row["page_number"],
                section_id=row["section_id"],
            )

        facts: list[DocumentFact] = []
        seen_fields: set[str] = set()
        for row in claim_rows:
            field = (
                row["field_name"]
                or (
                    row["claim_type"].rsplit(".", 1)[-1]
                    if "." in (row["claim_type"] or "")
                    else row["claim_type"]
                )
                or "unknown"
            )
            value = row["extracted_text"]
            is_not_found = (
                value == "not_found"
                or value.startswith("not_found:")
                or ": not_found" in value
            )
            citation = _citation(row)
            status = (
                "not_found"
                if is_not_found
                else ("grounded" if citation else "unverifiable")
            )
            seen_fields.add(field)
            facts.append(
                DocumentFact(
                    field_name=field,
                    extracted_value=None if is_not_found else value,
                    confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                    extraction_method=row["extraction_method"],
                    citation_status=status,
                    cited_span=citation if status == "grounded" else None,
                )
            )

        # Expected fields that no extractor produced → explicit not-found rows.
        if classification:
            from src.pipeline.extractors.registry import EXTRACTOR_REGISTRY

            extractor_cls = EXTRACTOR_REGISTRY.get(classification)
            required = getattr(extractor_cls, "REQUIRED_FIELDS", []) if extractor_cls else []
            for missing in required:
                if missing not in seen_fields:
                    facts.append(
                        DocumentFact(
                            field_name=missing,
                            extracted_value=None,
                            confidence=None,
                            extraction_method=None,
                            citation_status="not_found",
                            cited_span=None,
                        )
                    )

        facts.sort(key=lambda f: (f.citation_status == "not_found", f.field_name))

        return DocumentFactsResponse(
            document_id=str(doc_uuid),
            document_version_id=str(version.id),
            filename=doc.filename,
            classification=classification,
            run_id=run_id_str,
            source_text=source_text,
            facts=facts,
        )
    finally:
        session.close()
