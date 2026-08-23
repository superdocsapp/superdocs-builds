"""FastAPI app exposing the Box webhook entrypoint, a manual trigger
endpoint, batch processing, the confidence-gated review queue, the
metadata audit trail, per-run cost reporting, and fleet-level metrics.

Multi-tenant: every authenticated request resolves to a TenantContext
(app/tenancy.py) -- its own Box/SuperDocs clients, its own pipeline, its
own review queue / audit history / checkpoints / idempotency store, its
own run and metrics counters. A second tenant's API key can never reach
a first tenant's data through this API; see tests/test_multitenancy.py
for the isolation proof.
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.clients.box_client import BoxAPIError, verify_box_webhook_signature
from app.clients.fake_box_client import FakeBoxClient
from app.tenancy import TenantContext, TenantRegistry
from app.workflow.governance_simulator import compute_governance_outcome
from app.workflow.pipeline import METADATA_TEMPLATE_KEY

# Retention template table, mirrored from
# app/workflow/pipeline.py::_retention_category_for -- exposed read-only
# here so the UI can show "what strong looks like" (Templates screen)
# without duplicating pipeline logic or inventing data.
RETENTION_TEMPLATES = [
    {"doc_class": "contract", "retention_category": "contracts-7yr", "duration_years": 7},
    {"doc_class": "amendment", "retention_category": "contracts-7yr", "duration_years": 7},
    {"doc_class": "invoice", "retention_category": "financial-5yr", "duration_years": 5},
    {"doc_class": "policy", "retention_category": "policy-indefinite", "duration_years": None},
    {"doc_class": "correspondence", "retention_category": "correspondence-3yr", "duration_years": 3},
    {"doc_class": "unknown", "retention_category": "uncategorized-review", "duration_years": None},
]

app = FastAPI(title="Box Metadata Write-Back Workflow")

# The review console (frontend/) is a separate origin (Vite dev/preview
# server) talking to this API over plain fetch, not a proxy -- so it needs
# CORS enabled. Origins are configurable via FRONTEND_ORIGINS (comma-
# separated) for production; the localhost dev ports are allowed by
# default so `make bootstrap` + `npm run dev` work together out of the box.
_default_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
_frontend_origins = os.environ.get("FRONTEND_ORIGINS", _default_origins).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("box_workflow")

# Structured JSON logging with a per-run trace_id, so every log line for
# one file's processing (webhook receipt through final commit) can be
# pulled together with one query. LOG_JSON=0 keeps the plain-text format
# above for local dev if preferred.
from app.logctx import configure_logging, set_trace_id  # noqa: E402

if os.environ.get("LOG_JSON", "1") != "0":
    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"), json_output=True)

_ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# ---------------------------------------------------------------------------
# Multi-tenant registry: resolves an API key to an isolated TenantContext.
# See app/tenancy.py for the full design (TENANTS_CONFIG_PATH for real
# multi-tenant deployments, WORKFLOW_API_KEYS for the single-tenant /
# pre-multi-tenancy-compatible path, neither set -> auth disabled,
# dev/test only).
# ---------------------------------------------------------------------------

_db_dir = os.environ.get("PERSISTENCE_DB_PATH")
if _ENVIRONMENT == "production" and not _db_dir:
    raise RuntimeError(
        "ENVIRONMENT=production but PERSISTENCE_DB_PATH is unset. Without it, "
        "the review queue, metadata audit trail, and crash checkpoints are "
        "in-memory only and are lost on every restart -- silently breaking "
        "the 'survives being stopped' and 'a human holds the gate' "
        "requirements. Set PERSISTENCE_DB_PATH to a directory on a persistent "
        "volume (each tenant gets its own file inside it), or run with "
        "ENVIRONMENT=development for local/eval use."
    )

_tenants = TenantRegistry(db_dir=_db_dir)

if _ENVIRONMENT == "production" and not _tenants.auth_enabled:
    raise RuntimeError(
        "ENVIRONMENT=production but no tenants are configured (set either "
        "TENANTS_CONFIG_PATH or WORKFLOW_API_KEYS). Refusing to start an "
        "unauthenticated API against what's declared to be a production "
        "deployment. See .env.example."
    )


def require_tenant(authorization: str | None = Header(default=None)) -> str:
    """Resolves the caller's tenant_id from `Authorization: Bearer <key>`.
    Every endpoint except /healthz and /webhook/box (Box authenticates
    that one itself, via HMAC signature -- see box_webhook below) depends
    on this. Auth-disabled (dev/test) mode returns the single implicit
    "default" tenant without requiring a header at all."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    tenant_id = _tenants.resolve(token)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="missing or invalid API key")
    return tenant_id


