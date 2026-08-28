"""FastAPI router for pipeline run management.

Provides endpoints to create new pipeline runs, resume interrupted runs,
and query run history (backed by the audit_events table).
Uses dependency injection for the database layer to support testing without
a real database or LangGraph runtime.

Requirements: 6.3, 5.3
"""

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from src.database import SessionLocal
from src.models.runs import RunStep
from src.pipeline.cancel import request_cancel
from src.pipeline.config import load_config
from src.pipeline.history import HistoryStore, RunHistory, get_run_history
from src.pipeline.resume import (
    ResumeFromBeginning,
    ResumeLockError,
    ResumeResult,
    ResumeStore,
    resume_run,
)
from src.pipeline.services import CostStore, get_run_cost as get_run_cost_service
from src.pipeline.state import create_initial_state


# --- Request/Response models ---


class RunStateResponse(BaseModel):
    """Current pipeline state for canvas visualization.

    Driven directly from the LangGraph checkpointer — the frontend polls
    this endpoint and derives all node statuses from it.
    """

    run_id: str
    current_node: str
    node_status: str  # "completed" | "skipped" | "error"
    completed_nodes: list[str]
    skipped_nodes: list[dict]  # [{node_name, reason}]
    retries: dict[str, int]
    error_type: str | None = None
    error_detail: str | None = None
    run_status: str  # "running" | "completed" | "failed" | "paused"


class CreateRunRequest(BaseModel):
    """Request body for creating a new pipeline run."""

    document_id: str = Field(..., min_length=1)
    document_version_id: str = Field(..., min_length=1)
    config_overrides: dict | None = None


class CreateRunResponse(BaseModel):
    """Response for a newly created pipeline run."""

    run_id: str
    status: str


class ResumeRunResponse(BaseModel):
    """Response for a resumed pipeline run."""

    run_id: str
    status: str
    resumed_from: str | None = None
    next_node: str | None = None


class HistoryEntryResponse(BaseModel):
    """A single event in run history."""

    event_id: str
    timestamp: str
    entity_type: str
    entity_id: str
    action: str
    actor_id: str
    source_document_id: str | None = None
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any]


class RunHistoryResponse(BaseModel):
    """Complete ordered history for a pipeline run."""

    run_id: str
    entries: list[HistoryEntryResponse]
    total: int


class StageCostResponse(BaseModel):
    """Cost/time breakdown for a single pipeline stage."""

    stage: str
    step_order: int
    status: str
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class RunCostResponse(BaseModel):
    """Aggregated cost breakdown for a pipeline run."""

    run_id: str
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    stages: list[StageCostResponse] = []


class CancelRunResponse(BaseModel):
    """Response for a cancelled pipeline run."""

    run_id: str
    status: str
    message: str


# --- Database store protocol ---


class RunStore(Protocol):
    """Abstract protocol for run persistence operations.

    Implementations back onto SQLAlchemy sessions (production) or
    in-memory stores (testing).
    """

    def create_run(self, run_id: str, document_id: str, document_version_id: str, config_snapshot: dict) -> None:
        """Insert a new run row with frozen config snapshot."""
        ...

    def acquire_run_lock(self, run_id: str) -> bool:
        """Acquire advisory lock on run_id. Returns True if acquired."""
        ...

    def run_exists(self, run_id: str) -> bool:
        """Check if a run with the given ID exists."""
        ...


# --- Dependency injection ---


_run_store: Optional[Any] = None
_resume_store: Optional[Any] = None
_history_store: Optional[Any] = None


def set_run_store(store: Any) -> None:
    """Set the run store implementation (for testing/configuration)."""
    global _run_store
    _run_store = store


def set_resume_store(store: Any) -> None:
    """Set the resume store implementation (for testing/configuration)."""
    global _resume_store
    _resume_store = store


def set_history_store(store: Any) -> None:
    """Set the history store implementation (for testing/configuration)."""
    global _history_store
    _history_store = store


def get_run_store() -> Any:
    """Get the current run store implementation."""
    if _run_store is None:
        raise HTTPException(
            status_code=503,
            detail="Run store not configured",
        )
    return _run_store


