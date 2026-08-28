"""FastAPI router for the approval gate — programmatic approve/reject.

Provides REST endpoints to:
- List pending items for a run
- Get a single item's status
- Approve or reject an item (the critical callable operation)

These endpoints are designed to be driven programmatically (by another
service, CLI tool, or MCP tool) — not only via UI.

Invariants enforced (docs/invariants.md §5):
- Each decision is atomic and independent.
- Rejecting item X has zero effect on item Y.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.pipeline.approval import (
    ApprovalService,
    DecisionValue,
    InMemoryApprovalStore,
    ItemStatus,
    QueueItem,
)


# --- Request/Response models ---


class DecisionRequest(BaseModel):
    """Request body for approving or rejecting a queue item."""

    decision: str = Field(
        ..., pattern="^(approved|rejected)$",
        description="Must be 'approved' or 'rejected'"
    )
    reviewer_id: str = Field(..., min_length=1, max_length=128)
    justification: str = Field(..., min_length=1, max_length=2000)


class QueueItemResponse(BaseModel):
    """Response representing a single queue item."""

    id: str
    run_id: str
    item_type: str
    payload: dict[str, Any]
    status: str
    queued_at: str
    decided_at: Optional[str] = None
    decision: Optional[str] = None
    reviewer_id: Optional[str] = None
    justification: Optional[str] = None


class DecisionResponse(BaseModel):
    """Response for a decision operation."""

    item_id: str
    decision: str
    success: bool
    error: Optional[str] = None


class QueueListResponse(BaseModel):
    """Response for listing queue items."""

    run_id: str
    items: list[QueueItemResponse]
    total: int
    pending: int


# --- Dependency injection ---

_approval_service: Optional[ApprovalService] = None
_queue_context_provider: Optional[Any] = None


def set_approval_service(service: Optional[ApprovalService]) -> None:
    """Set the approval service (for testing/configuration)."""
    global _approval_service
    _approval_service = service


def set_queue_context_provider(provider: Optional[Any]) -> None:
    """Set the per-run review-context provider (read-side enrichment).

    Called with a run_id, returns the context dict used to surface
    retries / rule text / confidence+threshold / escalation reason on
    queue items. Injectable for testing; None disables enrichment.
    """
    global _queue_context_provider
    _queue_context_provider = provider


def get_approval_service() -> ApprovalService:
    """Get the current approval service."""
    if _approval_service is None:
        raise HTTPException(
            status_code=503,
            detail="Approval service not configured",
        )
    return _approval_service


# --- Helpers ---


def _item_to_response(item: QueueItem) -> QueueItemResponse:
    """Convert a QueueItem to its API response form."""
    return QueueItemResponse(
        id=item.id,
        run_id=item.run_id,
        item_type=item.item_type,
        payload=_enrich_payload(item.run_id, item.payload),
        status=item.status.value,
        queued_at=item.queued_at.isoformat(),
        decided_at=item.decided_at.isoformat() if item.decided_at else None,
        decision=item.decision.value if item.decision else None,
        reviewer_id=item.reviewer_id,
        justification=item.justification,
    )


def _enrich_payload(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach read-side provenance fields when a provider is wired."""
    if _queue_context_provider is None:
        return payload
    try:
        context = _queue_context_provider(run_id)
    except Exception:
        # Enrichment must never break serving the queue.
        return payload
    if not context:
        return payload
    from src.pipeline.queue_enrichment import enrich_item_details

    return enrich_item_details(payload, context)


# --- Router ---

router = APIRouter(prefix="/approval", tags=["approval"])


class AllPendingResponse(BaseModel):
    """Response for listing all pending items across runs."""

    items: list[QueueItemResponse]
    total: int


@router.get("/pending", response_model=AllPendingResponse)
def list_all_pending(
    service: ApprovalService = Depends(get_approval_service),
) -> AllPendingResponse:
    """List all pending approval items across all recent runs.

    Provides a lightweight cross-run view of everything awaiting review.
    Items are sorted by queued_at (most recent first).
    """
    items = service.get_all_pending()
    # Sort by queued_at descending
    items.sort(key=lambda i: i.queued_at, reverse=True)

    return AllPendingResponse(
        items=[_item_to_response(i) for i in items],
        total=len(items),
    )


@router.get("/runs/{run_id}/queue", response_model=QueueListResponse)
def list_queue(
    run_id: str,
    service: ApprovalService = Depends(get_approval_service),
) -> QueueListResponse:
    """List all approval queue items for a run.

    Returns all items regardless of status, with counts.
    """
    items = service.get_all(run_id)
    pending_count = sum(1 for i in items if i.status == ItemStatus.PENDING)

    return QueueListResponse(
        run_id=run_id,
        items=[_item_to_response(i) for i in items],
        total=len(items),
        pending=pending_count,
    )


@router.get("/items/{item_id}", response_model=QueueItemResponse)
def get_item(
    item_id: str,
    service: ApprovalService = Depends(get_approval_service),
) -> QueueItemResponse:
    """Get a single queue item by ID."""
    item = service.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")
    return _item_to_response(item)


@router.post("/items/{item_id}/decide", response_model=DecisionResponse)
def decide_item(
    item_id: str,
    request: DecisionRequest,
    service: ApprovalService = Depends(get_approval_service),
) -> DecisionResponse:
    """Approve or reject a single queue item.

    This is the critical callable endpoint: a program can drive approval
    without a human clicking through a UI.

    - Approving/rejecting one item has zero effect on other items in the queue.
    - The operation is atomic: either the decision is fully recorded or it fails.
    - Items can only be decided once (pending → approved/rejected is one-way).

    Returns 200 on success, 404 if item not found, 409 if already decided.
    """
    decision = DecisionValue(request.decision)
    result = service.decide(
        item_id=item_id,
        decision=decision,
        reviewer_id=request.reviewer_id,
        justification=request.justification,
    )

    if not result.success:
        if "not found" in (result.error or "").lower():
            raise HTTPException(status_code=404, detail=result.error)
        else:
            raise HTTPException(status_code=409, detail=result.error)

    return DecisionResponse(
        item_id=result.item_id,
        decision=result.decision.value,
        success=True,
    )
