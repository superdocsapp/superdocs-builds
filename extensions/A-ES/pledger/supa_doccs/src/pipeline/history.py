"""Run history service — backed by the audit_events table.

Provides a queryable history for any pipeline run: what changed, when, and
because of which source document. Does NOT reconstruct from logs — reads
directly from the append-only audit_events table populated during pipeline
execution.

The history endpoint answers: for any point in time, what changed, when,
and because of which source document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol


@dataclass
class HistoryEntry:
    """A single event in a run's history.

    Attributes:
        event_id: Unique identifier for this audit event.
        timestamp: When the change occurred (from audit_events.event_timestamp).
        entity_type: What was changed (e.g., 'run', 'claim', 'decision').
        entity_id: The ID of the entity that was changed.
        action: The type of change ('created', 'updated', 'status_changed').
        actor_id: Who or what caused the change (node name, user, system).
        source_document_id: The source document that caused this change
            (from audit_events.source_ref, which stores the document_version_id).
        previous_state: State before the change (None for 'created' actions).
        new_state: State after the change.
    """

    event_id: str
    timestamp: datetime
    entity_type: str
    entity_id: str
    action: str
    actor_id: str
    source_document_id: Optional[str]
    previous_state: Optional[dict[str, Any]]
    new_state: dict[str, Any]


@dataclass
class RunHistory:
    """Complete ordered history for a pipeline run.

    Attributes:
        run_id: The pipeline run this history belongs to.
        entries: Ordered list of history entries (oldest first).
        total: Total number of entries.
    """

    run_id: str
    entries: list[HistoryEntry] = field(default_factory=list)
    total: int = 0


class HistoryStore(Protocol):
    """Protocol for querying audit events.

    Implementations back onto PostgreSQL (production) or in-memory stores
    (testing). The store returns audit events filtered by run_id, ordered
    by event_timestamp ascending.
    """

    def get_events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all audit events for a run, ordered by timestamp ascending.

        Each dict has keys matching the audit_events columns:
        id, event_timestamp, entity_type, entity_id, action, actor_id,
        previous_state, new_state, source_ref.

        The run_id filter matches events where:
        - entity_type == 'run' and entity_id == run_id, OR
        - new_state contains run_id (for related entities like claims, steps)

        Args:
            run_id: The pipeline run ID to query history for.

        Returns:
            List of event dicts ordered by event_timestamp ASC.
        """
        ...


def get_run_history(store: HistoryStore, run_id: str) -> RunHistory:
    """Query the audit trail and build a structured history for a run.

    Reads directly from the audit_events table — no log reconstruction.

    Args:
        store: The history store implementation.
        run_id: The pipeline run to get history for.

    Returns:
        RunHistory with entries ordered by timestamp (oldest first).
    """
    raw_events = store.get_events_for_run(run_id)

    entries: list[HistoryEntry] = []
    for event in raw_events:
        entries.append(
            HistoryEntry(
                event_id=str(event["id"]),
                timestamp=event["event_timestamp"],
                entity_type=event["entity_type"],
                entity_id=str(event["entity_id"]),
                action=event["action"],
                actor_id=event["actor_id"],
                source_document_id=event.get("source_ref"),
                previous_state=event.get("previous_state"),
                new_state=event["new_state"],
            )
        )

    return RunHistory(
        run_id=run_id,
        entries=entries,
        total=len(entries),
    )