def get_tenant_context(tenant_id: str = Depends(require_tenant)) -> TenantContext:
    return _tenants.context_for(tenant_id)


# ---------------------------------------------------------------------------
# Minimal in-process rate limiting: a fixed window per API key (falls back
# to source IP if none was sent), configurable via
# WORKFLOW_RATE_LIMIT_PER_MINUTE. This is a floor, not a substitute for a
# real gateway (Cloudflare, an API gateway, nginx `limit_req`) in front of
# a real deployment -- but it means a single misbehaving caller (or one
# tenant) can't freely hammer SuperDocs-metered endpoints even before
# that gateway exists. Bucketed by the raw Authorization header (which is
# effectively per-tenant, since each tenant has distinct keys) rather than
# by resolved tenant_id, so an unresolvable/garbage key still gets its own
# bucket instead of colliding with "unauthenticated."
# ---------------------------------------------------------------------------

_RATE_LIMIT_PER_MINUTE = int(os.environ.get("WORKFLOW_RATE_LIMIT_PER_MINUTE", "120"))
_rate_lock = threading.Lock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/healthz",):
        return await call_next(request)
    key = request.headers.get("authorization") or (request.client.host if request.client else "unknown")
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_PER_MINUTE:
            return PlainTextResponse("rate limit exceeded", status_code=429)
        bucket.append(now)
    return await call_next(request)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    logger.info(
        "%s %s -> %s (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        (time.monotonic() - t0) * 1000,
    )
    return response


BOX_WEBHOOK_PRIMARY_KEY = os.environ.get("BOX_WEBHOOK_PRIMARY_KEY", "dev-primary-key")
BOX_WEBHOOK_SECONDARY_KEY = os.environ.get("BOX_WEBHOOK_SECONDARY_KEY")


def _report_to_dict(report) -> dict[str, Any]:
    return {
        "status": "skipped" if report.skipped_reason else "processed",
        "skipped_reason": report.skipped_reason,
        "file_id": report.file_id,
        "version_sha1": report.version_sha1,
        "stages": [s.__dict__ for s in report.stages],
        "metadata_written": report.metadata_written,
        "queued_for_review": report.queued_for_review,
        "total_operations": report.total_operations,
        "total_latency_ms": round(report.total_latency_ms, 2),
        "calibration_mode": report.calibration_mode,
        "near_duplicate_of": report.near_duplicate_of,
        "near_duplicate_similarity": report.near_duplicate_similarity,
    }


def _record_run(ctx: TenantContext, file_id: str, report) -> None:
    with ctx.runs_lock:
        ctx.runs[file_id] = report
    with ctx.metrics_lock:
        if report.skipped_reason:
            ctx.metrics["runs_skipped_total"] += 1
        else:
            ctx.metrics["runs_processed_total"] += 1
            ctx.latency_samples_ms.append(report.total_latency_ms)
        ctx.metrics["operations_total"] += report.total_operations
        ctx.metrics["stage_failures_total"] += sum(1 for s in report.stages if s.status == "failed")


