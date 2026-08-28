"""Deliverable build/persist/load — shared by finalize, incremental, REST and MCP.

The incremental flow previously built a Deliverable in-process only
(ServiceRegistry.deliverable), meaning a plain first run produced no
retrievable deliverable. This module owns:

- ``build_deliverable_from_state``: reconstruct a hashed Deliverable from
  a pipeline state's claims (moved from incremental_api so the finalize
  node and the incremental flow share one implementation).
- ``persist_deliverable``: upsert the serialized deliverable into the
  ``deliverables`` table (migration 011) keyed by run_id.
- ``load_deliverable_record``: read the persisted record for a run.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from src.pipeline.deliverable import Deliverable

# Claim state keys carried through as citation evidence when present.
_CITATION_FIELDS = (
    "start_offset",
    "end_offset",
    "chunk_index",
    "page_number",
    "section_id",
    "clause_ref",
    "snippet",
)


def build_deliverable_from_state(run_state: dict) -> Deliverable:
    """Build a hashed Deliverable from a run state's claims.

    Claims are grouped into sections by derived claim type; each claim
    carries its source document and citation status so downstream
    consumers can render citations.
    """
    deliverable = Deliverable()

    for claim_data in run_state.get("claims", []):
        claim_id = claim_data.get("claim_id", str(uuid.uuid4()))
        claim_text = claim_data.get("claim_text", "")

        # Derive section key from claim_id (format: "doc_type.field_idx")
        # or fall back to the claim_id itself.
        if "." in claim_id:
            claim_type = claim_id.rsplit("_", 1)[0] if "_" in claim_id else claim_id
        else:
            claim_type = f"generic.{claim_id}"

        from src.pipeline.deliverable import SectionClaim

        deliverable.add_claim(
            SectionClaim(
                claim_id=claim_id,
                claim_type=claim_type,
                extracted_text=claim_text,
                confidence=float(claim_data.get("confidence", 0.7)),
                source_document_id=run_state.get(
                    "document_id", "unknown"
                ),
                citation_status=claim_data.get("citation_status", "grounded"),
            )
        )

    deliverable.compute_all_hashes()
    return deliverable


def serialize_deliverable(deliverable: Deliverable) -> dict[str, Any]:
    """Serialize a Deliverable into the JSONB shape stored in `deliverables.sections`."""
    sections: dict[str, Any] = {}
    for key, section in sorted(deliverable.sections.items()):
        sections[key] = {
            "key": section.key,
            "content_hash": section.content_hash,
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "claim_type": c.claim_type,
                    "extracted_text": c.extracted_text,
                    "confidence": c.confidence,
                    "source_document_id": c.source_document_id,
                    "citation_status": c.citation_status,
                }
                for c in section.claims
            ],
        }
    return sections


def enrich_sections_with_citations(
    sections: dict[str, Any], run_state: dict
) -> dict[str, Any]:
    """Attach span-level citation evidence to each serialized claim.

    Looks up each claim in the originating run state by claim_id and
    copies whatever citation fields (offsets, page, snippet, ...) the
    extraction stage recorded.
    """
    claims_by_id = {
        c.get("claim_id"): c for c in run_state.get("claims", [])
    }
    for section in sections.values():
        for claim in section["claims"]:
            source = claims_by_id.get(claim["claim_id"], {})
            citation = {
                field: source[field]
                for field in _CITATION_FIELDS
                if source.get(field) is not None
            }
            if citation:
                claim["citation"] = citation
    return sections


def persist_deliverable(session_factory: sessionmaker, run_id: str, state: dict) -> dict:
    """Build and persist the deliverable for a finalized run.

    Upserts on run_id so re-finalizing a resumed run replaces cleanly.

    Returns:
        The persisted record: {run_id, deliverable_hash, section_count,
        claim_count, sections}.
    """
    deliverable = build_deliverable_from_state(state)
    sections = enrich_sections_with_citations(
        serialize_deliverable(deliverable), state
    )
    record = {
        "run_id": run_id,
        "deliverable_hash": deliverable.deliverable_hash,
        "section_count": len(sections),
        "claim_count": sum(len(s["claims"]) for s in sections.values()),
        "sections": sections,
    }

    with session_factory() as session:  # type: Session
        session.execute(
            text(
                """
                INSERT INTO deliverables
                    (run_id, deliverable_hash, section_count, claim_count,
                     sections)
                VALUES (:run_id, :hash, :sections_n, :claims_n,
                        CAST(:sections AS jsonb))
                ON CONFLICT (run_id) DO UPDATE SET
                    deliverable_hash = EXCLUDED.deliverable_hash,
                    section_count = EXCLUDED.section_count,
                    claim_count = EXCLUDED.claim_count,
                    sections = EXCLUDED.sections,
                    created_at = NOW()
                """
            ),
            {
                "run_id": uuid.UUID(run_id),
                "hash": record["deliverable_hash"],
                "sections_n": record["section_count"],
                "claims_n": record["claim_count"],
                "sections": _json_dumps(sections),
            },
        )
        session.commit()
    return record


def load_deliverable_record(
    session_factory: sessionmaker, run_id: str
) -> Optional[dict[str, Any]]:
    """Load the persisted deliverable row for a run, or None."""
    try:
        run_uuid = uuid.UUID(run_id)
    except (ValueError, AttributeError):
        return None
    with session_factory() as session:
        row = session.execute(
            text(
                """
                SELECT run_id, deliverable_hash, section_count, claim_count,
                       sections, created_at
                FROM deliverables WHERE run_id = :run_id
                """
            ),
            {"run_id": run_uuid},
        ).first()
        if row is None:
            return None
        return {
            "run_id": str(row.run_id),
            "deliverable_hash": row.deliverable_hash,
            "section_count": row.section_count,
            "claim_count": row.claim_count,
            "sections": row.sections,
            "created_at": row.created_at.isoformat(),
        }


def _json_dumps(payload) -> str:
    import json

    return json.dumps(payload)