def get_resume_store() -> Any:
    """Get the current resume store implementation."""
    if _resume_store is None:
        raise HTTPException(
            status_code=503,
            detail="Resume store not configured",
        )
    return _resume_store


def get_history_store() -> Any:
    """Get the current history store implementation."""
    if _history_store is None:
        raise HTTPException(
            status_code=503,
            detail="History store not configured",
        )
    return _history_store


_cost_store: Optional[Any] = None


def set_cost_store(store: Any) -> None:
    """Set the cost store implementation (for testing/configuration)."""
    global _cost_store
    _cost_store = store


def get_cost_store() -> Any:
    """Get the current cost store implementation."""
    if _cost_store is None:
        raise HTTPException(
            status_code=503,
            detail="Cost store not configured",
        )
    return _cost_store


# --- Router ---

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=CreateRunResponse)
def create_run(
    request: CreateRunRequest,
    store: Any = Depends(get_run_store),
) -> CreateRunResponse:
    """Create a new pipeline run.

    Validates input, generates a run_id (UUID), freezes configuration via
    load_config(overrides), builds initial state via create_initial_state(),
    and persists the run row. The actual graph invocation is deferred
    (will be async task in production).

    Acquires advisory lock on run_id at start to enforce single-writer.
    """
    # Generate run ID
    run_id = str(uuid.uuid4())

    # Freeze configuration with optional overrides
    try:
        config = load_config(request.config_overrides)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Acquire advisory lock
    if not store.acquire_run_lock(run_id):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot create run {run_id}: lock already held",
        )

    # Build initial state (validates that state construction works)
    initial_state = create_initial_state(
        run_id=run_id,
        document_id=request.document_id,
        document_version_id=request.document_version_id,
        config=config,
    )

    # Persist the run row with frozen config
    store.create_run(
        run_id=run_id,
        document_id=request.document_id,
        document_version_id=request.document_version_id,
        config_snapshot=dict(config),
    )

    return CreateRunResponse(run_id=run_id, status="created")


@router.post("/{run_id}/resume", response_model=ResumeRunResponse)
def resume_run_endpoint(
    run_id: str,
    store: Any = Depends(get_resume_store),
) -> ResumeRunResponse:
    """Resume a pipeline run from its last checkpoint.

    Calls resume_run which acquires an advisory lock, marks orphaned running
    rows as failed, restores state from last checkpoint, and determines the
    next node to execute.
    """
    try:
        result = resume_run(store=store, run_id=run_id)
    except ResumeLockError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if isinstance(result, ResumeFromBeginning):
        return ResumeRunResponse(
            run_id=run_id,
            status="resumed",
            resumed_from=None,
            next_node=result.next_node,
        )

    return ResumeRunResponse(
        run_id=run_id,
        status="resumed",
        resumed_from=result.resumed_from_step,
        next_node=result.next_node,
    )


@router.get("/{run_id}/history", response_model=RunHistoryResponse)
def get_run_history_endpoint(
    run_id: str,
    store: Any = Depends(get_history_store),
) -> RunHistoryResponse:
    """Get the full change history for a pipeline run.

    Returns an ordered list of all changes that occurred during this run,
    backed by the audit_events table. Each entry answers: what changed,
    when, and because of which source document.

    Events are returned in chronological order (oldest first).

    This does NOT reconstruct history from logs — it reads directly from
    the append-only audit trail populated during pipeline execution.
    """
    history = get_run_history(store=store, run_id=run_id)

    entries = [
        HistoryEntryResponse(
            event_id=entry.event_id,
            timestamp=entry.timestamp.isoformat(),
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            action=entry.action,
            actor_id=entry.actor_id,
            source_document_id=entry.source_document_id,
            previous_state=entry.previous_state,
            new_state=entry.new_state,
        )
        for entry in history.entries
    ]

    return RunHistoryResponse(
        run_id=run_id,
        entries=entries,
        total=history.total,
    )


