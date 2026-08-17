import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from uuid import UUID
from core.db import exec, exec_one, insert, to_uuid, update
from core.llm_provider import create_llm_provider

logger = logging.getLogger(__name__)

app = FastAPI(title="Drift Detector â€” Agent #2 (Analysis Core)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Falls back to the mock provider only when no live credentials are set.
llm = create_llm_provider()

_poller_task: asyncio.Task | None = None


@app.on_event("startup")
async def _migrate():
    # Search reads chunks.text_content, added after the baseline schema;
    # initdb will not replay that against an existing volume.
    from core.migrate import apply_migrations

    await apply_migrations()


@app.on_event("startup")
async def start_background_poller():
    """Consume ingestion jobs as they arrive.

    Without this the /upload endpoint enqueues a job that nothing ever
    picks up, so runs sit 'in_progress' forever. Disable with
    DRIFT_DISABLE_POLLER=1 if you want to drive the pipeline manually.
    """
    global _poller_task
    if os.getenv("DRIFT_DISABLE_POLLER") == "1":
        logger.info("Background poller disabled via DRIFT_DISABLE_POLLER=1")
        return

    from agents.analyzer.poller import Poller

    poller = Poller(llm)

    async def _loop():
        try:
            await poller.poll_and_run()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Analyzer poller loop exited unexpectedly")

    _poller_task = asyncio.create_task(_loop())


@app.on_event("shutdown")
async def stop_background_poller():
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass


@app.get("/health")
async def health():
    return {"status": "ok", "poller_running": bool(_poller_task and not _poller_task.done())}


@app.get("/health/providers")
async def provider_health():
    """Is retrieval running on real embeddings or the lexical fallback?

    Degraded embeddings still produce findings, so this is the only way to
    tell the difference without reading a run's trace.
    """
    from core.llm_provider import (
        AnthropicFoundryProvider,
        AzureLLMProvider,
        FallbackEmbedder,
        HashingEmbedder,
        NoEmbeddingDeployment,
    )

    embedder = getattr(llm, "_embedder", llm)
    report: dict = {
        "completion_provider": type(llm).__name__,
        "embedding_provider": type(embedder).__name__,
        "embeddings": "unknown",
    }

    azure = None
    if isinstance(embedder, FallbackEmbedder) and isinstance(embedder.primary, AzureLLMProvider):
        azure = embedder.primary
    elif isinstance(embedder, AzureLLMProvider):
        azure = embedder

    if isinstance(embedder, HashingEmbedder):
        report["embeddings"] = "lexical-fallback"
        report["detail"] = (
            "No embeddings endpoint configured. Retrieval matches on literal "
            "overlap only; paraphrased drift will be missed."
        )
    elif azure is not None:
        try:
            deployments = await azure.list_deployments()
            report["azure_deployments"] = sorted(
                d.get("id", "") for d in deployments if d.get("id")
            )
            resolved = await azure.resolve_embedding_deployment()
            report["embeddings"] = "live"
            report["embedding_deployment"] = resolved
        except NoEmbeddingDeployment as exc:
            report["embeddings"] = "lexical-fallback"
            report["detail"] = str(exc)
        except Exception as exc:
            report["embeddings"] = "unreachable"
            report["detail"] = f"{type(exc).__name__}: {str(exc)[:300]}"

    # A live probe is the only claim that actually proves it works.
    try:
        vec = await llm.embed("healthcheck")
        report["embedding_dimensions"] = len(vec)
        if getattr(embedder, "degraded", False):
            report["embeddings"] = "lexical-fallback"
            report["detail"] = getattr(embedder, "reason", "")
    except Exception as exc:
        report["embeddings"] = "error"
        report["detail"] = f"{type(exc).__name__}: {str(exc)[:300]}"

    return report


@app.post("/analyze/{run_id}")
async def analyze(run_id: str):
    from agents.analyzer.poller import Poller

    rid = UUID(run_id)
    rows = await exec(
        "SELECT id FROM documents WHERE run_id = :rid", {"rid": str(rid)}
    )
    doc_ids = [to_uuid(r["id"]) for r in rows]

    if not doc_ids:
        raise HTTPException(404, "No documents found for this run")

    p = Poller(llm)
    await p.run_manual(rid, doc_ids)
    return {"run_id": str(rid), "status": "analyzed"}


@app.get("/search")
async def search_documents(
    q: str,
    limit: int = 20,
    run_id: Optional[str] = None,
    semantic: bool = True,
):
    """Search every stored document for a word or phrase.

    Lives on the analyzer because search needs the embedding provider and the
    pgvector index, both of which this service already owns.

    Exact matches are returned above semantic neighbours and are never
    reordered by similarity: someone who typed a word is looking for that
    word. Semantic results are labelled as such so a conceptual match is never
    mistaken for a literal one.
    """
    from agents.analyzer.search import Searcher

    if len(q.strip()) < 2:
        # One character matches most of the corpus and answers nothing.
        return {"query": q, "results": [], "exact_count": 0,
                "semantic_count": 0, "semantic_available": False}

    return await Searcher(llm).search(
        q, limit=min(limit, 100), run_id=run_id, semantic=semantic
    )


@app.get("/findings/{run_id}")
async def get_findings(run_id: str):
    rows = await exec(
        "SELECT id, state, chunk_id, evidence_quote, evidence_chunk_id, "
        "proposed_old, proposed_new, verifier_verdict, judge_verdict, ai_explanation, "
        "change_fact_id, document_id FROM findings WHERE run_id = :rid ORDER BY created_at",
        {"rid": run_id},
    )
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "state": r["state"],
            "chunk_id": r["chunk_id"],
            "evidence_quote": r["evidence_quote"],
            "evidence_chunk_id": r["evidence_chunk_id"],
            "proposed_old": r["proposed_old"],
            "proposed_new": r["proposed_new"],
            "verifier_verdict": r["verifier_verdict"],
            "judge_verdict": r["judge_verdict"],
            "ai_explanation": r["ai_explanation"],
            "change_fact_id": r["change_fact_id"],
            "document_id": r["document_id"],
        })
    return {"run_id": run_id, "findings": results}


