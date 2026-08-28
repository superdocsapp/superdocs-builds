"""History service — MCP-equivalent callable for querying run history.

Provides the same capability as the GET /runs/{id}/history REST endpoint
but as a direct callable function, suitable for use as an MCP tool or
programmatic integration without HTTP overhead.

Backs onto the same audit_events table — does NOT reconstruct from logs.
For any point in time, answers: what changed, when, and because of which
source document.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from src.pipeline.history import (
    HistoryEntry,
    HistoryStore,
    RunHistory,
    get_run_history,
)


# ---------------------------------------------------------------------------
# In-memory audit store (implements HistoryStore for testing)
# ---------------------------------------------------------------------------


class InMemoryAuditStore:
    """In-memory append-only audit event store.

    Implements the HistoryStore protocol for testing and programmatic use.
    Events are stored in insertion order, filtered by run_id on query.
    Mimics PostgreSQL's append-only audit_events table behavior.
    """

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def append_event(
        self,
        run_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_id: str,
        new_state: dict[str, Any],
        previous_state: Optional[dict[str, Any]] = None,
        source_ref: Optional[str] = None,
        event_timestamp: Optional[datetime] = None,
    ) -> str:
        """Append an audit event to the store.

        This is the write side — mirrors INSERT into audit_events table.
        Once written, events are immutable (append-only).

        Args:
            run_id: The pipeline run this event belongs to.
            entity_type: What was changed (claim, section, deliverable, etc.).
            entity_id: ID of the entity that was changed.
            action: Type of change (created, updated, status_changed).
            actor_id: Who/what caused the change (node name, watcher, user).
            new_state: State after the change.
            previous_state: State before the change (None for 'created').
            source_ref: Source document ID that caused this change.
            event_timestamp: When it happened. Defaults to now.

        Returns:
            The generated event ID (UUID string).
        """
        event_id = str(uuid.uuid4())
        timestamp = event_timestamp or datetime.now(timezone.utc)

        self._events.append({
            "id": event_id,
            "run_id": run_id,
            "event_timestamp": timestamp,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor_id": actor_id,
            "previous_state": previous_state,
            "new_state": new_state,
            "source_ref": source_ref,
        })

        return event_id

    def get_events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all audit events for a run, ordered by timestamp ascending.

        Implements the HistoryStore protocol.

        Args:
            run_id: The pipeline run ID to query.

        Returns:
            List of event dicts ordered by event_timestamp ASC.
        """
        matching = [
            event for event in self._events
            if event["run_id"] == run_id
        ]
        # Sort by timestamp (ascending = oldest first)
        matching.sort(key=lambda e: e["event_timestamp"])
        return matching

    @property
    def event_count(self) -> int:
        """Total number of events in the store."""
        return len(self._events)


# ---------------------------------------------------------------------------
# MCP-equivalent service function
# ---------------------------------------------------------------------------


@dataclass
class HistoryQueryResult:
    """Result of a history query — the MCP tool response format.

    Attributes:
        run_id: The queried run.
        entries: Ordered history entries (oldest first).
        total: Total count.
        success: Whether the query succeeded.
        error: Error message if failed.
    """

    run_id: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    success: bool = True
    error: Optional[str] = None


def query_run_history(
    store: HistoryStore,
    run_id: str,
) -> HistoryQueryResult:
    """Query the full change history for a pipeline run.

    MCP-equivalent of GET /runs/{id}/history. Returns the same data
    as the REST endpoint but as a structured Python object, suitable for
    tool invocations from MCP clients.

    For any point in time, answers: what changed, when, and because of
    which source document. Backed by the audit_events table — never
    reconstructed from logs.

    Args:
        store: The history store implementation (HistoryStore protocol).
        run_id: UUID string of the pipeline run to query.

    Returns:
        HistoryQueryResult with entries in chronological order.
    """
    try:
        history = get_run_history(store=store, run_id=run_id)

        entries = [
            {
                "event_id": entry.event_id,
                "timestamp": entry.timestamp.isoformat(),
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "action": entry.action,
                "actor_id": entry.actor_id,
                "source_document_id": entry.source_document_id,
                "previous_state": entry.previous_state,
                "new_state": entry.new_state,
            }
            for entry in history.entries
        ]

        return HistoryQueryResult(
            run_id=run_id,
            entries=entries,
            total=history.total,
            success=True,
        )
    except Exception as exc:
        return HistoryQueryResult(
            run_id=run_id,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Audit-emitting wrapper for incremental updates
# ---------------------------------------------------------------------------


class AuditedIncrementalEngine:
    """Wraps the incremental update engine with audit event emission.

    Every change to the deliverable (section created, section updated,
    conflict detected) is recorded as an audit event in the store,
    with source_ref pointing to the document that caused the change.

    This ensures the /runs/{id}/history endpoint (and MCP equivalent)
    can answer "what changed, when, and because of which source document"
    for every modification.
    """

    def __init__(
        self,
        audit_store: InMemoryAuditStore,
        run_id: str,
    ) -> None:
        self._audit_store = audit_store
        self._run_id = run_id

    def record_section_created(
        self,
        section_key: str,
        new_state: dict[str, Any],
        source_document_id: str,
        actor_id: str = "watcher",
    ) -> str:
        """Record that a new section was created in the deliverable.

        Args:
            section_key: The section identifier (e.g., "loan_agreement.interest_rate").
            new_state: The section's content after creation.
            source_document_id: Document that caused this creation.
            actor_id: Who/what triggered the change.

        Returns:
            The audit event ID.
        """
        return self._audit_store.append_event(
            run_id=self._run_id,
            entity_type="section",
            entity_id=section_key,
            action="created",
            actor_id=actor_id,
            new_state=new_state,
            previous_state=None,
            source_ref=source_document_id,
        )

    def record_section_updated(
        self,
        section_key: str,
        previous_state: dict[str, Any],
        new_state: dict[str, Any],
        source_document_id: str,
        actor_id: str = "watcher",
    ) -> str:
        """Record that an existing section was updated.

        Args:
            section_key: The section identifier.
            previous_state: Section content before the update.
            new_state: Section content after the update.
            source_document_id: Document that caused this update.
            actor_id: Who/what triggered the change.

        Returns:
            The audit event ID.
        """
        return self._audit_store.append_event(
            run_id=self._run_id,
            entity_type="section",
            entity_id=section_key,
            action="updated",
            actor_id=actor_id,
            new_state=new_state,
            previous_state=previous_state,
            source_ref=source_document_id,
        )

    def record_conflict_detected(
        self,
        section_key: str,
        conflict_details: dict[str, Any],
        source_document_id: str,
        actor_id: str = "watcher",
    ) -> str:
        """Record that a conflict was detected and routed to approval queue.

        Args:
            section_key: The section where the conflict occurred.
            conflict_details: Full conflict context (old/new values).
            source_document_id: Document that caused the conflict.
            actor_id: Who/what triggered the detection.

        Returns:
            The audit event ID.
        """
        return self._audit_store.append_event(
            run_id=self._run_id,
            entity_type="conflict",
            entity_id=section_key,
            action="created",
            actor_id=actor_id,
            new_state=conflict_details,
            previous_state=None,
            source_ref=source_document_id,
        )
