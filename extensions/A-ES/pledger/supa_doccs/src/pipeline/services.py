"""Shared service functions called by both REST and MCP surfaces.

This module is the single source of truth for all business operations.
Both the FastAPI endpoints and the MCP tools call these functions —
no separate logic paths exist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from src.pipeline.approval import (
    ApprovalService,
    DecisionValue,
    InMemoryApprovalStore,
    ItemStatus,
    QueueItem,
)
from src.pipeline.config import load_config
from src.pipeline.deliverable import Deliverable
from src.pipeline.history import HistoryStore, RunHistory, get_run_history
from src.pipeline.resume import (
    ResumeFromBeginning,
    ResumeLockError,
    ResumeResult,
    ResumeStore,
    resume_run,
)
from src.pipeline.state import create_initial_state


# ---------------------------------------------------------------------------
# Store protocols
# ---------------------------------------------------------------------------


class CostStore(Protocol):
    """Protocol for querying per-step cost data."""

    def get_step_costs(self, run_id: str) -> list[dict[str, Any]]:
        """Return cost data for all steps of a run.

        Each dict contains: step_name, step_order, status, duration_ms,
        input_tokens, output_tokens, cost_usd.
        """
        ...


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CreateRunResult:
    run_id: str
    status: str
    error: Optional[str] = None


@dataclass
class RunStatusResult:
    run_id: str
    status: str
    resumed_from: Optional[str] = None
    next_node: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ApprovalListResult:
    run_id: str
    items: list[dict[str, Any]]
    total: int
    pending: int


@dataclass
class ApprovalDecisionResult:
    item_id: str
    decision: str
    success: bool
    error: Optional[str] = None


@dataclass
class DeliverableResult:
    sections: dict[str, Any]
    deliverable_hash: str


@dataclass
class RunDeliverableResult:
    """A persisted deliverable for a specific run (deliverables table)."""

    run_id: str
    deliverable_hash: str
    section_count: int
    claim_count: int
    sections: dict[str, Any]
    created_at: str


@dataclass
class HistoryResult:
    run_id: str
    entries: list[dict[str, Any]]
    total: int


@dataclass
class StageCost:
    """Cost/time breakdown for a single pipeline stage (node)."""

    stage: str
    step_order: int
    status: str
    duration_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None


@dataclass
class RunCostResult:
    """Aggregated cost breakdown for a complete pipeline run."""

    run_id: str
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    stages: list[StageCost] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Store registry (dependency injection for both surfaces)
# ---------------------------------------------------------------------------


class ServiceRegistry:
    """Holds all store/service references for DI.

    Both the REST layer and MCP layer read from here.
    """

    def __init__(self) -> None:
        self.run_store: Optional[Any] = None
        self.resume_store: Optional[Any] = None
        self.history_store: Optional[Any] = None
        self.approval_service: Optional[ApprovalService] = None
        self.deliverable: Optional[Deliverable] = None
        self.cost_store: Optional[CostStore] = None

    def configure(
        self,
        run_store: Any = None,
        resume_store: Any = None,
        history_store: Any = None,
        approval_service: ApprovalService | None = None,
        deliverable: Deliverable | None = None,
        cost_store: CostStore | None = None,
    ) -> None:
        if run_store is not None:
            self.run_store = run_store
        if resume_store is not None:
            self.resume_store = resume_store
        if history_store is not None:
            self.history_store = history_store
        if approval_service is not None:
            self.approval_service = approval_service
        if deliverable is not None:
            self.deliverable = deliverable
        if cost_store is not None:
            self.cost_store = cost_store


# Singleton registry
registry = ServiceRegistry()


# ---------------------------------------------------------------------------
# Service functions — called by both REST and MCP
# ---------------------------------------------------------------------------


def create_run(
    document_id: str,
    document_version_id: str,
    config_overrides: dict | None = None,
) -> CreateRunResult:
    """Create a new pipeline run.

    Validates input, generates run_id, freezes config, persists the run row.
    """
    if not registry.run_store:
        return CreateRunResult(run_id="", status="error", error="Run store not configured")

    run_id = str(uuid.uuid4())

    try:
        config = load_config(config_overrides)
    except ValueError as e:
        return CreateRunResult(run_id="", status="error", error=str(e))

    if not registry.run_store.acquire_run_lock(run_id):
        return CreateRunResult(
            run_id="", status="error",
            error=f"Cannot create run {run_id}: lock already held",
        )

    # Build initial state (validates construction)
    create_initial_state(
        run_id=run_id,
        document_id=document_id,
        document_version_id=document_version_id,
        config=config,
    )

    registry.run_store.create_run(
        run_id=run_id,
        document_id=document_id,
        document_version_id=document_version_id,
        config_snapshot=dict(config),
    )

    return CreateRunResult(run_id=run_id, status="created")


def get_run_status(run_id: str) -> RunStatusResult:
    """Get the status of a pipeline run by resuming/checking checkpoint."""
    if not registry.resume_store:
        return RunStatusResult(run_id=run_id, status="error", error="Resume store not configured")

    try:
        result = resume_run(store=registry.resume_store, run_id=run_id)
    except ResumeLockError as e:
        return RunStatusResult(run_id=run_id, status="locked", error=str(e))

    if isinstance(result, ResumeFromBeginning):
        return RunStatusResult(
            run_id=run_id,
            status="pending",
            next_node=result.next_node,
        )

    return RunStatusResult(
        run_id=run_id,
        status="in_progress",
        resumed_from=result.resumed_from_step,
        next_node=result.next_node,
    )


def list_pending_approvals(run_id: str) -> ApprovalListResult:
    """List all pending approval items for a run."""
    if not registry.approval_service:
        return ApprovalListResult(run_id=run_id, items=[], total=0, pending=0)

    all_items = registry.approval_service.get_all(run_id)
    pending_count = sum(1 for i in all_items if i.status == ItemStatus.PENDING)

    items_data = [
        {
            "id": item.id,
            "run_id": item.run_id,
            "item_type": item.item_type,
            "payload": item.payload,
            "status": item.status.value,
            "queued_at": item.queued_at.isoformat(),
            "decided_at": item.decided_at.isoformat() if item.decided_at else None,
            "decision": item.decision.value if item.decision else None,
            "reviewer_id": item.reviewer_id,
            "justification": item.justification,
        }
        for item in all_items
    ]

    return ApprovalListResult(
        run_id=run_id,
        items=items_data,
        total=len(all_items),
        pending=pending_count,
    )


def decide_approval_item(
    item_id: str,
    decision: str,
    reviewer_id: str,
    justification: str,
) -> ApprovalDecisionResult:
    """Approve or reject a single approval queue item."""
    if not registry.approval_service:
        return ApprovalDecisionResult(
            item_id=item_id, decision=decision, success=False,
            error="Approval service not configured",
        )

    if decision not in ("approved", "rejected"):
        return ApprovalDecisionResult(
            item_id=item_id, decision=decision, success=False,
            error=f"Invalid decision: {decision}. Must be 'approved' or 'rejected'.",
        )

    decision_enum = DecisionValue(decision)
    result = registry.approval_service.decide(
        item_id=item_id,
        decision=decision_enum,
        reviewer_id=reviewer_id,
        justification=justification,
    )

    return ApprovalDecisionResult(
        item_id=result.item_id,
        decision=result.decision.value,
        success=result.success,
        error=result.error,
    )


def get_deliverable() -> DeliverableResult:
    """Get the current deliverable with all section hashes."""
    if not registry.deliverable:
        return DeliverableResult(sections={}, deliverable_hash="")

    registry.deliverable.compute_all_hashes()

    sections_data: dict[str, Any] = {}
    for key, section in registry.deliverable.sections.items():
        sections_data[key] = {
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

    return DeliverableResult(
        sections=sections_data,
        deliverable_hash=registry.deliverable.deliverable_hash,
    )


def get_run_deliverable(
    run_id: str, session_factory: Any = None
) -> Optional[RunDeliverableResult]:
    """Fetch the persisted deliverable for a run, or None if not finalized.

    Reads the `deliverables` table written by the finalize node — the
    same source the incremental flow now shares. Used identically by the
    REST endpoint and the MCP get_deliverable tool.

    Args:
        run_id: The pipeline run identifier.
        session_factory: Optional SQLAlchemy sessionmaker override
            (defaults to the application SessionLocal; injectable for tests).
    """
    from src.pipeline.deliverable_store import load_deliverable_record

    if session_factory is None:
        from src.database import SessionLocal as _SessionLocal

        session_factory = _SessionLocal

    record = load_deliverable_record(session_factory, run_id)
    if record is None:
        return None
    return RunDeliverableResult(
        run_id=record["run_id"],
        deliverable_hash=record["deliverable_hash"],
        section_count=record["section_count"],
        claim_count=record["claim_count"],
        sections=record["sections"],
        created_at=record["created_at"],
    )


def get_change_history(run_id: str) -> HistoryResult:
    """Get the full change history for a pipeline run."""
    if not registry.history_store:
        return HistoryResult(run_id=run_id, entries=[], total=0)

    history = get_run_history(store=registry.history_store, run_id=run_id)

    entries_data = [
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

    return HistoryResult(
        run_id=run_id,
        entries=entries_data,
        total=history.total,
    )


def get_run_cost(run_id: str) -> RunCostResult:
    """Get per-stage cost and time breakdown for a pipeline run.

    Queries all run_steps for the given run_id and aggregates cost data
    into a total plus per-stage breakdown.
    """
    if not registry.cost_store:
        return RunCostResult(run_id=run_id, error="Cost store not configured")

    step_rows = registry.cost_store.get_step_costs(run_id)

    if not step_rows:
        return RunCostResult(run_id=run_id, stages=[])

    stages: list[StageCost] = []
    total_duration = 0
    total_input = 0
    total_output = 0
    total_cost = 0.0

    for row in step_rows:
        duration = row.get("duration_ms")
        inp_tokens = row.get("input_tokens")
        out_tokens = row.get("output_tokens")
        cost = row.get("cost_usd")

        stages.append(
            StageCost(
                stage=row["step_name"],
                step_order=row["step_order"],
                status=row["status"],
                duration_ms=duration,
                input_tokens=inp_tokens,
                output_tokens=out_tokens,
                cost_usd=float(cost) if cost is not None else None,
            )
        )

        if duration is not None:
            total_duration += duration
        if inp_tokens is not None:
            total_input += inp_tokens
        if out_tokens is not None:
            total_output += out_tokens
        if cost is not None:
            total_cost += float(cost)

    return RunCostResult(
        run_id=run_id,
        total_duration_ms=total_duration,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cost_usd=round(total_cost, 6),
        stages=stages,
    )