@app.get("/run/{run_id}/status")
async def run_status(run_id: str):
    # NB: `trace` has no `status` column — decision is the per-node verdict.
    steps = await exec(
        "SELECT node, input_hash, decision, evidence, ts FROM trace "
        "WHERE run_id = :rid ORDER BY ts",
        {"rid": run_id},
    )
    cost = await exec(
        "SELECT node, steps, total_tokens_in, total_tokens_out, total_superdocs_ops, "
        "total_ms FROM cost_ledger WHERE run_id = :rid ORDER BY node",
        {"rid": run_id},
    )
    return {
        "run_id": run_id,
        "steps": len(steps),
        "trace": [dict(s) for s in steps],
        "cost": [dict(c) for c in cost],
    }


@app.post("/embeddings/reset")
async def reset_embeddings(run_id: Optional[str] = None):
    """Clear stored embeddings so they are recomputed by the current provider.

    Embeddings are only written where the column is NULL, so switching
    providers (e.g. from the lexical fallback to a real embeddings endpoint)
    would otherwise leave old vectors in place. Cosine similarity between two
    different vector spaces is meaningless, so the stale ones must be dropped
    rather than left to quietly poison retrieval.
    """
    if run_id:
        result = await exec(
            "UPDATE chunks SET embedding = NULL WHERE document_id IN "
            "(SELECT id FROM documents WHERE run_id = :rid) AND embedding IS NOT NULL "
            "RETURNING id",
            {"rid": run_id},
        )
    else:
        result = await exec(
            "UPDATE chunks SET embedding = NULL WHERE embedding IS NOT NULL RETURNING id"
        )

    cleared = len(result)
    return {
        "cleared": cleared,
        "scope": run_id or "all runs",
        "note": "Re-embedding happens on the next analysis run for these chunks.",
    }