@router.get("/{run_id}/cost", response_model=RunCostResponse)
def get_run_cost_endpoint(
    run_id: str,
) -> RunCostResponse:
    """Get per-stage cost and time breakdown for a pipeline run.

    Returns total aggregated cost/time plus a per-stage breakdown with
    duration, token counts, and estimated USD cost for each node.

    Nodes that do not call an LLM will have token/cost fields as null
    but will still report duration_ms.
    """
    result = get_run_cost_service(run_id=run_id)

    if result.error:
        raise HTTPException(status_code=503, detail=result.error)

    stages = [
        StageCostResponse(
            stage=s.stage,
            step_order=s.step_order,
            status=s.status,
            duration_ms=s.duration_ms,
            input_tokens=s.input_tokens,
            output_tokens=s.output_tokens,
            cost_usd=s.cost_usd,
        )
        for s in result.stages
    ]

    return RunCostResponse(
        run_id=result.run_id,
        total_duration_ms=result.total_duration_ms,
        total_input_tokens=result.total_input_tokens,
        total_output_tokens=result.total_output_tokens,
        total_cost_usd=result.total_cost_usd,
        stages=stages,
    )


# ─── Timing summary ──────────────────────────────────────────────────────────

# Nodes known to make LLM calls
_LLM_NODES = frozenset({
    "classify_document",
    "extract_claims",
    "match_rules",
    "match_rules_against_sources",
    "score_confidence",
})

# Nodes known to compute embeddings
_EMBED_NODES = frozenset({"embed"})


class NodeTiming(BaseModel):
    """Timing detail for a single pipeline node."""
    node: str
    duration_ms: int
    category: str  # "llm", "embedding", or "cpu"
    input_tokens: int
    output_tokens: int


class RunTimingResponse(BaseModel):
    """Aggregated timing summary for a pipeline run."""
    run_id: str
    total_wall_clock_ms: int
    llm_time_ms: int
    embedding_time_ms: int
    cpu_db_time_ms: int
    total_input_tokens: int
    total_output_tokens: int
    nodes: list[NodeTiming]


@router.get("/{run_id}/timing", response_model=RunTimingResponse)
def get_run_timing(run_id: str) -> RunTimingResponse:
    """Get a timing summary for a pipeline run.

    Breaks down total wall-clock time into:
    - llm_time_ms: time spent in nodes that call the LLM
    - embedding_time_ms: time spent computing embeddings
    - cpu_db_time_ms: time spent in pure CPU / DB / IO work

    Also reports per-node breakdown with category labels.
    """
    session = SessionLocal()
    try:
        steps = session.execute(
            select(RunStep)
            .where(RunStep.run_id == uuid.UUID(run_id))
            .order_by(RunStep.step_order)
        ).scalars().all()

        if not steps:
            raise HTTPException(status_code=404, detail="No steps found for this run")

        nodes: list[NodeTiming] = []
        llm_time = 0
        embed_time = 0
        cpu_time = 0
        total_inp = 0
        total_out = 0

        for step in steps:
            duration = step.duration_ms or 0
            inp = step.input_tokens or 0
            out = step.output_tokens or 0

            # Categorize: a node counts as "llm" only if it actually used tokens
            if step.step_name in _LLM_NODES and (inp > 0 or out > 0):
                category = "llm"
                llm_time += duration
            elif step.step_name in _EMBED_NODES and duration > 0:
                category = "embedding"
                embed_time += duration
            else:
                category = "cpu"
                cpu_time += duration

            total_inp += inp
            total_out += out

            nodes.append(NodeTiming(
                node=step.step_name,
                duration_ms=duration,
                category=category,
                input_tokens=inp,
                output_tokens=out,
            ))

        total_wall = llm_time + embed_time + cpu_time

        return RunTimingResponse(
            run_id=run_id,
            total_wall_clock_ms=total_wall,
            llm_time_ms=llm_time,
            embedding_time_ms=embed_time,
            cpu_db_time_ms=cpu_time,
            total_input_tokens=total_inp,
            total_output_tokens=total_out,
            nodes=nodes,
        )
    finally:
        session.close()


# ─── Deliverable ─────────────────────────────────────────────────────────────


class DeliverableClaimResponse(BaseModel):
    """A single claim in a deliverable section, with its citation."""

    claim_id: str
    claim_type: str
    extracted_text: str
    confidence: float
    source_document_id: str
    citation_status: str
    citation: dict[str, Any] | None = None


