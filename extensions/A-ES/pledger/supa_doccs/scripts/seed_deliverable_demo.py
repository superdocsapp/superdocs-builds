"""Seed a demo deliverable (with one unverifiable claim) + an incremental
update history event against the latest completed run.

Used to verify the Deliverable Register tab:
  - every claim line carries a citation
  - the unverifiable claim (source_span=None) renders with the loud marker

Usage:
    uv run python scripts/seed_deliverable_demo.py [run_id]
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import SessionLocal
from src.pipeline.deliverable_store import persist_deliverable, load_deliverable_record
from src.pipeline.history_sql import emit_incremental_update_event


def _demo_claims(document_id: str) -> list[dict]:
    """Claims mirroring real extraction output. Claim 3 is unverifiable."""
    return [
        {
            "claim_id": "loan_agreement.interest_1",
            "claim_text": "The annual interest rate on the principal is 12.5% per annum.",
            "confidence": 0.94,
            "citation_status": "grounded",
            "start_offset": 1450,
            "end_offset": 1520,
            "page_number": 4,
            "section_id": "sec-3.1",
            "clause_ref": "§3.1.2",
            "snippet": "interest shall accrue at a rate of 12.5% per annum on the outstanding principal",
        },
        {
            "claim_id": "loan_agreement.repayment_2",
            "claim_text": "Repayments are due on the first business day of each month.",
            "confidence": 0.88,
            "citation_status": "grounded",
            "start_offset": 2310,
            "end_offset": 2372,
            "page_number": 6,
            "section_id": "sec-5.2",
            "clause_ref": "§5.2",
            "snippet": "all installment payments fall due on the first business day of each calendar month",
        },
        {
            # source_span=None at extraction — must surface UNVERIFIABLE in the UI
            "claim_id": "loan_agreement.penalty_3",
            "claim_text": "Early repayment may incur a penalty of up to 2% of the remaining balance.",
            "confidence": 0.41,
            "citation_status": "unverifiable",
        },
    ]


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else None

    if not run_id:
        from sqlalchemy import text
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id FROM runs WHERE status = 'completed' "
                    "ORDER BY started_at DESC LIMIT 1"
                )
            ).first()
        if row is None:
            print("ERROR: no completed run found", file=sys.stderr)
            sys.exit(1)
        run_id = str(row[0])

    document_id = str(uuid.uuid4())  # stand-in source document reference
    claims = _demo_claims(document_id)
    state = {"claims": claims, "document_id": document_id}

    record = persist_deliverable(SessionLocal, run_id, state)
    print(f"Seeded deliverable for run {run_id}")
    print(f"  hash: {record['deliverable_hash'][:16]}…")
    print(f"  sections: {record['section_count']}, claims: {record['claim_count']}")

    # Emit a Movement-3 incremental update event so the diff UI has data.
    hashes_after = {}
    stored = load_deliverable_record(SessionLocal, run_id)
    if stored:
        for key, section in stored["sections"].items():
            hashes_after[key] = section["content_hash"]

    emit_incremental_update_event(
        SessionLocal,
        run_id=run_id,
        pile_id=str(uuid.uuid4()),
        new_document_id=document_id,
        affected_sections=list(hashes_after.keys()),
        conflicts_detected=1,
        approval_items_created=1,
        hashes_before={k: "seed-before-" + "0" * 40 for k in hashes_after},
        hashes_after=hashes_after,
    )
    print("  emitted incremental_update history event")
    print("Verify: curl http://localhost:8000/runs/%s/deliverable | jq '.sections'" % run_id)


if __name__ == "__main__":
    main()