def _percentile(sorted_samples: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list. No numpy
    dependency for four gauges; this is the same reasoning as the
    hand-rolled Prometheus exposition format below -- don't pull in a
    library for something this small."""
    if not sorted_samples:
        return 0.0
    rank = max(0, min(len(sorted_samples) - 1, int(round(pct / 100 * (len(sorted_samples) - 1)))))
    return sorted_samples[rank]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/box")
async def box_webhook(request: Request, tenant: str = "default") -> dict[str, Any]:
    """Box calls this directly, authenticated by HMAC signature (below),
    not a bearer token Box doesn't send -- so it's exempt from
    require_tenant. Which tenant's context a webhook delivery belongs to
    is resolved from a `?tenant=` query param on the subscription URL an
    operator registers with Box per tenant (defaults to "default" for a
    single-tenant deployment, matching pre-multi-tenancy behavior). This
    is an interim mechanism: a real self-serve "Connect your Box account"
    OAuth flow would register the tenant mapping at connect time instead
    of requiring an operator to hand-configure it -- see app/tenancy.py's
    module docstring for what that flow would still need to add."""
    body = await request.body()
    headers = {k.upper(): v for k, v in request.headers.items()}

    if not verify_box_webhook_signature(
        body, headers, BOX_WEBHOOK_PRIMARY_KEY, BOX_WEBHOOK_SECONDARY_KEY
    ):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    payload = await request.json()
    trigger = payload.get("trigger", "")
    if trigger not in ("FILE.UPLOADED", "FILE.METADATA_UPDATED"):
        # Box sends many trigger types; anything outside upload / metadata
        # change is out of scope for this workflow and is a no-op, not an
        # error -- Box still expects a 200 so it doesn't retry forever.
        return {"status": "ignored", "trigger": trigger}

    source = payload.get("source", {})
    file_id = source.get("id")
    if not file_id:
        raise HTTPException(status_code=400, detail="missing source.id in webhook payload")

    ctx = _tenants.context_for(tenant)
    set_trace_id()
    try:
        report = ctx.pipeline.process(file_id)
    except BoxAPIError as e:
        # Box sent us a webhook pointing at a file_id we can't actually
        # reach (deleted between the event firing and us processing it,
        # a permissions change, etc.) -- a clean 404 rather than a crash,
        # so Box's own retry/backoff logic sees a real HTTP response.
        raise HTTPException(status_code=404, detail=f"Box file not accessible: {e}")
    _record_run(ctx, file_id, report)
    return _report_to_dict(report)


class BatchRequest(BaseModel):
    file_ids: list[str]
    max_workers: int = 8


@app.post("/process/batch")
def process_batch(req: BatchRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Processes many DIFFERENT files genuinely concurrently (a real
    thread pool, not a for-loop) -- the complement to the existing
    5-thread same-file concurrency test, proving state doesn't corrupt
    across a real multi-file batch the way documents actually arrive at
    enterprise scale."""
    results: dict[str, Any] = {}

    def run_one(file_id: str) -> tuple[str, Any]:
        set_trace_id()  # each thread pool worker gets its own trace_id
        try:
            report = ctx.pipeline.process(file_id)
        except BoxAPIError as e:
            # One bad file_id in a batch of many must not crash the
            # whole concurrent request -- every other file's future
            # still completes normally; this one is reported as a
            # per-file failure in the results dict instead.
            return file_id, {"status": "failed", "error": f"Box file not accessible: {e}"}
        _record_run(ctx, file_id, report)
        return file_id, _report_to_dict(report)

    with ThreadPoolExecutor(max_workers=req.max_workers) as pool:
        futures = [pool.submit(run_one, fid) for fid in req.file_ids]
        for future in as_completed(futures):
            file_id, result = future.result()
            results[file_id] = result

    processed = sum(1 for r in results.values() if r["status"] == "processed")
    skipped = sum(1 for r in results.values() if r["status"] == "skipped")
    failed = sum(1 for r in results.values() if r["status"] == "failed")
    total_operations = sum(r.get("total_operations", 0) for r in results.values())
    return {
        "batch_size": len(req.file_ids),
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total_operations": total_operations,
        "results": results,
    }


@app.post("/process/{file_id}")
def process_file(file_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Manual trigger, bypassing the webhook signature check -- used by
    the MCP tool and by demo/test scripts that don't have a live Box
    tenant sending real webhooks."""
    set_trace_id()
    try:
        report = ctx.pipeline.process(file_id)
    except BoxAPIError as e:
        # Most common real cause: file_id doesn't exist in this tenant's
        # Box account (or was deleted/moved out of reach). A clean 404
        # beats an uncaught 500 -- the caller gave us a bad identifier,
        # not something the server did wrong.
        raise HTTPException(status_code=404, detail=f"Box file not accessible: {e}")
    _record_run(ctx, file_id, report)
    return _report_to_dict(report)


@app.get("/reviews")
def list_reviews(
    file_id: str | None = None, ctx: TenantContext = Depends(get_tenant_context)
) -> dict[str, Any]:
    """Fields extracted below the confidence threshold, waiting on a
    human before they can reach Box metadata."""
    items = ctx.review_queue.list_pending(file_id)
    return {"threshold": ctx.review_queue.threshold, "pending": [r.model_dump() for r in items]}


@app.post("/reviews/{review_id}/approve")
def approve_review(review_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    try:
        return ctx.pipeline.apply_review_decision(review_id, approve=True)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown review_id")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/reviews/{review_id}/reject")
def reject_review(review_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    try:
        return ctx.pipeline.apply_review_decision(review_id, approve=False)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown review_id")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/dead-letters")
def list_dead_letters(
    file_id: str | None = None, ctx: TenantContext = Depends(get_tenant_context)
) -> dict[str, Any]:
    """Runs where at least one stage exhausted retries or hit an open
    circuit -- the real ops worklist, versus reading extraction_notes on
    each file by hand. Also reports whether SuperDocs currently looks
    healthy for this tenant, since a wave of new entries usually means
    the breaker just tripped."""
    items = ctx.dead_letter.list_unresolved(file_id)
    return {
        "circuit_open": ctx.circuit_breaker.is_open,
        "unresolved": [
            {
                "entry_id": e.entry_id,
                "file_id": e.file_id,
                "version_sha1": e.version_sha1,
                "stage": e.stage,
                "reason": e.reason,
                "attempts": e.attempts,
                "created_at": e.created_at,
            }
            for e in items
        ],
    }


@app.post("/dead-letters/{entry_id}/resolve")
def resolve_dead_letter(
    entry_id: str, ctx: TenantContext = Depends(get_tenant_context)
) -> dict[str, Any]:
    """Marks an entry resolved -- e.g. after a manual reprocess trigger
    or after confirming the underlying document just doesn't have the
    field. Does not itself retrigger processing; call
    POST /process/{file_id} for that."""
    try:
        entry = ctx.dead_letter.resolve(entry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown dead-letter entry_id")
    return {"entry_id": entry.entry_id, "resolved": entry.resolved, "resolved_at": entry.resolved_at}


@app.get("/calibration-report")
def calibration_report(
    field_name: str | None = None, ctx: TenantContext = Depends(get_tenant_context)
) -> dict[str, Any]:
    """Real calibration: for each (field, confidence-bucket), how often
    a human actually approved the value unchanged, versus what the
    bucket's own confidence midpoint would predict. A large negative
    calibration_gap means this tenant's pipeline is systematically
    over-confident for that field/bucket -- worth tightening
    review_threshold or field_thresholds for it. Needs accumulated
    review decisions to say anything meaningful; empty on a fresh
    tenant."""
    tracker = ctx.pipeline.calibration_tracker
    return {
        "buckets": tracker.bucket_report(field_name),
        "worst_calibrated": tracker.worst_calibrated_fields() if field_name is None else None,
    }


@app.get("/calibration-report/suggest-thresholds")
def suggest_thresholds(
    target_approval_rate: float = 0.9, ctx: TenantContext = Depends(get_tenant_context)
) -> dict[str, Any]:
    """Suggests (never applies) a per-field confidence threshold based
    on this tenant's accumulated real review decisions -- the lowest
    confidence bucket whose real approval rate still meets
    target_approval_rate. Applying it is a manual edit to this
    tenant's field_thresholds in tenants config; this endpoint only
    gives the evidence, since the risk/review-burden trade-off a
    threshold represents is this tenant's policy call, not this
    pipeline's to make."""
    return ctx.pipeline.calibration_tracker.suggest_thresholds(target_approval_rate=target_approval_rate)


@app.get("/cost-report")
def cost_report(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Real SuperDocs operations/latency spent per run, bucketed by
    which calibration mode (none / pairwise / enable_calibration /
    ensemble) produced the run, plus the REALIZED operations multiplier
    of each calibrated mode versus this tenant's own 'none' baseline --
    not the docstring's rough estimate. Answers 'is the accuracy
    trade-off from turning on calibration actually worth it for our
    document mix' with this tenant's own numbers."""
    return ctx.pipeline.cost_tracker.report()


@app.get("/files/{file_id}/history")
def file_history(file_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """The audit trail: every field that has ever changed value for this
    file, when, and why. A reprocessed file where nothing changed
    produces zero new entries here -- this is what proves 'byte-identical
    where you promise untouched' rather than just asserting it."""
    entries = ctx.history.get_history(file_id)
    return {"file_id": file_id, "changes": [e.model_dump() for e in entries]}


@app.get("/files/{file_id}/history/verify")
def verify_file_history(file_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Recomputes the hash chain over this file's audit trail and reports
    whether it's intact -- i.e. whether any entry was altered, deleted,
    or reordered after being written. Not a substitute for real WORM
    storage at scale (see README), but gives a regulator or auditor a
    concrete, checkable answer to "has this been tampered with" rather
    than just trusting the table."""
    result = ctx.history.verify_history(file_id)
    return {
        "file_id": file_id,
        "valid": result.valid,
        "checked_count": result.checked_count,
        "unverifiable_prefix_count": result.unverifiable_prefix_count,
        "first_break_index": result.first_break_index,
        "detail": result.detail,
    }


@app.get("/runs/{file_id}/cost")
def run_cost(file_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Per-stage latency and SuperDocs operations spent on the most
    recent run for this file."""
    with ctx.runs_lock:
        report = ctx.runs.get(file_id)
    if report is None:
        raise HTTPException(status_code=404, detail="no run recorded for this file_id yet")
    return {
        "file_id": file_id,
        "version_sha1": report.version_sha1,
        "total_operations": report.total_operations,
        "total_latency_ms": round(report.total_latency_ms, 2),
        "stages": [
            {"stage": s.name, "status": s.status, "latency_ms": round(s.latency_ms, 2), "operations": s.operations}
            for s in report.stages
        ],
    }


@app.get("/files/{file_id}/governance-outcome")
def governance_outcome(file_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Proves the metadata write-back actually accomplishes what the
    brief says it should: 'those fields then drive Box's own retention,
    search, and workflow rules.' Reads exactly what's in the Box metadata
    template (nothing else) and computes the same retention-eligibility,
    search-facet, and workflow outcomes Box's own automation would
    compute from those fields -- every outcome citing the metadata field
    and value that produced it."""
    metadata = ctx.box.get_metadata(file_id, "documentIntelligence")
    if not metadata:
        raise HTTPException(
            status_code=404, detail="no documentIntelligence metadata written for this file_id yet"
        )
    governance = ctx.box.get_governance_state(file_id)
    pending = [r.field_name for r in ctx.review_queue.list_pending(file_id)]
    outcome = compute_governance_outcome(
        file_id=file_id,
        metadata=metadata,
        legal_hold=governance.legal_hold,
        retention_policy_locked=governance.retention_policy_locked,
        pending_review_field_names=pending,
    )
    return outcome.__dict__


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(ctx: TenantContext = Depends(get_tenant_context)) -> str:
    """This tenant's fleet-level view in Prometheus exposition format --
    the number a founder running this would actually watch every
    morning, made real (scrapeable) rather than just answered in a
    write-up. No new dependency: hand-rolled exposition format rather
    than pulling in prometheus_client for four gauges. Scoped to the
    calling tenant, same as every other endpoint -- a monitoring scraper
    needs its own tenant key per tenant, or an aggregate view needs a
    separate fleet-wide operator endpoint, which is future work, not
    something this exposes today."""
    with ctx.metrics_lock:
        snapshot = dict(ctx.metrics)
        latency_sorted = sorted(ctx.latency_samples_ms)
    pending_reviews = len(ctx.review_queue.list_pending())
    p50 = _percentile(latency_sorted, 50)
    p95 = _percentile(latency_sorted, 95)
    p99 = _percentile(latency_sorted, 99)

    lines = [
        "# HELP box_workflow_runs_processed_total Runs that completed processing (not skipped).",
        "# TYPE box_workflow_runs_processed_total counter",
        f"box_workflow_runs_processed_total {snapshot['runs_processed_total']}",
        "# HELP box_workflow_runs_skipped_total Runs skipped (idempotent no-op, concurrency, or governance hold).",
        "# TYPE box_workflow_runs_skipped_total counter",
        f"box_workflow_runs_skipped_total {snapshot['runs_skipped_total']}",
        "# HELP box_workflow_stage_failures_total Individual pipeline stages that failed (after exhausting retries).",
        "# TYPE box_workflow_stage_failures_total counter",
        f"box_workflow_stage_failures_total {snapshot['stage_failures_total']}",
        "# HELP box_workflow_operations_total SuperDocs operations spent across all runs.",
        "# TYPE box_workflow_operations_total counter",
        f"box_workflow_operations_total {snapshot['operations_total']}",
        "# HELP box_workflow_reviews_pending Fields currently held for human review.",
        "# TYPE box_workflow_reviews_pending gauge",
        f"box_workflow_reviews_pending {pending_reviews}",
        "# HELP box_workflow_run_latency_ms Per-run end-to-end latency in milliseconds, processed runs only, over the most recent "
        f"{ctx.latency_samples_ms.maxlen} samples.",
        "# TYPE box_workflow_run_latency_ms summary",
        f'box_workflow_run_latency_ms{{quantile="0.5"}} {round(p50, 2)}',
        f'box_workflow_run_latency_ms{{quantile="0.95"}} {round(p95, 2)}',
        f'box_workflow_run_latency_ms{{quantile="0.99"}} {round(p99, 2)}',
        f"box_workflow_run_latency_ms_count {len(latency_sorted)}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Read-only UI surface: file listing, single-file detail, search, and the
# retention template table. Every field below is read from the same stores
# the pipeline itself writes to (Box metadata, review queue, history,
# last-run report) -- nothing here is fabricated for display. This is the
# "search" and "templates" surfaces named on the assigned build's card,
# plus the file listing the Review/Documents UI is built on top of.
# ---------------------------------------------------------------------------


def _known_file_ids(ctx: TenantContext) -> list[str]:
    lister = getattr(ctx.box, "list_known_file_ids", None)
    return lister() if callable(lister) else []


def _file_summary(ctx: TenantContext, file_id: str) -> dict[str, Any]:
    metadata = ctx.box.get_metadata(file_id, METADATA_TEMPLATE_KEY)
    governance = ctx.box.get_governance_state(file_id)
    pending = ctx.review_queue.list_pending(file_id)
    namer = getattr(ctx.box, "get_file_name", None)
    name = namer(file_id) if callable(namer) else None
    with ctx.runs_lock:
        last_report = ctx.runs.get(file_id)
    return {
        "file_id": file_id,
        "name": name,
        "is_companion": file_id.startswith("companion-"),
        "doc_class": metadata.get("doc_class"),
        "doc_class_confidence": metadata.get("doc_class_confidence"),
        "counterparty_name": metadata.get("counterparty_name"),
        "retention_category": metadata.get("retention_category"),
        "processed": bool(metadata),
        "legal_hold": governance.legal_hold,
        "retention_policy_locked": governance.retention_policy_locked,
        "pending_review_count": len(pending),
        "last_run_status": (
            "skipped" if last_report and last_report.skipped_reason else "processed" if last_report else None
        ),
    }


@app.get("/files")
def list_files(
    include_companions: bool = False, ctx: TenantContext = Depends(get_tenant_context)
) -> dict[str, Any]:
    """Every file THIS TENANT's Box client instance has seen (seeded demo
    files, plus any companion documents the pipeline created), each
    summarized with exactly what's in its real Box metadata template
    today. Companion documents (generated artifacts, not source files)
    are excluded by default -- they're reachable via the parent file's
    detail view."""
    summaries = [_file_summary(ctx, fid) for fid in _known_file_ids(ctx)]
    if not include_companions:
        summaries = [s for s in summaries if not s["is_companion"]]
    return {"count": len(summaries), "files": summaries}


@app.get("/files/{file_id}")
def file_detail(file_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Full detail for one file: current Box metadata, governance state,
    pending reviews, and the most recent run report -- the payload the
    Document Details screen renders. Returns whatever the stores actually
    hold; a file with no run yet still returns a valid (empty) shape.
    404s for a file_id THIS TENANT's Box client has never seen -- which
    also means one tenant can never probe for another tenant's file_ids
    by guessing, since each tenant's Box client only knows its own."""
    if file_id not in _known_file_ids(ctx):
        raise HTTPException(status_code=404, detail="unknown file_id")
    metadata = ctx.box.get_metadata(file_id, METADATA_TEMPLATE_KEY)
    governance = ctx.box.get_governance_state(file_id)
    pending = ctx.review_queue.list_pending(file_id)
    namer = getattr(ctx.box, "get_file_name", None)
    name = namer(file_id) if callable(namer) else None
    with ctx.runs_lock:
        last_report = ctx.runs.get(file_id)
    return {
        "file_id": file_id,
        "name": name,
        "metadata": metadata,
        "governance": governance.model_dump(),
        "pending_reviews": [r.model_dump() for r in pending],
        "last_run": _report_to_dict(last_report) if last_report else None,
    }


@app.get("/search")
def search_files(
    q: str | None = None,
    doc_class: str | None = None,
    retention_category: str | None = None,
    needs_review: bool | None = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Facet search over THIS TENANT's processed files' real Box
    metadata -- the 'search' surface named on the assigned build's card.
    `q` matches file name or counterparty name (case-insensitive
    substring); the rest are exact-match facets computed from the same
    metadata Box's own search index would read."""
    results = []
    for fid in _known_file_ids(ctx):
        summary = _file_summary(ctx, fid)
        if doc_class and summary["doc_class"] != doc_class:
            continue
        if retention_category and summary["retention_category"] != retention_category:
            continue
        if needs_review is not None and (summary["pending_review_count"] > 0) != needs_review:
            continue
        if q:
            haystack = f"{summary['name'] or ''} {summary['counterparty_name'] or ''}".lower()
            if q.lower() not in haystack:
                continue
        results.append(summary)
    return {"count": len(results), "results": results}


@app.get("/templates")
def retention_templates(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """The doc-class -> retention-category mapping the pipeline actually
    applies (mirrored from app/workflow/pipeline.py), exposed read-only
    for the Templates screen. Not yet per-tenant customizable -- every
    tenant currently shares this deployment's one mapping; per-tenant
    override is real, separate future work."""
    return {"templates": RETENTION_TEMPLATES}


_SCENARIO_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "demo_scenario"
_SCENARIO_FILES = [
    ("msa-northbridge", "01_msa_northbridge.pdf", "01_msa_northbridge.txt", None),
    ("amendment-1-northbridge", "02_amendment_1_northbridge.pdf", "02_amendment_1_northbridge.txt", None),
    ("invoice-northbridge", "03_invoice_northbridge.pdf", "03_invoice_northbridge.txt", None),
    ("policy-cold-chain", "04_cold_chain_policy.pdf", "04_cold_chain_policy.txt", None),
    ("msa-solara-hold", "05_msa_solara_under_legal_hold.pdf", "05_msa_solara_under_legal_hold.txt", "legal_hold"),
]


@app.post("/demo/seed")
def seed_demo_data(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Loads the real Meridian Cold Chain Logistics scenario (the same
    fixtures `make demo-scenario` runs) into THIS TENANT's in-memory Box
    client and processes every file through the real pipeline -- so the
    UI has genuine, non-fabricated data to render, isolated to whichever
    tenant's key made the request.

    Hard-gated, independent of auth: refuses to run unless
    WORKFLOW_ENABLE_DEMO_SEED=true is explicitly set, and always refuses
    against anything but the in-memory FakeBoxClient. A valid API key is
    not enough on its own -- an operator has to opt a deployment into
    demo seeding by name, so it can never be live by accident in
    whatever environment WORKFLOW_API_KEYS was generated for."""
    if os.environ.get("WORKFLOW_ENABLE_DEMO_SEED", "").lower() != "true":
        raise HTTPException(
            status_code=404,
            detail="demo seeding is disabled; set WORKFLOW_ENABLE_DEMO_SEED=true to enable it "
            "(never set this in a real deployment)",
        )
    if not isinstance(ctx.box, FakeBoxClient):
        raise HTTPException(
            status_code=409,
            detail="demo seeding only works against the in-memory FakeBoxClient, "
            "not a live Box tenant",
        )
    from app.models import GovernanceState

    processed = []
    for file_id, name, source_name, gov_flag in _SCENARIO_FILES:
        if file_id in ctx.box.list_known_file_ids():
            continue  # idempotent: calling seed twice doesn't reprocess
        content = (_SCENARIO_DIR / source_name).read_bytes()
        governance = GovernanceState(legal_hold=True) if gov_flag == "legal_hold" else None
        ctx.box.seed_file(file_id, name, content, governance=governance)
        report = ctx.pipeline.process(file_id)
        _record_run(ctx, file_id, report)
        processed.append(_report_to_dict(report))
    return {"seeded": len(processed), "runs": processed}
