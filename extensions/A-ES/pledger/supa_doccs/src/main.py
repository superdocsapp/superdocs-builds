"""FastAPI application entry point — wires all routers and services.

Mounts:
- /documents — file upload and listing
- /runs — pipeline run management (create, state, history, cost)
- /approval — approval queue management
- /health — health check
- /runs/{run_id}/stream — SSE endpoint for live pipeline updates
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select, text

# Load environment variables from .env
load_dotenv()

from src.database import SessionLocal, engine
from src.models.documents import Document, DocumentVersion
from src.models.piles import Pile, PileDocument
from src.models.runs import Run, RunStep
from src.pipeline.approval import ApprovalService
from src.pipeline.citation_payload import (
    build_source_citation,
    resolve_evaluation_method,
)
from src.pipeline.approval_api import router as approval_router, set_approval_service
from src.pipeline.approval_postgres import PostgresApprovalStore
from src.pipeline.api import router as runs_router
from src.pipeline.incremental_api import (
    router as incremental_router,
    set_incremental_approval_service,
)
from src.pipeline.piles_api import router as piles_router
from src.pipeline.upload_api import router as upload_router

logger = logging.getLogger(__name__)

# ─── Global state for SSE ─────────────────────────────────────────────────────

# Map of run_id → list of asyncio.Queue for SSE subscribers
_sse_subscribers: dict[str, list[asyncio.Queue]] = {}


def get_sse_queue(run_id: str) -> asyncio.Queue:
    """Create and register an SSE subscriber queue for a run."""
    if run_id not in _sse_subscribers:
        _sse_subscribers[run_id] = []
    queue: asyncio.Queue = asyncio.Queue()
    _sse_subscribers[run_id].append(queue)
    return queue


def remove_sse_queue(run_id: str, queue: asyncio.Queue) -> None:
    """Remove a subscriber queue when the client disconnects."""
    if run_id in _sse_subscribers:
        try:
            _sse_subscribers[run_id].remove(queue)
        except ValueError:
            pass
        if not _sse_subscribers[run_id]:
            del _sse_subscribers[run_id]


async def broadcast_sse(run_id: str, data: dict) -> None:
    """Broadcast an event to all SSE subscribers for a run."""
    if run_id in _sse_subscribers:
        for queue in _sse_subscribers[run_id]:
            try:
                await queue.put(data)
            except Exception:
                pass


# ─── Application lifecycle ────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    # Initialize approval service with Postgres-backed store
    # (durable across restarts via approval_queue/decisions tables).
    store = PostgresApprovalStore(SessionLocal)
    service = ApprovalService(store)
    set_approval_service(service)
    # Approval decisions land in the audit trail for /runs/{id}/history.
    from src.pipeline.history_sql import emit_decision_event as _emit_decision

    def _decision_listener(item_id, run_id, decision, reviewer_id, justification):
        _emit_decision(
            SessionLocal,
            item_id=item_id,
            run_id=run_id,
            decision=decision,
            reviewer_id=reviewer_id,
            justification=justification,
        )

    service.set_decision_listener(_decision_listener)
    # extract_claims node persists claims/source_locations at node
    # completion (durable record); checkpoint JSONB stays for resumability.
    from src.pipeline.nodes.extract_claims import set_claim_persister
    from src.pipeline.source_linker import make_sql_claim_persister

    set_claim_persister(make_sql_claim_persister(SessionLocal))

    # Phase 5.2: history endpoint reads the audit_events table.
    from src.pipeline.api import set_history_store
    from src.pipeline.history_sql import SQLHistoryStore

    set_history_store(SQLHistoryStore(SessionLocal))

    # Cost endpoint: same durable pattern as history — read run_steps
    # from Postgres so cost data survives process restarts (B4 gap).
    from src.pipeline.services import registry
    from src.pipeline.stores import SQLCostStore

    registry.configure(cost_store=SQLCostStore(SessionLocal))

    # Review-queue enrichment: read-side join over run_steps/config so the
    # review page can surface retries, rule text, confidence+threshold and
    # escalation reason without recomputing anything.
    from src.pipeline.approval_api import set_queue_context_provider
    from src.pipeline.queue_enrichment import make_db_context_provider

    set_queue_context_provider(make_db_context_provider(SessionLocal))

    set_incremental_approval_service(service)
    logger.info("Application started. Approval service configured.")
    yield
    set_approval_service(None)
    set_incremental_approval_service(None)
    set_claim_persister(None)
    set_history_store(None)
    set_queue_context_provider(None)
    registry.cost_store = None
    logger.info("Application shutdown.")


# ─── App creation ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Agentic Document Intelligence",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(upload_router)
from src.pipeline.facts_api import router as facts_router
app.include_router(facts_router)
app.include_router(approval_router)
app.include_router(runs_router)
app.include_router(piles_router)
app.include_router(incremental_router)


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ─── Run management ──────────────────────────────────────────────────────────


class StartPipelineRequest(BaseModel):
    """Request to start a pipeline run.

    Supply pile_id to run against all documents in a pile (preferred).
    Supply document_id + document_version_id for legacy single-doc mode.
    Both can be provided — pile_id is recorded on the run either way.
    """
    document_id: Optional[str] = None
    document_version_id: Optional[str] = None
    pile_id: Optional[str] = None
    config_overrides: Optional[dict] = None


class StartPipelineResponse(BaseModel):
    """Response after starting a pipeline run.

    run_id is the primary run (the first document). For pile starts,
    run_ids carries every per-document run created for the pile.
    """
    run_id: str
    run_ids: list[str] = []
    status: str


class RunListItem(BaseModel):
    """Summary of a pipeline run."""
    id: str
    status: str
    started_at: str
    document_id: Optional[str] = None
    filename: Optional[str] = None
    pile_id: Optional[str] = None
    pile_name: Optional[str] = None
    needs_recheck_count: int = 0


@app.post("/runs/start", response_model=StartPipelineResponse)
async def start_pipeline(
    request: StartPipelineRequest,
    background_tasks: BackgroundTasks,
) -> StartPipelineResponse:
    """Start a new pipeline run.

    Accepts pile_id (preferred) to run against all documents in the pile,
    or document_id + document_version_id for legacy single-document mode.
    When pile_id is provided without document fields, the first document
    in the pile is used as the primary pipeline input. The full pile
    document list is recorded in config_snapshot.pile_document_ids.
    """
    session = SessionLocal()
    try:
        pile_uuid = None
        pile_document_ids: list[str] = []

        # --- Resolve pile if provided ---
        if request.pile_id:
            pile = session.execute(
                select(Pile).where(Pile.id == uuid.UUID(request.pile_id))
            ).scalar_one_or_none()
            if pile is None:
                raise HTTPException(status_code=404, detail="Pile not found")
            pile_uuid = pile.id

            # Gather all documents in the pile (snapshot at run-start, invariant 12)
            pile_docs = session.execute(
                select(PileDocument)
                .where(PileDocument.pile_id == pile.id)
                .order_by(PileDocument.added_at)
            ).scalars().all()
            pile_document_ids = [str(pd.document_id) for pd in pile_docs]

            if not pile_document_ids:
                raise HTTPException(
                    status_code=422,
                    detail="Pile has no documents. Upload documents before starting a run.",
                )

        # --- Resolve documents to process into per-document run specs ---
        # A run executes one document's pipeline pass (run_steps is unique
        # per (run_id, step_order)), so a pile start fans out into one run
        # per pile document (invariant 10: starting a run against a pile
        # processes ALL of the pile's documents).
        run_specs: list[dict] = []

        if request.document_id and request.document_version_id:
            # Explicit single-document mode (or pile + explicit primary doc)
            doc = session.execute(
                select(Document).where(Document.id == uuid.UUID(request.document_id))
            ).scalar_one_or_none()
            if doc is None:
                raise HTTPException(status_code=404, detail="Document not found")

            version = session.execute(
                select(DocumentVersion).where(
                    DocumentVersion.id == uuid.UUID(request.document_version_id)
                )
            ).scalar_one_or_none()
            if version is None:
                raise HTTPException(status_code=404, detail="Document version not found")

            run_specs.append({
                "document_id": request.document_id,
                "document_version_id": request.document_version_id,
                "storage_path": version.storage_ref,
                "mime_type": doc.mime_type,
                "filename": doc.filename,
            })

        elif pile_document_ids:
            # Pile-first mode: one run per pile document. Validate every
            # document has a usable version and snapshot its latest version
            # now (invariant 12: the pile's document list is fixed at
            # run-start; later additions are invisible to this run).
            for pd_id in pile_document_ids:
                doc = session.execute(
                    select(Document).where(Document.id == uuid.UUID(pd_id))
                ).scalar_one_or_none()
                if doc is None:
                    raise HTTPException(status_code=500, detail=f"Pile document not found in DB: {pd_id}")

                version = session.execute(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == doc.id)
                    .order_by(DocumentVersion.version_number.desc())
                ).scalars().first()
                if version is None:
                    label = doc.filename or pd_id
                    raise HTTPException(
                        status_code=422,
                        detail=f"Pile document has no usable version: {label}. "
                               "Re-upload this document before starting the pipeline.",
                    )

                run_specs.append({
                    "document_id": str(doc.id),
                    "document_version_id": str(version.id),
                    "storage_path": version.storage_ref,
                    "mime_type": doc.mime_type,
                    "filename": doc.filename,
                })

        else:
            raise HTTPException(
                status_code=422,
                detail="Provide pile_id or both document_id and document_version_id.",
            )

        # Create one run record per document
        for spec in run_specs:
            run_id = str(uuid.uuid4())
            spec["run_id"] = run_id
            run = Run(
                id=uuid.UUID(run_id),
                status="pending",
                config_snapshot={
                    "document_id": spec["document_id"],
                    "document_version_id": spec["document_version_id"],
                    "pile_document_ids": pile_document_ids or [spec["document_id"]],
                    **(request.config_overrides or {}),
                },
                initiator="api",
                version=1,
                pile_id=pile_uuid,
            )
            session.add(run)
        session.commit()
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create run: {e}")
    finally:
        session.close()

    # Start pipeline execution in background — every document's run
    # executes, so the whole pile is analysed (invariant 10).
    background_tasks.add_task(
        _execute_pile_background,
        run_specs=run_specs,
        config_overrides=request.config_overrides,
    )

    return StartPipelineResponse(
        run_id=run_specs[0]["run_id"],
        run_ids=[spec["run_id"] for spec in run_specs],
        status="started",
    )


async def _execute_pile_background(
    run_specs: list[dict],
    config_overrides: Optional[dict] = None,
) -> None:
    """Background task that runs every per-document pipeline of a pile start.

    Documents execute sequentially: each run makes many LLM calls and the
    client has no retry/backoff, so piling on concurrent requests would
    trade fact quality for speed. Each run is an independent
    single-document pipeline writing to its own rows (invariant 12), and a
    run whose executor crashes is marked failed so it can never dangle as
    "running".
    """
    for spec in run_specs:
        await _execute_pipeline_background(
            run_id=spec["run_id"],
            document_id=spec["document_id"],
            document_version_id=spec["document_version_id"],
            storage_path=spec["storage_path"],
            mime_type=spec["mime_type"],
            filename=spec["filename"],
            config_overrides=config_overrides,
        )


async def _execute_pipeline_background(
    run_id: str,
    document_id: str,
    document_version_id: str,
    storage_path: str,
    mime_type: str,
    filename: str,
    config_overrides: Optional[dict] = None,
) -> None:
    """Background task that runs the full pipeline."""
    from src.pipeline.demo_executor import run_pipeline

    async def sse_callback(data: dict) -> None:
        await broadcast_sse(run_id, data)

    try:
        await run_pipeline(
            run_id=run_id,
            document_id=document_id,
            document_version_id=document_version_id,
            storage_path=storage_path,
            mime_type=mime_type,
            filename=filename,
            session_factory=SessionLocal,
            config_overrides=config_overrides,
            sse_callback=sse_callback,
        )
    except Exception as e:
        logger.exception("Pipeline execution failed for run %s: %s", run_id, e)
        # Update run status to failed
        session = SessionLocal()
        try:
            run = session.execute(
                select(Run).where(Run.id == uuid.UUID(run_id))
            ).scalar_one_or_none()
            if run:
                run.status = "failed"
                session.commit()
        finally:
            session.close()
        # Notify SSE subscribers
        await broadcast_sse(run_id, {
            "type": "run_complete",
            "run_id": run_id,
            "status": "failed",
            "error": str(e),
        })


def _load_seed_demo_module():
    # Import the seeding core. scripts/ is a top-level dir (not under src/),
    # so load it by file path to avoid depending on it being an installed
    # package or on the current working directory.
    import importlib.util

    seed_path = Path(__file__).resolve().parent.parent / "scripts" / "seed_demo.py"
    if not seed_path.exists():
        raise HTTPException(
            status_code=501,
            detail="Demo seeding is unavailable: scripts/seed_demo.py not found in this deployment.",
        )
    spec = importlib.util.spec_from_file_location("seed_demo", seed_path)
    seed_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_module)
    return seed_module


@app.post("/demo/seed")
async def seed_demo_endpoint() -> dict:
    """Seed the fixed demo pile (the same work `scripts/seed_demo.py` does).

    Calls the seeding logic in-process — no shell/subprocess execution and no
    caller-supplied input. Idempotent: if the demo pile is already present the
    call is a no-op and reports status "skipped". The blocking DB work runs in
    a threadpool so it does not stall the event loop.
    """
    seed_module = _load_seed_demo_module()

    try:
        result = await run_in_threadpool(seed_module.seed_demo)
    except Exception as e:
        logger.exception("Demo seed failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Demo seed failed: {e}")
    return result


@app.get("/runs")
async def list_runs() -> list[RunListItem]:
    """List all pipeline runs."""
    session = SessionLocal()
    try:
        runs = session.execute(
            select(Run).order_by(Run.started_at.desc()).limit(50)
        ).scalars().all()

        # Count recheck-flagged queue items per run in one grouped query
        recheck_counts: dict[str, int] = {}
        recheck_rows = session.execute(
            text(
                "SELECT run_id, count(*) FROM approval_queue "
                "WHERE status = 'approved_needs_recheck' AND run_id IS NOT NULL "
                "GROUP BY run_id"
            )
        ).fetchall()
        recheck_counts = {str(row[0]): int(row[1]) for row in recheck_rows}

        results = []
        for run in runs:
            doc_id = run.config_snapshot.get("document_id") if run.config_snapshot else None
            filename = None
            if doc_id:
                doc = session.execute(
                    select(Document).where(Document.id == uuid.UUID(doc_id))
                ).scalar_one_or_none()
                if doc:
                    filename = doc.filename

            # Resolve pile name
            pile_name = None
            pile_id_str = str(run.pile_id) if run.pile_id else None
            if run.pile_id:
                pile = session.execute(
                    select(Pile).where(Pile.id == run.pile_id)
                ).scalar_one_or_none()
                if pile:
                    pile_name = pile.name

            results.append(RunListItem(
                id=str(run.id),
                status=run.status,
                started_at=run.started_at.isoformat(),
                document_id=doc_id,
                filename=filename,
                pile_id=pile_id_str,
                pile_name=pile_name,
                needs_recheck_count=recheck_counts.get(str(run.id), 0),
            ))
        return results
    finally:
        session.close()


@app.get("/runs/{run_id}/state")
async def get_run_state(run_id: str) -> dict:
    """Return pipeline run state for the frontend canvas.

    Reads from run_steps to give real-time progress. Uses the last
    *completed/skipped* step's output_state for accumulated results
    (completed_nodes, retries, etc.) and separately identifies the
    currently-running step (if any) as current_node.

    STATUS → COLOUR CONTRACT (frontend relies on these values):
      - completed_nodes: list of node names that finished successfully
      - current_node: the node currently executing (or last executed)
      - node_status: "completed" | "skipped" | "error" | "running" | "pending"
      - run_status: "pending" | "running" | "completed" | "failed" | "cancelled" | "paused"
    The frontend derives per-node visual state from these fields exclusively.
    """
    session = SessionLocal()
    try:
        run = session.execute(
            select(Run).where(Run.id == uuid.UUID(run_id))
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")

        # Get ALL steps ordered by step_order descending
        steps = session.execute(
            select(RunStep)
            .where(RunStep.run_id == uuid.UUID(run_id))
            .order_by(RunStep.step_order.desc())
        ).scalars().all()

        if not steps:
            return {
                "run_id": run_id,
                "current_node": "",
                "node_status": "pending",
                "completed_nodes": [],
                "skipped_nodes": [],
                "retries": {},
                "error_type": None,
                "error_detail": None,
                "run_status": run.status,
            }

        # Find the currently-running step (if any) and the last checkpointed step.
        # A "running" step has output_state={} (written by _create_step before node
        # executes). The last completed/skipped/failed step has the real accumulated
        # state including completed_nodes.
        running_step = None
        checkpointed_step = None
        for step in steps:
            if step.status == "running" and running_step is None:
                running_step = step
            elif step.status in ("completed", "skipped", "failed") and checkpointed_step is None:
                checkpointed_step = step
            if running_step and checkpointed_step:
                break

        # Read accumulated state from the last checkpointed step's output_state.
        # This contains completed_nodes, retries, skipped_nodes, etc.
        output_state = (checkpointed_step.output_state or {}) if checkpointed_step else {}

        # Determine current_node: prefer the running step (actively executing),
        # fall back to the last checkpointed step name.
        if running_step:
            current_node = running_step.step_name
            node_status = "running"
        elif checkpointed_step:
            current_node = output_state.get("current_node", checkpointed_step.step_name)
            node_status = output_state.get("node_status", checkpointed_step.status)
        else:
            current_node = ""
            node_status = "pending"

        return {
            "run_id": run_id,
            "current_node": current_node,
            "node_status": node_status,
            "completed_nodes": output_state.get("completed_nodes", []),
            "skipped_nodes": output_state.get("skipped_nodes", []),
            "retries": output_state.get("retries", {}),
            "error_type": output_state.get("error_type"),
            "error_detail": output_state.get("error_detail"),
            "run_status": run.status,
        }
    finally:
        session.close()


@app.get("/runs/{run_id}/node/{node_id}/details")
async def get_node_details(run_id: str, node_id: str) -> dict:
    """Get detailed output from a specific pipeline node.

    Returns the node's execution details including duration, token usage,
    retry/skip info, and relevant output data (claims, verdicts, findings, etc.).
    """
    session = SessionLocal()
    try:
        step = session.execute(
            select(RunStep).where(
                RunStep.run_id == uuid.UUID(run_id),
                RunStep.step_name == node_id,
            )
        ).scalar_one_or_none()

        if step is None:
            raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found for run")

        output = step.output_state or {}

        # Extract relevant data based on node type
        details: dict[str, Any] = {
            "node_id": node_id,
            "status": step.status,
            "duration_ms": step.duration_ms,
            "input_tokens": step.input_tokens,
            "output_tokens": step.output_tokens,
            "cost_usd": float(step.cost_usd) if step.cost_usd else None,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "ended_at": step.ended_at.isoformat() if step.ended_at else None,
        }

        # ── Common: retry, error, skip info ──────────────────────────────
        details["retry_count"] = output.get("retries", {}).get(node_id, 0)
        details["error_detail"] = output.get("error_detail")
        details["error_type"] = output.get("error_type")

        # Find skip reason for this node
        skip_reason = None
        for sn in output.get("skipped_nodes", []):
            if isinstance(sn, dict) and sn.get("node_name") == node_id:
                skip_reason = sn.get("reason")
                break
        details["skip_reason"] = skip_reason

        # ── Per-node specific output ─────────────────────────────────────
        if node_id == "ingest":
            details["mime_type"] = output.get("mime_type")
            raw = output.get("raw_content")
            details["file_size"] = len(raw) if raw else None
            # Per-document status from pile run
            pile_doc_ids = output.get("config", {}).get("pile_document_ids", [])
            if not pile_doc_ids:
                # Check the config_snapshot on the run itself
                run = session.execute(
                    select(Run).where(Run.id == uuid.UUID(run_id))
                ).scalar_one_or_none()
                if run and run.config_snapshot:
                    pile_doc_ids = run.config_snapshot.get("pile_document_ids", [])
            details["pile_document_count"] = len(pile_doc_ids)
            details["document_id"] = output.get("document_id")

        elif node_id == "extract_text":
            text = output.get("extracted_text", "")
            details["extracted_text_preview"] = text[:2000] if text else None
            details["text_length"] = len(text) if text else 0
            # Estimate page count (~3000 chars per page for plain text)
            details["estimated_page_count"] = max(1, (len(text) + 2999) // 3000) if text else 0
            # Per-document status (for pile runs, ingest handles one doc at a time currently)
            details["document_id"] = output.get("document_id")
            details["mime_type"] = output.get("mime_type")

        elif node_id == "classify_document":
            details["classification_label"] = output.get("classification_label")
            details["classification_confidence"] = output.get("classification_confidence")
            details["classification_scores"] = output.get("classification_scores")
            # Reasoning: if LLM was used (tokens > 0) it's LLM-based; otherwise keyword fallback
            if (step.input_tokens or 0) > 0:
                details["classification_method"] = "llm"
            else:
                details["classification_method"] = "keyword_fallback"

        elif node_id == "chunk":
            chunks = output.get("chunks", [])
            details["chunk_count"] = len(chunks)
            # Config used
            config = output.get("config", {})
            details["chunk_max_size"] = config.get("chunk_max_size")
            details["chunk_overlap"] = config.get("chunk_overlap")
            # Sample boundaries (first 5 chunks with start/end offsets)
            details["chunks_preview"] = [
                {
                    "index": c.get("index"),
                    "length": len(c.get("text", "")),
                    "start_offset": c.get("start_offset"),
                    "end_offset": c.get("end_offset"),
                    "text_preview": c.get("text", "")[:120],
                }
                for c in chunks[:5]
            ]

        elif node_id == "embed":
            details["embeddings_stored"] = output.get("embeddings_stored", False)
            # Model info from environment
            details["embedding_model"] = os.environ.get("EMBEDDING_MODEL", "none (skipped)")
            details["vector_count"] = 0  # Currently skipped; would be chunk count
            chunks = output.get("chunks", [])
            if output.get("embeddings_stored"):
                details["vector_count"] = len(chunks)

        elif node_id == "extract_claims":
            claims = output.get("claims", [])
            details["claim_count"] = len(claims)
            # Count by extraction method
            method_counts: dict[str, int] = {}
            for claim in claims:
                method = claim.get("_extraction_method", "llm")
                method_counts[method] = method_counts.get(method, 0) + 1
            details["extraction_method_counts"] = method_counts
            # Enrich claims with text snippet from the source chunks
            chunks = output.get("chunks", [])
            enriched_claims = []
            for claim in claims:
                enriched = dict(claim)
                chunk_idx = claim.get("chunk_index")
                start = claim.get("start_offset", 0)
                end = claim.get("end_offset", 0)
                if chunks and chunk_idx is not None and 0 <= chunk_idx < len(chunks):
                    chunk_text = chunks[chunk_idx].get("text", "")
                    chunk_start = chunks[chunk_idx].get("start_offset", 0)
                    if start < len(chunk_text) and end <= len(chunk_text):
                        snippet = chunk_text[start:end]
                    elif start >= chunk_start:
                        local_start = start - chunk_start
                        local_end = end - chunk_start
                        if 0 <= local_start < len(chunk_text):
                            snippet = chunk_text[local_start:min(local_end, len(chunk_text))]
                        else:
                            snippet = ""
                    else:
                        snippet = ""
                    if snippet:
                        ctx_start = max(0, start - 30) if start < len(chunk_text) else max(0, (start - chunk_start) - 30)
                        ctx_end_pos = min(len(chunk_text), (end if end < len(chunk_text) else end - chunk_start) + 30)
                        context_before = chunk_text[ctx_start:start if start < len(chunk_text) else start - chunk_start].lstrip()
                        context_after = chunk_text[(end if end < len(chunk_text) else end - chunk_start):ctx_end_pos].rstrip()
                        enriched["snippet"] = snippet
                        enriched["snippet_context_before"] = context_before
                        enriched["snippet_context_after"] = context_after
                enriched_claims.append(enriched)
            details["claims"] = enriched_claims

        elif node_id in ("match_rules", "match_rules_against_sources"):
            verdicts = output.get("verdicts", [])
            findings = output.get("claim_findings", []) if node_id == "match_rules" else output.get("source_findings", [])
            details["verdicts"] = verdicts
            details["findings"] = findings
            details["finding_count"] = len(findings)
            # Split findings by evaluation_method
            eval_method_counts: dict[str, int] = {}
            for f in findings:
                method = f.get("evaluation_method", f.get("source", "llm"))
                eval_method_counts[method] = eval_method_counts.get(method, 0) + 1
            details["evaluation_method_counts"] = eval_method_counts
            # Verdict summary
            verdict_counts: dict[str, int] = {}
            for v in verdicts:
                vtype = v.get("verdict", "unknown")
                verdict_counts[vtype] = verdict_counts.get(vtype, 0) + 1
            details["verdict_counts"] = verdict_counts
            # Was fallback used?
            if (step.input_tokens or 0) > 0:
                details["evaluation_method"] = "llm"
            else:
                details["evaluation_method"] = "fallback"

        elif node_id == "merge_findings":
            details["findings"] = output.get("findings", [])
            details["finding_count"] = len(output.get("findings", []))

        elif node_id == "score_confidence":
            details["verdicts"] = output.get("verdicts", [])

        elif node_id == "route_to_queue":
            buckets = output.get("queue_buckets", {})
            details["queue_buckets"] = buckets
            details["auto_approve_count"] = len(buckets.get("auto_approve", []))
            details["escalate_count"] = len(buckets.get("escalate", []))
            details["auto_reject_count"] = len(buckets.get("auto_reject", []))
            # Show routing conditions for escalated items
            verdicts = output.get("verdicts", [])
            config = output.get("config", {})
            threshold = config.get("confidence_threshold", 0.7)
            details["confidence_threshold"] = threshold
            routing_reasons: list[dict] = []
            verdict_map = {v.get("claim_id"): v for v in verdicts}
            for claim_id in buckets.get("escalate", []):
                v = verdict_map.get(claim_id)
                if v is None:
                    routing_reasons.append({"claim_id": claim_id, "reason": "no_verdict_available"})
                elif v.get("verdict") == "non_compliant":
                    routing_reasons.append({"claim_id": claim_id, "reason": "non_compliant"})
                elif v.get("needs_human_review"):
                    routing_reasons.append({"claim_id": claim_id, "reason": "needs_human_review"})
                elif v.get("confidence", 1.0) < threshold:
                    routing_reasons.append({"claim_id": claim_id, "reason": f"low_confidence ({v.get('confidence', 0):.2f} < {threshold})"})
                else:
                    routing_reasons.append({"claim_id": claim_id, "reason": "escalated"})
            details["routing_reasons"] = routing_reasons

        elif node_id == "human_review":
            details["decisions"] = output.get("decisions", [])
            details["decision_count"] = len(output.get("decisions", []))

        elif node_id == "finalize":
            details["final_status"] = "completed"
            details["total_claims"] = len(output.get("claims", []))
            details["total_findings"] = len(output.get("findings", []))

        return details
    finally:
        session.close()


@app.get("/runs/{run_id}/cost")
async def get_run_cost(run_id: str) -> dict:
    """Get per-stage cost and duration breakdown for a pipeline run."""
    session = SessionLocal()
    try:
        steps = session.execute(
            select(RunStep)
            .where(RunStep.run_id == uuid.UUID(run_id))
            .order_by(RunStep.step_order)
        ).scalars().all()

        stages = []
        total_duration = 0
        total_input = 0
        total_output = 0
        total_cost = 0.0

        for step in steps:
            d = step.duration_ms or 0
            i = step.input_tokens or 0
            o = step.output_tokens or 0
            c = float(step.cost_usd or 0)
            total_duration += d
            total_input += i
            total_output += o
            total_cost += c
            stages.append({
                "stage": step.step_name,
                "step_order": step.step_order,
                "status": step.status,
                "duration_ms": d,
                "input_tokens": i,
                "output_tokens": o,
                "cost_usd": c,
            })

        return {
            "run_id": run_id,
            "total_duration_ms": total_duration,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": total_cost,
            "stages": stages,
        }
    finally:
        session.close()


# ─── Report / Summary ─────────────────────────────────────────────────────────


@app.get("/runs/{run_id}/report")
async def get_run_report(run_id: str) -> dict:
    """Generate a comprehensive compliance report for a completed pipeline run.

    Returns a structured summary including:
    - Overall compliance verdict
    - Risk score
    - Document classification
    - All extracted claims with their verdicts
    - Findings and violations
    - Recommendations
    """
    session = SessionLocal()
    try:
        run = session.execute(
            select(Run).where(Run.id == uuid.UUID(run_id))
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")

        if run.status not in ("completed", "failed"):
            return {
                "run_id": run_id,
                "status": run.status,
                "ready": False,
                "message": "Pipeline has not completed yet.",
            }

        # Get all steps and their outputs
        steps = session.execute(
            select(RunStep)
            .where(RunStep.run_id == uuid.UUID(run_id))
            .order_by(RunStep.step_order)
        ).scalars().all()

        # Build report from step outputs
        step_outputs = {}
        total_duration = 0
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        for step in steps:
            step_outputs[step.step_name] = step.output_state or {}
            total_duration += step.duration_ms or 0
            total_cost += float(step.cost_usd or 0)
            total_input_tokens += step.input_tokens or 0
            total_output_tokens += step.output_tokens or 0

        # Extract key data from step outputs
        classify_out = step_outputs.get("classify_document", {})
        claims_out = step_outputs.get("extract_claims", {})
        rules_out = step_outputs.get("match_rules", {})
        source_out = step_outputs.get("match_rules_against_sources", {})
        merge_out = step_outputs.get("merge_findings", {})
        route_out = step_outputs.get("route_to_queue", {})
        text_out = step_outputs.get("extract_text", {})

        claims = claims_out.get("claims", [])
        verdicts = rules_out.get("verdicts", [])
        findings = merge_out.get("findings", [])
        source_findings = source_out.get("source_findings", [])
        queue_buckets = route_out.get("queue_buckets", {})

        # Compute overall verdict
        non_compliant_count = sum(1 for v in verdicts if v.get("verdict") == "non_compliant")
        indeterminate_count = sum(1 for v in verdicts if v.get("verdict") == "indeterminate")
        compliant_count = sum(1 for v in verdicts if v.get("verdict") == "compliant")
        total_claims = len(claims)

        if non_compliant_count > 0:
            overall_verdict = "NON-COMPLIANT"
            risk_level = "HIGH"
        elif indeterminate_count > total_claims * 0.3:
            overall_verdict = "REQUIRES REVIEW"
            risk_level = "MEDIUM"
        elif indeterminate_count > 0:
            overall_verdict = "MOSTLY COMPLIANT"
            risk_level = "LOW"
        else:
            overall_verdict = "COMPLIANT"
            risk_level = "MINIMAL"

        # Risk score (0-100)
        if total_claims > 0:
            risk_score = int(
                (non_compliant_count * 100 + indeterminate_count * 40) / total_claims
            )
        else:
            risk_score = 0
        risk_score = min(risk_score, 100)

        # Build claim details with verdicts
        verdict_map = {v.get("claim_id"): v for v in verdicts}
        claim_details = []
        for claim in claims:
            cid = claim.get("claim_id", "")
            v = verdict_map.get(cid, {})
            claim_details.append({
                "claim_id": cid,
                "claim_text": claim.get("claim_text", ""),
                "confidence": claim.get("confidence", 0),
                "verdict": v.get("verdict", "not_evaluated"),
                "rule_id": v.get("rule_id"),
                "needs_review": v.get("needs_human_review", False),
            })

        # Get document info
        doc_id = run.config_snapshot.get("document_id") if run.config_snapshot else None
        filename = None
        if doc_id:
            doc = session.execute(
                select(Document).where(Document.id == uuid.UUID(doc_id))
            ).scalar_one_or_none()
            if doc:
                filename = doc.filename

        report = {
            "run_id": run_id,
            "ready": True,
            "status": run.status,
            "generated_at": datetime.now(timezone.utc).isoformat(),

            # Document info
            "document": {
                "filename": filename,
                "classification": classify_out.get("classification_label", "unknown"),
                "classification_confidence": classify_out.get("classification_confidence", 0),
                "text_length": len(text_out.get("extracted_text", "")),
            },

            # Overall assessment
            "assessment": {
                "overall_verdict": overall_verdict,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "summary": _generate_summary(overall_verdict, non_compliant_count, indeterminate_count, compliant_count, total_claims, findings),
            },

            # Claim breakdown
            "claims": {
                "total": total_claims,
                "compliant": compliant_count,
                "non_compliant": non_compliant_count,
                "indeterminate": indeterminate_count,
                "details": claim_details,
            },

            # Findings
            "findings": {
                "total": len(findings),
                "items": findings[:20],  # Limit to first 20
                "source_findings": source_findings[:10],
            },

            # Queue routing
            "routing": {
                "auto_approved": len(queue_buckets.get("auto_approve", [])),
                "escalated": len(queue_buckets.get("escalate", [])),
                "auto_rejected": len(queue_buckets.get("auto_reject", [])),
            },

            # Execution stats
            "execution": {
                "total_duration_ms": total_duration,
                "total_cost_usd": total_cost,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "nodes_completed": len([s for s in steps if s.status == "completed"]),
                "nodes_skipped": len([s for s in steps if s.status == "skipped"]),
                "nodes_failed": len([s for s in steps if s.status == "failed"]),
            },
        }

        return report
    finally:
        session.close()


def _generate_summary(verdict: str, non_compliant: int, indeterminate: int, compliant: int, total: int, findings: list) -> str:
    """Generate a human-readable summary paragraph."""
    parts = []
    parts.append(f"Document analysis complete. {total} factual claims were extracted and evaluated against compliance rules.")

    if non_compliant > 0:
        parts.append(f"{non_compliant} claim(s) were found NON-COMPLIANT, requiring immediate attention.")
    if indeterminate > 0:
        parts.append(f"{indeterminate} claim(s) could not be definitively assessed and require manual review.")
    if compliant > 0 and non_compliant == 0:
        parts.append(f"All {compliant} evaluated claims are within regulatory bounds.")

    if findings:
        parts.append(f"{len(findings)} finding(s) were identified during source document analysis.")

    return " ".join(parts)


# ─── Approval queue backfill for existing runs ───────────────────────────────


@app.delete("/runs/{run_id}")
async def delete_run(run_id: str) -> dict:
    """Delete a pipeline run and its associated data.

    Hard-deletes all dependent rows (decisions, approval-queue entries,
    source_locations, claims, run_steps) in FK-safe order, then the run
    row itself. This is irreversible.
    """
    session = SessionLocal()
    try:
        run = session.execute(
            select(Run).where(Run.id == uuid.UUID(run_id))
        ).scalar_one_or_none()

        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")

        from src.pipeline.run_cleanup import delete_run_and_dependents

        delete_run_and_dependents(session, run_id)
        session.commit()

        return {"id": run_id, "status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete run: {e}")
    finally:
        session.close()


@app.post("/runs/{run_id}/populate-queue")
async def populate_approval_queue(run_id: str) -> dict:
    """Backfill the approval queue from a completed run's escalated claims.

    This handles the case where a run completed before the approval-enqueue
    fix was deployed. It reads the route_to_queue node's output_state to find
    escalated claim IDs, then creates pending approval items for any that
    don't already exist in the queue.

    Idempotent: calling multiple times won't create duplicates.
    """
    from src.pipeline.approval_api import get_approval_service

    session = SessionLocal()
    try:
        # Get the route_to_queue step output
        rtq_step = session.execute(
            select(RunStep).where(
                RunStep.run_id == uuid.UUID(run_id),
                RunStep.step_name == "route_to_queue",
            )
        ).scalar_one_or_none()

        if rtq_step is None:
            raise HTTPException(status_code=404, detail="Run has no route_to_queue step")

        output = rtq_step.output_state or {}
        buckets = output.get("queue_buckets", {})
        escalated_ids = buckets.get("escalate", [])

        if not escalated_ids:
            return {"run_id": run_id, "created": 0, "message": "No escalated claims to enqueue"}

        # Get claims data for enriched payloads
        claims = output.get("claims", [])
        claim_map = {c.get("claim_id", ""): c for c in claims}

        # Check what's already in the queue
        approval_service = get_approval_service()
        existing_items = approval_service.get_all(run_id)
        existing_claim_ids = set()
        for item in existing_items:
            cid = item.payload.get("details", {}).get("claim_id") or item.payload.get("claim_id", "")
            if cid:
                existing_claim_ids.add(cid)

        # Enqueue missing items
        created = 0
        for claim_id in escalated_ids:
            if claim_id in existing_claim_ids:
                continue

            claim_data = claim_map.get(claim_id, {})
            claim_text = claim_data.get("claim_text", claim_id)
            confidence = claim_data.get("confidence", 0)

            approval_service.enqueue_item(
                run_id=run_id,
                item_type="finding",
                payload={
                    "summary": claim_text,
                    "details": {
                        "claim_id": claim_id,
                        "confidence": confidence,
                        "severity": "medium" if confidence < 0.7 else "low",
                        "evaluation_method": resolve_evaluation_method(
                            claim_data, output.get("claim_findings", [])
                        ),
                    },
                    "source_citations": [
                        build_source_citation(
                            claim_data,
                            document_id=output.get("document_id"),
                            document_version_id=output.get("document_version_id"),
                            extracted_text=output.get("extracted_text"),
                        )
                    ],
                },
            )
            created += 1

        return {"run_id": run_id, "created": created, "total_escalated": len(escalated_ids)}
    finally:
        session.close()


# ─── SSE streaming ────────────────────────────────────────────────────────────


@app.get("/runs/{run_id}/stream")
async def stream_run_events(run_id: str):
    """Server-Sent Events stream for real-time pipeline progress.

    Clients connect here and receive events as nodes start/complete.
    """
    queue = get_sse_queue(run_id)

    async def event_generator():
        try:
            # Send initial state
            session = SessionLocal()
            try:
                run = session.execute(
                    select(Run).where(Run.id == uuid.UUID(run_id))
                ).scalar_one_or_none()
                if run:
                    yield {
                        "event": "connected",
                        "data": json.dumps({
                            "run_id": run_id,
                            "status": run.status,
                        }),
                    }
            finally:
                session.close()

            # Stream events
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {
                        "event": data.get("type", "update"),
                        "data": json.dumps(data),
                    }
                    # Stop streaming when run completes
                    if data.get("type") == "run_complete":
                        break
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {"event": "ping", "data": ""}
        finally:
            remove_sse_queue(run_id, queue)

    return EventSourceResponse(event_generator())