class DeliverableSectionResponse(BaseModel):
    """One hashed deliverable section."""

    key: str
    content_hash: str
    claims: list[DeliverableClaimResponse]


class RunDeliverableResponse(BaseModel):
    """The persisted deliverable assembled by the finalize node.

    Served from the `deliverables` table (migration 011) — available for
    any completed run, not just incremental updates.
    """

    run_id: str
    deliverable_hash: str
    section_count: int
    claim_count: int
    sections: dict[str, DeliverableSectionResponse]
    created_at: str


# ─── Conflicts ───────────────────────────────────────────────────────────────


class ConflictItemResponse(BaseModel):
    """A conflict detected during an incremental update.

    Backed by the approval_queue row (item_type='conflict') — the same
    lifecycle (pending → approved/rejected) as other review items.
    """

    id: str
    status: str  # "pending" | "approved" | "rejected"
    item_type: str = "conflict"
    queued_at: str
    decided_at: str | None = None
    decision: str | None = None
    reviewer_id: str | None = None
    justification: str | None = None
    payload: dict[str, Any]  # section_key, existing/new values + sources, reason


class RunConflictsResponse(BaseModel):
    """All conflicts detected during a run's incremental updates."""

    run_id: str
    total: int
    pending: int
    resolved: int
    items: list[ConflictItemResponse]


