"""Approval gate service — programmatic approve/reject for queued items.

Provides the core business logic for the approval queue: enqueue items,
decide (approve/reject) individual items, and query queue state. Each
decision is atomic and independent — deciding one item never affects another.

Design:
- Items are scoped by run_id (a batch = all pending items for a run).
- Each item has a lifecycle: pending → approved | rejected.
- Decisions are recorded with reviewer_id and justification.
- The service is protocol-based for testability (in-memory or Postgres).

Invariants enforced (see docs/invariants.md §5):
- Rejecting item X has zero effect on item Y.
- Approving item Y does not modify any other item.
- Decisions are atomic per-item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol
import uuid


class ItemStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    # Flagged retroactively by migration 015: item was approved before the
    # zero/null-citation gap was fixed, so the approval lacks traceable
    # evidence and must be re-reviewed. Not a normal decide() target.
    APPROVED_NEEDS_RECHECK = "approved_needs_recheck"


class DecisionValue(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class QueueItem:
    """A single item in the approval queue."""

    id: str
    run_id: str
    item_type: str  # "finding", "conflict", "proposed_update"
    payload: dict[str, Any]
    status: ItemStatus = ItemStatus.PENDING
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: Optional[datetime] = None
    decision: Optional[DecisionValue] = None
    reviewer_id: Optional[str] = None
    justification: Optional[str] = None


@dataclass
class DecisionResult:
    """Result of a decide operation."""

    item_id: str
    decision: DecisionValue
    previous_status: ItemStatus
    success: bool
    error: Optional[str] = None


class ApprovalStoreError(Exception):
    """Raised on store operation failure."""
    pass


class ItemNotFoundError(ApprovalStoreError):
    """Raised when a queue item is not found."""
    pass


class ItemAlreadyDecidedError(ApprovalStoreError):
    """Raised when attempting to decide an already-decided item."""
    pass


class ApprovalStore(Protocol):
    """Protocol for approval queue persistence.

    Implementations back onto Postgres (production) or in-memory (testing).
    """

    def enqueue(self, item: QueueItem) -> None:
        """Add an item to the queue."""
        ...

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        """Retrieve a single queue item by ID."""
        ...

    def get_pending_for_run(self, run_id: str) -> list[QueueItem]:
        """Get all pending items for a given run_id."""
        ...

    def get_all_for_run(self, run_id: str) -> list[QueueItem]:
        """Get all items (any status) for a given run_id."""
        ...

    def record_decision(
        self,
        item_id: str,
        decision: DecisionValue,
        reviewer_id: str,
        justification: str,
    ) -> QueueItem:
        """Atomically record a decision on a pending item.

        Must:
        - Verify item exists and is in 'pending' status
        - Transition status to the decision value
        - Record reviewer_id, justification, decided_at
        - Return the updated item

        Raises:
            ItemNotFoundError: If item_id doesn't exist.
            ItemAlreadyDecidedError: If item is not in 'pending' status.
        """
        ...


# ---------------------------------------------------------------------------
# In-memory store implementation (for testing without Postgres)
# ---------------------------------------------------------------------------


class InMemoryApprovalStore:
    """Thread-safe in-memory implementation of ApprovalStore.

    Uses a dict keyed by item_id. Decisions are atomic because Python's
    GIL serializes dict mutations (sufficient for testing; production uses
    Postgres row-level locking).
    """

    def __init__(self) -> None:
        self._items: dict[str, QueueItem] = {}

    def enqueue(self, item: QueueItem) -> None:
        self._items[item.id] = item

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        return self._items.get(item_id)

    def get_pending_for_run(self, run_id: str) -> list[QueueItem]:
        return [
            item
            for item in self._items.values()
            if item.run_id == run_id and item.status == ItemStatus.PENDING
        ]

    def get_all_for_run(self, run_id: str) -> list[QueueItem]:
        return [
            item for item in self._items.values() if item.run_id == run_id
        ]

    def get_all_pending(self) -> list[QueueItem]:
        """Get all pending items across all runs."""
        return [
            item
            for item in self._items.values()
            if item.status == ItemStatus.PENDING
        ]

    def record_decision(
        self,
        item_id: str,
        decision: DecisionValue,
        reviewer_id: str,
        justification: str,
    ) -> QueueItem:
        item = self._items.get(item_id)
        if item is None:
            raise ItemNotFoundError(f"Queue item not found: {item_id}")
        if item.status != ItemStatus.PENDING:
            raise ItemAlreadyDecidedError(
                f"Item {item_id} is already '{item.status.value}', "
                f"cannot record decision"
            )

        # Atomic update (single item, no cross-item effects)
        item.status = ItemStatus(decision.value)
        item.decision = decision
        item.reviewer_id = reviewer_id
        item.justification = justification
        item.decided_at = datetime.now(timezone.utc)

        return item


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


class ApprovalService:
    """High-level operations on the approval queue.

    Wraps the store with validation and convenience methods.

    An optional ``decision_listener`` (set via :meth:`set_decision_listener`)
    is invoked after every successful decision so state changes reach the
    audit trail regardless of caller (REST, MCP, service layer).
    """

    def __init__(self, store: ApprovalStore) -> None:
        self._store = store
        self._decision_listener: Optional[Any] = None

    def set_decision_listener(
        self,
        listener: Any,
    ) -> None:
        """Register a callable invoked after each successful decision.

        Signature: ``(item_id, run_id, decision_str, reviewer_id,
        justification) -> None``. Listener exceptions are swallowed and
        logged — auditing must never break deciding.
        """
        self._decision_listener = listener

    def _notify_decision(
        self,
        item_id: str,
        item: QueueItem,
        decision: DecisionValue,
        reviewer_id: str,
        justification: str,
    ) -> None:
        if self._decision_listener is None:
            return
        import logging

        try:
            self._decision_listener(
                item_id,
                item.run_id,
                decision.value,
                reviewer_id,
                justification,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Decision listener failed for item %s", item_id
            )

    def enqueue_item(
        self,
        run_id: str,
        item_type: str,
        payload: dict[str, Any],
        item_id: Optional[str] = None,
    ) -> QueueItem:
        """Add a new item to the approval queue.

        Args:
            run_id: The pipeline run this item belongs to.
            item_type: Category — "finding", "conflict", or "proposed_update".
            payload: Arbitrary data describing what needs approval.
            item_id: Optional explicit ID (auto-generated if not provided).

        Returns:
            The created QueueItem.
        """
        item = QueueItem(
            id=item_id or str(uuid.uuid4()),
            run_id=run_id,
            item_type=item_type,
            payload=payload,
        )
        self._store.enqueue(item)
        return item

    def decide(
        self,
        item_id: str,
        decision: DecisionValue,
        reviewer_id: str,
        justification: str,
    ) -> DecisionResult:
        """Record a decision (approve/reject) on a single queue item.

        This is atomic per-item and has zero effect on other items.

        Args:
            item_id: ID of the queue item to decide.
            decision: "approved" or "rejected".
            reviewer_id: Who made the decision.
            justification: Reason for the decision.

        Returns:
            DecisionResult indicating success or failure.
        """
        try:
            item = self._store.record_decision(
                item_id=item_id,
                decision=decision,
                reviewer_id=reviewer_id,
                justification=justification,
            )
            self._notify_decision(
                item_id, item, decision, reviewer_id, justification
            )
            return DecisionResult(
                item_id=item_id,
                decision=decision,
                previous_status=ItemStatus.PENDING,
                success=True,
            )
        except ItemNotFoundError as e:
            return DecisionResult(
                item_id=item_id,
                decision=decision,
                previous_status=ItemStatus.PENDING,
                success=False,
                error=str(e),
            )
        except ItemAlreadyDecidedError as e:
            return DecisionResult(
                item_id=item_id,
                decision=decision,
                previous_status=ItemStatus.PENDING,
                success=False,
                error=str(e),
            )

    def get_pending(self, run_id: str) -> list[QueueItem]:
        """Get all pending items for a run."""
        return self._store.get_pending_for_run(run_id)

    def get_all(self, run_id: str) -> list[QueueItem]:
        """Get all items (any status) for a run."""
        return self._store.get_all_for_run(run_id)

    def get_item(self, item_id: str) -> Optional[QueueItem]:
        """Get a single item by ID."""
        return self._store.get_item(item_id)

    def get_all_pending(self) -> list[QueueItem]:
        """Get all pending items across all runs."""
        return self._store.get_all_pending()
