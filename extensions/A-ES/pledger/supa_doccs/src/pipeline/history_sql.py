"""SQL-backed HistoryStore and audit-event writers.

Phase 5.2's GET /runs/{id}/history returned "History store not
configured" because nothing was ever wired into set_history_store(), and
the only attempted writers (incremental flow) used enum values that
violate migration 006's CHECK constraints — failing silently.

This module provides:
- ``emit_audit_event``: single INSERT path into the append-only
  audit_events table, constrained to the schema's allowed enums.
- ``SQLHistoryStore``: reads events for a run, matching events whose
  entity IS the run or whose new_state embeds run_id.
- Typed helpers for the three state-changing event sources:
  node completion, approval decision, incremental update.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


def emit_audit_event(
    session_factory: sessionmaker,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: str,
    previous_state: Optional[dict] = None,
    new_state: Optional[dict] = None,
    source_ref: Optional[str] = None,
) -> None:
    """Append one row to audit_events. Raises on constraint violations.

    Allowed entity_type (migration 006): document | document_version |
    claim | source_location | run | run_step | approval_queue | decision
    Allowed action: created | updated | status_changed | deleted
    """
    with session_factory() as session:  # type: Session
        session.execute(
            text(
                """
                INSERT INTO audit_events
                    (event_timestamp, entity_type, entity_id, action,
                     actor_id, previous_state, new_state, source_ref)
                VALUES
                    (:ts, :etype, CAST(:eid AS uuid), :action,
                     :actor, CAST(:prev AS jsonb), CAST(:new AS jsonb),
                     :source_ref)
                """
            ),
            {
                "ts": datetime.now(timezone.utc),
                "etype": entity_type,
                "eid": str(entity_id),
                "action": action,
                "actor": actor_id[:128],
                "prev": _json(previous_state) if previous_state is not None else None,
                "new": _json(new_state or {}),
                "source_ref": source_ref[:128] if source_ref else None,
            },
        )
        session.commit()


class SQLHistoryStore:
    """HistoryStore backed by the audit_events table."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def get_events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """All events for a run, oldest first.

        Matches events where the entity IS the run (entity_type='run',
        entity_id == run_id) OR the event's new_state embeds run_id
        (claims, decisions, steps, incremental updates).
        """
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    """
                    SELECT id, event_timestamp, entity_type, entity_id,
                           action, actor_id, previous_state, new_state,
                           source_ref
                    FROM audit_events
                    WHERE (entity_type = 'run' AND entity_id::text = :rid)
                       OR new_state->>'run_id' = :rid
                    ORDER BY event_timestamp ASC, id ASC
                    """
                ),
                {"rid": str(run_id)},
            ).mappings().all()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Typed writers for the three state-changing sources
# ---------------------------------------------------------------------------


def emit_node_completed(
    session_factory: sessionmaker,
    run_id: str,
    node_name: str,
    node_status: str,
    duration_ms: int | None = None,
    source_ref: Optional[str] = None,
) -> None:
    """Node-completion event. Written by the executor after checkpoint."""
    new_state: dict[str, Any] = {
        "run_id": run_id,
        "type": "node_completed",
        "node": node_name,
        "node_status": node_status,
    }
    if duration_ms is not None:
        new_state["duration_ms"] = duration_ms
    emit_audit_event(
        session_factory,
        entity_type="run",
        entity_id=run_id,
        action="status_changed",
        actor_id=f"node:{node_name}",
        new_state=new_state,
        source_ref=source_ref,
    )


def emit_run_status_changed(
    session_factory: sessionmaker,
    run_id: str,
    old_status: Optional[str],
    new_status: str,
) -> None:
    """Run lifecycle transition (running/completed/failed/cancelled)."""
    emit_audit_event(
        session_factory,
        entity_type="run",
        entity_id=run_id,
        action="status_changed",
        actor_id="executor",
        previous_state={"status": old_status} if old_status else None,
        new_state={"run_id": run_id, "type": "run_status", "status": new_status},
    )


def emit_decision_event(
    session_factory: sessionmaker,
    item_id: str,
    run_id: str,
    decision: str,
    reviewer_id: str,
    justification: str,
) -> None:
    """Approval-decision event."""
    emit_audit_event(
        session_factory,
        entity_type="decision",
        entity_id=item_id,
        action="created",
        actor_id=reviewer_id,
        previous_state={"status": "pending"},
        new_state={
            "run_id": run_id,
            "type": "approval_decision",
            "decision": decision,
            "justification": justification,
        },
    )


def emit_incremental_update_event(
    session_factory: sessionmaker,
    run_id: str,
    pile_id: str,
    new_document_id: str,
    affected_sections: list[str],
    conflicts_detected: int,
    approval_items_created: int,
    hashes_before: dict[str, str],
    hashes_after: dict[str, str],
) -> None:
    """Incremental-update event (schema-conforming rewrite of the
    incremental flow's previously-rejected write)."""
    emit_audit_event(
        session_factory,
        entity_type="run",
        entity_id=run_id,
        action="updated",
        actor_id="incremental_api",
        previous_state={"section_hashes": hashes_before},
        new_state={
            "run_id": run_id,
            "type": "incremental_update",
            "pile_id": pile_id,
            "affected_sections": sorted(affected_sections),
            "conflicts_detected": conflicts_detected,
            "approval_items_created": approval_items_created,
        },
        source_ref=new_document_id,
    )


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload)