@router.get("/{run_id}/conflicts", response_model=RunConflictsResponse)
def get_run_conflicts_endpoint(run_id: str) -> RunConflictsResponse:
    """Fetch conflicts detected during incremental updates for a run.

    Reads approval_queue rows with item_type='conflict' — the durable,
    restart-safe record. Pending conflicts are still awaiting review;
    they are never auto-resolved.
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                """
                SELECT q.id, q.status, q.item_type, q.payload, q.queued_at,
                       q.decided_at,
                       d.decision_value, d.reviewer_id, d.justification,
                       d.decided_at AS decision_decided_at
                FROM approval_queue q
                LEFT JOIN decisions d ON d.approval_queue_id = q.id
                WHERE q.run_id = :run_id AND q.item_type = 'conflict'
                ORDER BY q.queued_at ASC
                """
            ),
            {"run_id": run_uuid},
        ).mappings().all()

        items = [
            ConflictItemResponse(
                id=str(r["id"]),
                status=r["status"],
                item_type=r["item_type"],
                queued_at=r["queued_at"].isoformat(),
                decided_at=(r["decided_at"] or r["decision_decided_at"]).isoformat()
                if (r["decided_at"] or r["decision_decided_at"])
                else None,
                decision=r["decision_value"],
                reviewer_id=r["reviewer_id"],
                justification=r["justification"],
                payload=r["payload"],
            )
            for r in rows
        ]
        pending = sum(1 for i in items if i.status == "pending")
        return RunConflictsResponse(
            run_id=run_id,
            total=len(items),
            pending=pending,
            resolved=len(items) - pending,
            items=items,
        )
    finally:
        session.close()


@router.get("/{run_id}/deliverable", response_model=RunDeliverableResponse)
def get_run_deliverable_endpoint(run_id: str) -> RunDeliverableResponse:
    """Fetch the persisted deliverable for a run.

    Returns 404 if the run has no persisted deliverable (never finalized,
    or finalized before this record existed).
    """
    from src.pipeline.services import get_run_deliverable

    result = get_run_deliverable(run_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No deliverable found for run {run_id}",
        )

    return RunDeliverableResponse(
        run_id=result.run_id,
        deliverable_hash=result.deliverable_hash,
        section_count=result.section_count,
        claim_count=result.claim_count,
        sections={
            key: DeliverableSectionResponse(
                key=s["key"],
                content_hash=s["content_hash"],
                claims=[
                    DeliverableClaimResponse(
                        claim_id=c["claim_id"],
                        claim_type=c["claim_type"],
                        extracted_text=c["extracted_text"],
                        confidence=c["confidence"],
                        source_document_id=c["source_document_id"],
                        citation_status=c["citation_status"],
                        citation=c.get("citation"),
                    )
                    for c in s["claims"]
                ],
            )
            for key, s in result.sections.items()
        },
        created_at=result.created_at,
    )


# ─── Findings (audit trail view) ─────────────────────────────────────────────


class FindingCitationResponse(BaseModel):
    """Source citation attached to a finding."""

    claim_id: str | None = None
    snippet: str | None = None
    page_number: int | None = None
    section_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    clause_ref: str | None = None
    source_document_id: str | None = None
    document_id: str | None = None
    document_version_id: str | None = None


class FindingAuditEventResponse(BaseModel):
    """One audit-trail event touching this finding."""

    event_id: str
    timestamp: str
    action: str
    actor_id: str
    details: dict[str, Any] = {}


class FindingRecordResponse(BaseModel):
    """Every finding ever generated for a run, resolved or not.

    Current status is joined from approval_queue/decisions; the event
    trail comes straight from audit_events — never reconstructed from
    the findings output alone.
    """

    finding_key: str
    claim_id: str | None = None
    rule_id: str | None = None
    description: str
    severity: str | None = None
    evaluation_method: str | None = None
    source_node: str | None = None
    playbook_id: str | None = None
    citations: list[FindingCitationResponse] = []
    status: str  # pending | approved | rejected | unqueued
    decided_by: str | None = None
    decided_at: str | None = None
    justification: str | None = None
    queued_at: str | None = None
    first_generated_at: str | None = None
    events: list[FindingAuditEventResponse] = []


class RunFindingsResponse(BaseModel):
    run_id: str
    total: int
    pending: int
    resolved: int
    items: list[FindingRecordResponse]


@router.get("/{run_id}/findings", response_model=RunFindingsResponse)
def get_run_findings_endpoint(run_id: str) -> RunFindingsResponse:
    """List every finding ever generated for a run with its full audit trail.

    Sources combined here:
      - ``audit_events``   — decision/approval events (Phase 1 audit trail),
        read directly, not reconstructed
      - ``approval_queue`` + ``decisions`` — current status, reviewer, timing
      - run step outputs   — findings that never entered the queue
        (status='unqueued') so nothing generated is invisible
      - ``claims``/``source_locations`` — citations for each finding
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    session = SessionLocal()
    try:
        # ── Run metadata: playbook id from the frozen config snapshot ──
        run_row = session.execute(
            text("SELECT config_snapshot FROM runs WHERE id = :rid"),
            {"rid": run_uuid},
        ).first()
        if run_row is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        snapshot = run_row.config_snapshot or {}
        playbook_id = snapshot.get("playbook_id") or snapshot.get("playbook")

        # ── Queue findings + current decision state ──
        queue_rows = session.execute(
            text(
                """
                SELECT q.id::text AS item_id, q.status, q.payload, q.queued_at,
                       q.claim_id::text AS claim_fk,
                       d.decision_value, d.reviewer_id,
                       d.decided_at AS d_decided_at, d.justification
                FROM approval_queue q
                LEFT JOIN decisions d ON d.approval_queue_id = q.id
                WHERE q.run_id = :rid AND q.item_type = 'finding'
                ORDER BY q.queued_at ASC
                """
            ),
            {"rid": run_uuid},
        ).mappings().all()

        item_ids = [r["item_id"] for r in queue_rows]

        # ── Audit trail for this run, read directly from audit_events ──
        events_by_item: dict[str, list[dict]] = {}
        earliest_event: dict[str, str] = {}
        event_rows = session.execute(
            text(
                """
                SELECT id::text AS event_id, event_timestamp, entity_type,
                       entity_id::text AS entity_id, action, actor_id,
                       previous_state, new_state, source_ref
                FROM audit_events
                WHERE new_state->>'run_id' = :rid_str
                   OR (entity_type = 'run' AND entity_id::text = :rid_str)
                   OR source_ref::text = :rid_str
                ORDER BY event_timestamp ASC
                """
            ),
            {
                "rid": run_uuid,
                "rid_str": str(run_uuid),
            },
        ).mappings().all()

        for ev in event_rows:
            ns = ev["new_state"] or {}
            target = ev["entity_id"]
            entry = {
                "event_id": ev["event_id"],
                "timestamp": ev["event_timestamp"].isoformat(),
                "action": ev["action"],
                "actor_id": ev["actor_id"],
                "details": {
                    k: v for k, v in ns.items() if k != "run_id"
                },
            }
            events_by_item.setdefault(target, []).append(entry)

            # Track first mention of a claim in the audit trail
            claim_ref = ns.get("claim_id")
            if isinstance(claim_ref, str) and claim_ref and (
                claim_ref not in earliest_event
                or ev["event_timestamp"].isoformat() < earliest_event[claim_ref]
            ):
                earliest_event[claim_ref] = ev["event_timestamp"].isoformat()
            if ev["source_ref"] and (
                str(ev["source_ref"]) not in earliest_event
                or ev["event_timestamp"].isoformat() < earliest_event[str(ev["source_ref"])]
            ):
                earliest_event[str(ev["source_ref"])] = ev["event_timestamp"].isoformat()

        # ── Citations: persisted claims/source_locations for this run ──
        citations_by_claim: dict[str, list[dict]] = {}
        cit_rows = session.execute(
            text(
                """
                SELECT c.id::text AS cid, sl.page_number, sl.section_id,
                       sl.start_offset, sl.end_offset, sl.clause_ref,
                       dv.document_id::text AS document_id
                FROM claims c
                LEFT JOIN source_locations sl ON sl.claim_id = c.id
                LEFT JOIN document_versions dv ON dv.id = c.document_version_id
                WHERE c.run_id = :rid
                """
            ),
            {"rid": run_uuid},
        ).mappings().all()
        for row in cit_rows:
            citations_by_claim.setdefault(row["cid"], []).append(
                {
                    "claim_id": row["cid"],
                    "page_number": row["page_number"],
                    "section_id": row["section_id"],
                    "start_offset": row["start_offset"],
                    "end_offset": row["end_offset"],
                    "clause_ref": row["clause_ref"],
                    "source_document_id": row["document_id"],
                }
            )

        # Supplement with extraction-stage spans keyed by synthetic claim ids
        extract_step = session.execute(
            select(RunStep).where(
                RunStep.run_id == run_uuid, RunStep.step_name == "extract_claims"
            )
        ).scalar_one_or_none()
        if extract_step is not None:
            doc_id = snapshot.get("document_id")
            for claim in (extract_step.output_state or {}).get("claims", []):
                cid = claim.get("claim_id")
                if cid and cid not in citations_by_claim:
                    span_fields = ("start_offset", "end_offset", "page_number", "section_id", "clause_ref")
                    citation = {f: claim[f] for f in span_fields if claim.get(f) is not None}
                    if citation:
                        citation["claim_id"] = cid
                        citation["source_document_id"] = doc_id
                        citations_by_claim[cid] = [citation]

        def _citations_for(claim_id: str | None, payload_citations: list) -> list[dict]:
            merged: list[dict] = []
            if claim_id and claim_id in citations_by_claim:
                merged.extend(citations_by_claim[claim_id])
            for c in payload_citations or []:
                loc = c.get("source_location") if isinstance(c, dict) else None
                doc_id = c.get("document_id") if isinstance(c, dict) else None
                doc_ver = (
                    c.get("document_version_id") if isinstance(c, dict) else None
                )
                if loc:
                    merged.append(
                        {
                            "claim_id": c.get("claim_id"),
                            "snippet": c.get("snippet"),
                            "page_number": loc.get("page_number"),
                            "section_id": loc.get("section_id"),
                            "start_offset": loc.get("start_offset"),
                            "end_offset": loc.get("end_offset"),
                            "clause_ref": loc.get("clause_ref"),
                            "document_id": doc_id,
                            "document_version_id": doc_ver,
                        }
                    )
                elif isinstance(c, dict):
                    merged.append(
                        {
                            "claim_id": c.get("claim_id"),
                            "snippet": c.get("snippet"),
                            "document_id": doc_id,
                            "document_version_id": doc_ver,
                        }
                    )
            return merged

        # ── Assemble queue-backed findings ──
        covered_claim_ids: set[str] = set()
        items: list[FindingRecordResponse] = []
        for r in queue_rows:
            payload = r["payload"] or {}
            details = payload.get("details", {}) or {}
            claim_id = details.get("claim_id") or payload.get("claim_id")
            if claim_id:
                covered_claim_ids.add(str(claim_id))
            decided = r["decision_value"]
            status = r["status"] if decided is None else decided
            item_events = events_by_item.get(r["item_id"], [])
            first_ts = r["queued_at"].isoformat() if r["queued_at"] else None
            for ev in item_events:
                if first_ts is None or ev["timestamp"] < first_ts:
                    first_ts = ev["timestamp"]
            decided_at = r["d_decided_at"].isoformat() if r["d_decided_at"] else None

            items.append(
                FindingRecordResponse(
                    finding_key=r["item_id"],
                    claim_id=str(claim_id) if claim_id else None,
                    rule_id=details.get("rule_id"),
                    description=payload.get("summary", ""),
                    severity=details.get("severity"),
                    evaluation_method=details.get("evaluation_method"),
                    source_node="human_review",
                    playbook_id=str(playbook_id) if playbook_id else None,
                    citations=[
                        FindingCitationResponse(**c) for c in _citations_for(claim_id, payload.get("source_citations"))
                    ],
                    status=status,
                    decided_by=r["reviewer_id"],
                    decided_at=decided_at,
                    justification=r["justification"],
                    queued_at=first_ts,
                    first_generated_at=(
                        min(filter(None, [first_ts, earliest_event.get(str(claim_id))]))
                        if (first_ts or earliest_event.get(str(claim_id)))
                        else None
                    ),
                    events=[FindingAuditEventResponse(**e) for e in item_events],
                )
            )

        # ── Unqueued findings from node outputs — still visible ──
        steps = session.execute(
            select(RunStep).where(RunStep.run_id == run_uuid)
        ).scalars().all()
        seen_keys: set[str] = set(covered_claim_ids)
        for step in steps:
            out = step.output_state or {}
            node_findings: list[dict] = []
            if step.step_name == "match_rules":
                node_findings = out.get("claim_findings", [])
            elif step.step_name == "match_rules_against_sources":
                node_findings = out.get("source_findings", [])
            elif step.step_name == "merge_findings":
                node_findings = [
                    f for f in out.get("findings", []) if f.get("source") != "match_rules_against_sources"
                ]
            for f in node_findings:
                claim_id = f.get("claim_id")
                key = f"step:{step.step_name}:{claim_id or f.get('rule_id', '')}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                items.append(
                    FindingRecordResponse(
                        finding_key=key,
                        claim_id=str(claim_id) if claim_id else None,
                        rule_id=f.get("rule_id"),
                        description=f.get("reason") or f.get("description") or f.get("finding_type", ""),
                        severity=f.get("severity"),
                        evaluation_method="llm" if f.get("source") == "match_rules" else "structured",
                        source_node=step.step_name,
                        playbook_id=str(playbook_id) if playbook_id else None,
                        citations=[
                            FindingCitationResponse(**c)
                            for c in _citations_for(str(claim_id) if claim_id else None, [])
                        ],
                        status="unqueued",
                        queued_at=step.started_at.isoformat() if step.started_at else None,
                        first_generated_at=None,
                        events=[],
                    )
                )

        pending = sum(1 for i in items if i.status == "pending")
        resolved = sum(1 for i in items if i.status in ("approved", "rejected"))
        return RunFindingsResponse(
            run_id=run_id,
            total=len(items),
            pending=pending,
            resolved=resolved,
            items=items,
        )
    finally:
        session.close()


@router.post("/{run_id}/cancel", response_model=CancelRunResponse)
def cancel_run_endpoint(
    run_id: str,
    store: Any = Depends(get_run_store),
) -> CancelRunResponse:
    """Cancel a running pipeline.

    Sets a cooperative cancellation flag. The executor checks this flag
    between node transitions and stops cleanly. All completed checkpoints
    and audit events are preserved — nothing is deleted.

    The run can be resumed later via POST /runs/{run_id}/resume.
    """
    if not store.run_exists(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    request_cancel(run_id)

    return CancelRunResponse(
        run_id=run_id,
        status="cancelling",
        message=(
            "Cancellation requested. The run will stop after the current "
            "node completes. All checkpoints are preserved."
        ),
    )