@app.get("/run/{run_id}/metrics")
async def run_metrics(run_id: str):
    """Detection quality for this run.

    Ground truth is derived in code from the literal change facts, so this is
    measured rather than asserted. See metrics.Metrics.method / .limitations
    in the response for exactly what was and was not scored.
    """
    from agents.analyzer.metrics import compute_metrics

    run = await exec_one("SELECT id FROM runs WHERE id = :rid", {"rid": run_id})
    if not run:
        raise HTTPException(404, "Run not found")

    facts = await exec(
        "SELECT id, type, old_value, new_value FROM change_facts WHERE run_id = :rid",
        {"rid": run_id},
    )
    chunks = await exec(
        "SELECT c.chunk_id, c.html FROM chunks c "
        "JOIN documents d ON d.id = c.document_id WHERE d.run_id = :rid",
        {"rid": run_id},
    )
    findings = await exec(
        "SELECT change_fact_id, chunk_id, evidence_chunk_id, state "
        "FROM findings WHERE run_id = :rid",
        {"rid": run_id},
    )

    metrics = compute_metrics(
        [dict(f) for f in facts], [dict(c) for c in chunks], [dict(f) for f in findings]
    )
    return {"run_id": run_id, **metrics.to_dict()}


@app.get("/run/{run_id}/logs")
async def run_logs(run_id: str):
    """Append-only trace plus checkpoint state — the material behind the
    terminal view and the evidence that a resume skipped completed work."""
    run = await exec_one(
        "SELECT id, corpus_ref, trigger, status, created_at FROM runs WHERE id = :rid",
        {"rid": run_id},
    )
    if not run:
        raise HTTPException(404, "Run not found")

    trace = await exec(
        "SELECT id, node, input_hash, decision, evidence, tokens_in, tokens_out, "
        "superdocs_ops, ms, ts FROM trace WHERE run_id = :rid ORDER BY ts",
        {"rid": run_id},
    )
    steps = await exec(
        "SELECT node, input_hash, status, output_ref, started_at, ended_at "
        "FROM run_steps WHERE run_id = :rid ORDER BY started_at",
        {"rid": run_id},
    )
    return {"run": run, "trace": trace, "steps": steps}


@app.post("/run/{run_id}/stop")
async def stop_run(run_id: str):
    """Request cancellation. The poller checks between checkpointed units,
    so the run stops without leaving a half-written step behind."""
    run = await exec_one(
        "SELECT status FROM runs WHERE id = :rid", {"rid": run_id}
    )
    if not run:
        raise HTTPException(404, "Run not found")
    if run["status"] not in ("pending", "in_progress"):
        return {"run_id": run_id, "status": run["status"], "message": "Run is not active"}

    await update("runs", {"id": run_id}, {"status": "cancelling"})
    return {"run_id": run_id, "status": "cancelling"}


@app.post("/run/{run_id}/resume")
async def resume_run(run_id: str):
    """Re-enqueue a stopped/failed run.

    Completed nodes are recorded in `run_steps` and findings are persisted
    per change_fact, so the pipeline picks up where it left off instead of
    repeating LLM work.
    """
    run = await exec_one(
        "SELECT status FROM runs WHERE id = :rid", {"rid": run_id}
    )
    if not run:
        raise HTTPException(404, "Run not found")
    if run["status"] in ("pending", "in_progress"):
        return {"run_id": run_id, "status": run["status"], "message": "Run is already active"}

    rows = await exec(
        "SELECT id FROM documents WHERE run_id = :rid", {"rid": run_id}
    )
    if not rows:
        raise HTTPException(400, "Run has no documents to analyze")

    completed = await exec(
        "SELECT count(*) AS n FROM run_steps WHERE run_id = :rid AND status = 'completed'",
        {"rid": run_id},
    )

    await update("runs", {"id": run_id}, {"status": "pending"})
    await insert(
        "jobs",
        {
            "kind": "ingestion",
            "agent": "agent_2",
            "payload": json.dumps(
                {"run_id": run_id, "document_ids": [str(r["id"]) for r in rows]}
            ),
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
        },
    )
    return {
        "run_id": run_id,
        "status": "pending",
        "resumed_from_completed_steps": completed[0]["n"] if completed else 0,
    }


@app.get("/run/{run_id}/cost")
async def run_cost(run_id: str):
    cost = await exec(
        "SELECT node, steps, total_tokens_in, total_tokens_out, total_superdocs_ops, total_ms FROM cost_ledger WHERE run_id = :rid ORDER BY node",
        {"rid": run_id},
    )
    results = [dict(c) for c in cost]
    total_ops = sum(r["total_superdocs_ops"] for r in results)
    return {"run_id": run_id, "stages": results, "total_ops": total_ops}