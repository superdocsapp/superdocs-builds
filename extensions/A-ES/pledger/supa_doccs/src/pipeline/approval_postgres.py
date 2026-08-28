"""Postgres-backed implementation of the ApprovalStore protocol.

Durably persists the approval queue in the ``approval_queue`` and
``decisions`` tables (schema: migrations 005 + 010), replacing the
in-memory dict whose contents were lost on every process restart.

Semantics:
- Each item is one ``approval_queue`` row; the service contract fields
  (run_id, item_type, payload) live on that row (migration 010).
- A decision atomically inserts a ``decisions`` row and transitions the
  queue row's status inside a single transaction. The Phase 2.3 guard
  trigger (``trg_guard_decision_on_pending``) additionally rejects any
  decision insert against a non-pending entry.
- Concurrency: the queue row is locked with SELECT ... FOR UPDATE before
  the status check, so two concurrent decisions on the same item cannot
  both succeed — the loser sees status != pending and gets
  ItemAlreadyDecidedError.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from src.pipeline.approval import (
    DecisionValue,
    ItemAlreadyDecidedError,
    ItemNotFoundError,
    ItemStatus,
    QueueItem,
)

_ITEM_TYPE_MAX = 32
_JUSTIFICATION_MAX = 2000


def _row_to_item(row) -> QueueItem:
    """Map an approval_queue (+ optional decisions) row to a QueueItem."""
    return QueueItem(
        id=str(row.id),
        run_id=str(row.run_id),
        item_type=row.item_type,
        payload=row.payload,
        status=ItemStatus(row.status),
        queued_at=row.queued_at,
        decided_at=row.decided_at,
        decision=DecisionValue(row.decision_value)
        if row.decision_value is not None
        else None,
        reviewer_id=row.reviewer_id,
        justification=row.justification,
    )


def _parse_item_id(item_id: str) -> uuid.UUID:
    """Parse an item id, mapping malformed ids to ItemNotFoundError.

    The store keys items by server-generated UUIDs; any id that isn't a
    valid UUID therefore cannot exist.
    """
    try:
        return uuid.UUID(item_id)
    except (ValueError, AttributeError):
        raise ItemNotFoundError(f"Queue item not found: {item_id}")


_SELECT_ITEM_SQL = """
    SELECT q.id, q.run_id, q.item_type, q.payload, q.status,
           q.queued_at, q.decided_at, q.assigned_reviewer AS reviewer_id,
           d.justification, d.decision_value
    FROM approval_queue q
    LEFT JOIN decisions d ON d.approval_queue_id = q.id
    """


class PostgresApprovalStore:
    """ApprovalStore backed by approval_queue/decisions tables."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def enqueue(self, item: QueueItem) -> None:
        with self._session_factory() as session:  # type: Session
            session.execute(
                text(
                    """
                    INSERT INTO approval_queue
                        (id, run_id, item_type, payload, status)
                    VALUES
                        (:id, :run_id, :item_type, CAST(:payload AS jsonb),
                         :status)
                    """
                ),
                {
                    "id": uuid.UUID(item.id),
                    "run_id": uuid.UUID(item.run_id),
                    "item_type": item.item_type[:_ITEM_TYPE_MAX],
                    "payload": _json_dumps(item.payload),
                    "status": item.status.value,
                },
            )
            session.commit()

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        with self._session_factory() as session:
            row = session.execute(
                text(_SELECT_ITEM_SQL + " WHERE q.id = :id"),
                {"id": _parse_item_id(item_id)},
            ).first()
            return _row_to_item(row) if row is not None else None

    def get_pending_for_run(self, run_id: str) -> list[QueueItem]:
        return self._get_for_run(run_id, pending_only=True)

    def get_all_for_run(self, run_id: str) -> list[QueueItem]:
        return self._get_for_run(run_id, pending_only=False)

    def get_all_pending(self) -> list[QueueItem]:
        with self._session_factory() as session:
            rows = session.execute(
                text(_SELECT_ITEM_SQL + " WHERE q.status = :status ORDER BY q.queued_at"),
                {"status": ItemStatus.PENDING.value},
            ).fetchall()
            return [_row_to_item(r) for r in rows]

    def record_decision(
        self,
        item_id: str,
        decision: DecisionValue,
        reviewer_id: str,
        justification: str,
    ) -> QueueItem:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            try:
                # Lock the row so concurrent decisions serialize here.
                locked = session.execute(
                    text(
                        "SELECT id, status FROM approval_queue "
                        "WHERE id = :id FOR UPDATE"
                    ),
                    {"id": _parse_item_id(item_id)},
                ).first()
                if locked is None:
                    raise ItemNotFoundError(
                        f"Queue item not found: {item_id}"
                    )
                if locked.status != ItemStatus.PENDING.value:
                    raise ItemAlreadyDecidedError(
                        f"Item {item_id} is already '{locked.status}', "
                        f"cannot record decision"
                    )

                # Insert first (guard trigger requires status='pending'
                # at insert time), then transition the status — same
                # transaction, so they commit or roll back together.
                session.execute(
                    text(
                        """
                        INSERT INTO decisions
                            (approval_queue_id, decision_value,
                             reviewer_id, decided_at, justification)
                        VALUES (:qid, :value, :reviewer, :at, :justification)
                        """
                    ),
                    {
                        "qid": uuid.UUID(item_id),
                        "value": decision.value,
                        "reviewer": reviewer_id[:128],
                        "at": now,
                        "justification": justification[:_JUSTIFICATION_MAX],
                    },
                )
                updated = session.execute(
                    text(
                        """
                        UPDATE approval_queue
                        SET status = :status,
                            assigned_reviewer = :reviewer,
                            decided_at = :at,
                            version = version + 1
                        WHERE id = :id
                        RETURNING id, run_id, item_type, payload, status,
                                  queued_at, decided_at,
                                  assigned_reviewer AS reviewer_id
                        """
                    ),
                    {
                        "status": ItemStatus(decision.value).value,
                        "reviewer": reviewer_id[:128],
                        "at": now,
                        "id": uuid.UUID(item_id),
                    },
                ).first()
                session.commit()
                return QueueItem(
                    id=str(updated.id),
                    run_id=str(updated.run_id),
                    item_type=updated.item_type,
                    payload=updated.payload,
                    status=ItemStatus(updated.status),
                    queued_at=updated.queued_at,
                    decided_at=updated.decided_at,
                    decision=decision,
                    reviewer_id=updated.reviewer_id,
                    justification=justification[:_JUSTIFICATION_MAX],
                )
            except Exception:
                session.rollback()
                raise

    # ------------------------------------------------------------------

    def _get_for_run(self, run_id: str, pending_only: bool) -> list[QueueItem]:
        sql_str = _SELECT_ITEM_SQL + " WHERE q.run_id = :run_id"
        params: dict = {"run_id": uuid.UUID(run_id)}
        if pending_only:
            sql_str += " AND q.status = :status"
            params["status"] = ItemStatus.PENDING.value
        sql_str += " ORDER BY q.queued_at"
        with self._session_factory() as session:
            rows = session.execute(text(sql_str), params).fetchall()
            return [_row_to_item(r) for r in rows]


def _json_dumps(payload) -> str:
    import json

    return json.dumps(payload)
