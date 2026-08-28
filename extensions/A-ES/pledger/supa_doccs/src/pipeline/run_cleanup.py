"""Run deletion — removes a run and every row that references it.

The schema uses RESTRICT foreign keys on the review chain
(decisions → approval_queue → claims ← source_locations), so a run
cannot be deleted by simply removing run_steps + claims: any claim that
was escalated to the approval queue, or that carries a source location,
blocks the delete (the exact failure seen when deleting run ee8f2b6d
from the UI).

This module owns the deletion order. deliverables is not touched —
its run_id FK cascades automatically.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def delete_run_and_dependents(session: Session, run_id: str) -> None:
    """Delete a run and all dependent rows, respecting FK order.

    Deletes, in order:
      1. decisions for the run's approval-queue entries
      2. the run's approval-queue entries (claim-backed or not)
      3. source_locations of the run's claims
      4. the run's claims
      5. the run's steps
      6. the run row itself (deliverables cascade with it)

    Caller is responsible for commit/rollback.
    """
    run_uuid = uuid.UUID(run_id)

    session.execute(
        text(
            """
            DELETE FROM decisions
            WHERE approval_queue_id IN (
                SELECT id FROM approval_queue WHERE run_id = :rid
            )
            """
        ),
        {"rid": run_uuid},
    )
    session.execute(
        text("DELETE FROM approval_queue WHERE run_id = :rid"),
        {"rid": run_uuid},
    )
    session.execute(
        text(
            """
            DELETE FROM source_locations
            WHERE claim_id IN (SELECT id FROM claims WHERE run_id = :rid)
            """
        ),
        {"rid": run_uuid},
    )
    session.execute(
        text("DELETE FROM claims WHERE run_id = :rid"),
        {"rid": run_uuid},
    )
    session.execute(
        text("DELETE FROM run_steps WHERE run_id = :rid"),
        {"rid": run_uuid},
    )
    session.execute(
        text("DELETE FROM runs WHERE id = :rid"),
        {"rid": run_uuid},
    )
