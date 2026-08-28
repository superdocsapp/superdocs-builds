"""Seed approval-queue findings + audit-trail events for a run so the
Findings view can be verified end-to-end.

Creates one pending finding and one approved finding (with its decision
audit event) against the latest completed run.

Usage:
    uv run python scripts/seed_findings_demo.py [run_id]
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import SessionLocal
from src.pipeline.citation_payload import build_source_citation
from src.pipeline.history_sql import emit_audit_event, emit_decision_event


def _enqueue_finding(session_factory, run_id: str, payload: dict) -> str:
    """Insert an approval_queue finding row + its audit-trail creation event."""
    item_id = str(uuid.uuid4())

    from sqlalchemy import text

    with session_factory() as session:
        session.execute(
            text(
                """
                INSERT INTO approval_queue
                    (id, status, queued_at, priority, version, run_id,
                     item_type, payload)
                VALUES (CAST(:iid AS uuid), 'pending', NOW(), 2, 1,
                        CAST(:rid AS uuid), 'finding', CAST(:payload AS jsonb))
                """
            ),
            {"iid": item_id, "rid": run_id, "payload": _json(payload)},
        )
        session.commit()

    emit_audit_event(
        session_factory,
        entity_type="approval_queue",
        entity_id=item_id,
        action="created",
        actor_id="seed_findings_demo",
        new_state={
            "run_id": run_id,
            "type": "finding_created",
            "rule_id": payload.get("details", {}).get("rule_id"),
            "claim_id": payload.get("details", {}).get("claim_id"),
        },
    )
    return item_id


def _decide(session_factory, item_id: str, run_id: str, decision: str, reviewer: str) -> None:
    from sqlalchemy import text

    with session_factory() as session:
        session.execute(
            text(
                """
                INSERT INTO decisions
                    (id, approval_queue_id, decision_value, reviewer_id,
                     decided_at, justification)
                VALUES (gen_random_uuid(), CAST(:iid AS uuid), :decision,
                        :reviewer, NOW(), :justification)
                """
            ),
            {
                "iid": item_id,
                "decision": decision,
                "reviewer": reviewer,
                "justification": f"{decision} via seed_findings_demo",
            },
        )
        session.execute(
            text(
                """
                UPDATE approval_queue
                SET status = :decision, decided_at = NOW(), version = version + 1
                WHERE id = CAST(:iid AS uuid)
                """
            ),
            {"iid": item_id, "decision": decision},
        )
        session.commit()

    emit_decision_event(
        session_factory,
        item_id=item_id,
        run_id=run_id,
        decision=decision,
        reviewer_id=reviewer,
        justification=f"{decision} via seed_findings_demo",
    )


def _resolve_document(session, run_id: str) -> dict:
    """Resolve the run's document/version and load its source text."""
    from pathlib import Path
    from sqlalchemy import text as _text

    row = session.execute(
        _text(
            """
            SELECT dv.id AS version_id, dv.storage_ref,
                   r.config_snapshot->>'document_id' AS document_id
            FROM runs r
            JOIN document_versions dv ON dv.document_id = r.config_snapshot->>'document_id'::uuid
            WHERE r.id = CAST(:rid AS uuid)
            ORDER BY dv.version_number DESC
            LIMIT 1
            """
        ),
        {"rid": uuid.UUID(run_id)},
    ).first()
    if row is None or not row.document_id:
        return {}

    path = Path(row.storage_ref)
    source_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    return {
        "document_id": str(row.document_id),
        "document_version_id": str(row.version_id),
        "extracted_text": source_text,
    }


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

    doc = _resolve_document(SessionLocal(), run_id)

    pending_item = _enqueue_finding(
        SessionLocal,
        run_id,
        {
            "summary": "Interest rate of 12.5% per annum exceeds the microfinance cap of 12%.",
            "details": {
                "claim_id": "loan_agreement.interest_1",
                "rule_id": "USURY-36.1",
                "severity": "high",
                "evaluation_method": "llm",
            },
            "source_citations": [
                build_source_citation(
                    {
                        "claim_id": "loan_agreement.interest_1",
                        "claim_text": "The annual interest rate on the principal is 12.5% per annum.",
                        "citation_status": "grounded",
                        "start_offset": 1450,
                        "end_offset": 1520,
                    },
                    document_id=doc.get("document_id"),
                    document_version_id=doc.get("document_version_id"),
                    extracted_text=doc.get("extracted_text"),
                    page_number=4,
                    section_id="sec-3.1",
                    clause_ref="§3.1.2",
                )
            ],
        },
    )
    print(f"Pending finding: {pending_item}")

    decided_item = _enqueue_finding(
        SessionLocal,
        run_id,
        {
            "summary": "Repayment schedule clause omits the mandatory 30-day grace period disclosure.",
            "details": {
                "claim_id": "loan_agreement.repayment_2",
                "rule_id": "DISC-7.3",
                "severity": "medium",
                "evaluation_method": "structured",
            },
            "source_citations": [],
        },
    )
    _decide(SessionLocal, decided_item, run_id, "approved", "audit-reviewer")
    print(f"Decided finding: {decided_item} (approved)")

    print("\nVerify:")
    print(f"  curl http://localhost:8000/runs/{run_id}/findings | jq '.items'")


def _json(payload) -> str:
    import json

    return json.dumps(payload)


if __name__ == "__main__":
    main()
