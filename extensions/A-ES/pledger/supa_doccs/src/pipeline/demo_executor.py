"""Demo pipeline executor — runs all 13 nodes with real DeepSeek LLM calls.

Executes the pipeline sequentially, broadcasting state updates via SSE.
Each node produces real results using the DeepSeek API for classification,
claim extraction, rule matching, and confidence scoring.

The executor writes checkpoints to the database after each node completes,
enabling the frontend to poll or stream live progress.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.llm.deepseek_client import chat_completion, chat_completion_json
from src.pipeline.cancel import is_cancelled
from src.pipeline.citation_payload import (
    build_source_citation,
    resolve_evaluation_method,
)
from src.pipeline.config import PipelineConfig, load_config
from src.pipeline.history_sql import (
    emit_node_completed,
    emit_run_status_changed,
)
from src.pipeline.serialization import serialize_state
from src.pipeline.span_resolution import resolve_span

def _emit_history_event(fn, session_factory, state: dict, **kwargs) -> None:
    """Best-effort audit write with ONE retry.

    On persistent failure, marks the run's persistence gap so the run
    ends as 'completed_with_persistence_gap' instead of silently
    under-reporting history.
    """
    for attempt in (1, 2):
        try:
            fn(session_factory, **kwargs)
            return
        except Exception as e:
            logger.warning(
                "Audit event write failed (attempt %d/2) for run %s: %s",
                attempt, kwargs.get("run_id"), e,
            )
    _mark_persistence_gap(state)


def _mark_persistence_gap(state: dict) -> None:
    """Flag the run so it ends as 'completed_with_persistence_gap'."""
    state["_persistence_gap"] = True


def _resolve_final_status(state: dict) -> str:
    """Final run status reflecting any durability-write failures."""
    return (
        "completed_with_persistence_gap"
        if state.get("_persistence_gap")
        else "completed"
    )
from src.pipeline.state import (
    ChunkEntry,
    ComplianceVerdict,
    Decision,
    ExtractionResult,
    NodeMetrics,
    PipelineState,
    QueueBuckets,
    SkippedNodeEntry,
    create_initial_state,
)

logger = logging.getLogger(__name__)

# Type alias for SSE broadcast callback
SSECallback = Any  # Callable[[dict], Awaitable[None]] | None


async def run_pipeline(
    run_id: str,
    document_id: str,
    document_version_id: str,
    storage_path: str,
    mime_type: str,
    filename: str,
    session_factory,
    config_overrides: Optional[dict] = None,
    sse_callback: Optional[SSECallback] = None,
) -> PipelineState:
    """Execute the full pipeline with real LLM calls.

    Args:
        run_id: UUID string for this pipeline run.
        document_id: UUID string for the document.
        document_version_id: UUID string for the version.
        storage_path: Path to the document file on disk.
        mime_type: MIME type of the document.
        filename: Original filename.
        session_factory: SQLAlchemy session factory for DB writes.
        config_overrides: Optional config overrides.
        sse_callback: Optional async callback to broadcast SSE events.

    Returns:
        The final PipelineState after all nodes complete.
    """
    config = load_config(config_overrides)

    state = create_initial_state(
        run_id=run_id,
        document_id=document_id,
        document_version_id=document_version_id,
        config=config,
    )

    # Update run status to running
    await _update_run_status(session_factory, run_id, "running")
    _emit_history_event(
        emit_run_status_changed,
        session_factory,
        state,
        run_id=run_id,
        old_status="pending",
        new_status="running",
    )

    # Define the node execution sequence
    nodes = [
        ("ingest", _node_ingest),
        ("extract_text", _node_extract_text),
        ("classify_document", _node_classify_document),
        ("chunk", _node_chunk),
        ("embed", _node_embed),
        ("extract_claims", _node_extract_claims),
        ("match_rules", _node_match_rules),
        ("match_rules_against_sources", _node_match_rules_against_sources),
        ("merge_findings", _node_merge_findings),
        ("score_confidence", _node_score_confidence),
        ("route_to_queue", _node_route_to_queue),
        ("human_review", _node_human_review),
        ("finalize", _node_finalize),
    ]

    # Context passed to nodes (avoid passing heavy deps through state)
    ctx = {
        "storage_path": storage_path,
        "mime_type": mime_type,
        "filename": filename,
        "run_id": run_id,
        "session_factory": session_factory,
    }

    for step_order, (node_name, node_fn) in enumerate(nodes, start=1):
        # Cooperative cancellation check between nodes
        if is_cancelled(run_id):
            await _update_run_status(session_factory, run_id, "cancelled")
            _emit_history_event(
                emit_run_status_changed,
                session_factory,
                state,
                run_id=run_id,
                old_status="running",
                new_status="cancelled",
            )
            await _broadcast(sse_callback, {
                "type": "run_complete",
                "run_id": run_id,
                "status": "cancelled",
                "completed_nodes": state.get("completed_nodes", []),
            })
            return state

        # Broadcast: node starting
        await _broadcast(sse_callback, {
            "type": "node_start",
            "run_id": run_id,
            "node": node_name,
            "step_order": step_order,
        })

        # Write step row as "running"
        await _create_step(session_factory, run_id, node_name, step_order)

        # Execute node
        t0 = time.perf_counter()
        try:
            state = await node_fn(state, ctx)
        except Exception as e:
            logger.exception("Node %s failed: %s", node_name, e)
            state = _error_state(state, node_name, str(e))

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        # Extract metrics
        metrics = state.get("_last_node_metrics")
        input_tokens = metrics.get("input_tokens", 0) if metrics else 0
        output_tokens = metrics.get("output_tokens", 0) if metrics else 0

        # Write checkpoint
        serialized = serialize_state(state)
        await _write_checkpoint(
            session_factory, run_id, node_name, step_order,
            serialized, state["node_status"], elapsed_ms,
            input_tokens, output_tokens,
        )

        if state["node_status"] in ("completed", "skipped"):
            _emit_history_event(
                emit_node_completed,
                session_factory,
                state,
                run_id=run_id,
                node_name=node_name,
                node_status=state["node_status"],
                duration_ms=elapsed_ms,
                source_ref=state.get("document_version_id"),
            )

        # Broadcast: node completed
        await _broadcast(sse_callback, {
            "type": "node_complete",
            "run_id": run_id,
            "node": node_name,
            "status": state["node_status"],
            "duration_ms": elapsed_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "completed_nodes": state.get("completed_nodes", []),
            "current_node": state.get("current_node", ""),
            "error_detail": state.get("error_detail"),
            "run_status": "running",
        })

        # If node errored with permanent error, stop pipeline
        if state["node_status"] == "error" and state.get("error_type") == "permanent":
            await _update_run_status(session_factory, run_id, "failed")
            _emit_history_event(
                emit_run_status_changed,
                session_factory,
                state,
                run_id=run_id,
                old_status="running",
                new_status="failed",
            )
            await _broadcast(sse_callback, {
                "type": "run_complete",
                "run_id": run_id,
                "status": "failed",
                "error": state.get("error_detail"),
            })
            return state

    # Pipeline completed successfully — unless durability writes failed,
    # in which case the gap must be visible in the run status itself.
    final_status = _resolve_final_status(state)
    await _update_run_status(session_factory, run_id, final_status)
    _emit_history_event(
        emit_run_status_changed,
        session_factory,
        state,
        run_id=run_id,
        old_status="running",
        new_status="completed",
    )
    await _broadcast(sse_callback, {
        "type": "run_complete",
        "run_id": run_id,
        "status": "completed",
        "completed_nodes": state.get("completed_nodes", []),
    })

    return state


# ─── Node implementations ────────────────────────────────────────────────────


async def _node_ingest(state: PipelineState, ctx: dict) -> PipelineState:
    """Load document bytes from storage."""
    storage_path = ctx["storage_path"]
    mime_type = ctx["mime_type"]

    try:
        raw_content = Path(storage_path).read_bytes()
    except (OSError, IOError) as e:
        return _error_state(state, "ingest", f"Cannot read file: {e}", permanent=True)

    if len(raw_content) == 0:
        return _error_state(state, "ingest", "File is empty", permanent=True)

    completed = list(state.get("completed_nodes", []))
    completed.append("ingest")

    return PipelineState(**{
        **state,
        "raw_content": raw_content,
        "mime_type": mime_type,
        "current_node": "ingest",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": None,
    })


async def _node_extract_text(state: PipelineState, ctx: dict) -> PipelineState:
    """Extract text from document bytes."""
    raw_content = state.get("raw_content")
    mime_type = state.get("mime_type", "")

    if raw_content is None:
        return _error_state(state, "extract_text", "No raw content", permanent=True)

    extracted_text = ""

    if mime_type == "text/plain":
        extracted_text = raw_content.decode("utf-8", errors="replace")
    elif mime_type == "application/pdf":
        try:
            import pdfplumber
            import io
            with pdfplumber.open(io.BytesIO(raw_content)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    pages.append(text)
                extracted_text = "\n\n".join(pages)
        except Exception as e:
            return _error_state(state, "extract_text", f"PDF extraction failed: {e}")
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        # Simple DOCX extraction — read the XML content
        try:
            import zipfile
            import io
            import xml.etree.ElementTree as ET

            with zipfile.ZipFile(io.BytesIO(raw_content)) as zf:
                with zf.open("word/document.xml") as doc_xml:
                    tree = ET.parse(doc_xml)
                    root = tree.getroot()
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    paragraphs = []
                    for para in root.iter(f"{{{ns['w']}}}p"):
                        texts = [t.text for t in para.iter(f"{{{ns['w']}}}t") if t.text]
                        if texts:
                            paragraphs.append("".join(texts))
                    extracted_text = "\n".join(paragraphs)
        except Exception as e:
            return _error_state(state, "extract_text", f"DOCX extraction failed: {e}")
    else:
        return _error_state(state, "extract_text", f"Unsupported MIME: {mime_type}", permanent=True)

    if not extracted_text.strip():
        return _error_state(state, "extract_text", "No text extracted from document", permanent=True)

    completed = list(state.get("completed_nodes", []))
    completed.append("extract_text")

    return PipelineState(**{
        **state,
        "extracted_text": extracted_text,
        "current_node": "extract_text",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": None,
    })


async def _node_classify_document(state: PipelineState, ctx: dict) -> PipelineState:
    """Classify document type using DeepSeek."""
    text = state.get("extracted_text", "")
    if not text:
        return _error_state(state, "classify_document", "No text to classify", permanent=True)

    # Use first 3000 chars for classification
    sample = text[:3000]

    system_prompt = """You are a document classification expert for microfinance/lending documents.
Classify the document into exactly one of these categories:
- loan_agreement: A loan agreement, promissory note, or credit facility document
- modification_agreement: A loan modification, restructuring, or amendment document
- repayment_statement: A repayment schedule, payment history, or account statement

Respond with JSON: {"label": "<category>", "confidence": <0.0-1.0>, "scores": {"loan_agreement": <score>, "modification_agreement": <score>, "repayment_statement": <score>}}"""

    user_prompt = f"Classify this document:\n\n---\n{sample}\n---"

    try:
        result, inp_tokens, out_tokens = await chat_completion_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        label = result.get("label", "unclassified")
        confidence = float(result.get("confidence", 0.5))
        scores = result.get("scores", {})

        # Validate label
        valid_labels = {"loan_agreement", "modification_agreement", "repayment_statement"}
        if label not in valid_labels:
            label = "unclassified"
            confidence = 0.3

    except Exception as e:
        logger.warning("Classification LLM failed (using fallback): %s", e)
        # Fallback: simple keyword-based classification
        text_lower = text.lower()
        if "loan agreement" in text_lower or "principal amount" in text_lower:
            label = "loan_agreement"
            confidence = 0.7
        elif "modification" in text_lower or "amendment" in text_lower:
            label = "modification_agreement"
            confidence = 0.7
        elif "repayment" in text_lower or "payment schedule" in text_lower:
            label = "repayment_statement"
            confidence = 0.7
        else:
            label = "loan_agreement"
            confidence = 0.5
        scores = {label: confidence}
        inp_tokens = 0
        out_tokens = 0

    completed = list(state.get("completed_nodes", []))
    completed.append("classify_document")

    return PipelineState(**{
        **state,
        "classification_label": label,
        "classification_confidence": confidence,
        "classification_scores": scores,
        "current_node": "classify_document",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": NodeMetrics(input_tokens=inp_tokens, output_tokens=out_tokens),
    })


async def _node_chunk(state: PipelineState, ctx: dict) -> PipelineState:
    """Split text into overlapping chunks."""
    extracted_text = state.get("extracted_text", "")
    config = state["config"]

    if not extracted_text:
        return _error_state(state, "chunk", "No text to chunk", permanent=True)

    chunk_max_size = config["chunk_max_size"]
    chunk_overlap = config["chunk_overlap"]
    min_threshold = config["min_chunk_threshold"]

    completed = list(state.get("completed_nodes", []))
    skipped = list(state.get("skipped_nodes", []))

    # Below threshold: single chunk, skip
    if len(extracted_text) < min_threshold:
        chunks = [ChunkEntry(index=0, text=extracted_text, start_offset=0, end_offset=len(extracted_text))]
        skipped.append(SkippedNodeEntry(node_name="chunk", reason="below_chunk_threshold"))
        completed.append("chunk")
        return PipelineState(**{
            **state,
            "chunks": chunks,
            "current_node": "chunk",
            "node_status": "skipped",
            "error_type": None,
            "error_detail": None,
            "skipped_nodes": skipped,
            "completed_nodes": completed,
            "_last_node_metrics": None,
        })

    # Normal chunking
    stride = chunk_max_size - chunk_overlap
    chunks: list[ChunkEntry] = []
    idx = 0
    offset = 0
    while offset < len(extracted_text):
        end = min(offset + chunk_max_size, len(extracted_text))
        chunks.append(ChunkEntry(index=idx, text=extracted_text[offset:end], start_offset=offset, end_offset=end))
        idx += 1
        offset += stride
        if end == len(extracted_text):
            break

    completed.append("chunk")

    return PipelineState(**{
        **state,
        "chunks": chunks,
        "current_node": "chunk",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "skipped_nodes": skipped,
        "_last_node_metrics": None,
    })


async def _node_embed(state: PipelineState, ctx: dict) -> PipelineState:
    """Generate embeddings (skipped in demo — no vector store needed for compliance)."""
    completed = list(state.get("completed_nodes", []))
    completed.append("embed")
    skipped = list(state.get("skipped_nodes", []))
    skipped.append(SkippedNodeEntry(node_name="embed", reason="vector_store_not_configured"))

    return PipelineState(**{
        **state,
        "embeddings_stored": False,
        "current_node": "embed",
        "node_status": "skipped",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "skipped_nodes": skipped,
        "_last_node_metrics": None,
    })


async def _node_extract_claims(state: PipelineState, ctx: dict) -> PipelineState:
    """Extract factual claims from chunks using DeepSeek."""
    chunks = state.get("chunks", [])
    doc_type = state.get("classification_label", "unknown")

    if not chunks:
        completed = list(state.get("completed_nodes", []))
        completed.append("extract_claims")
        return PipelineState(**{
            **state,
            "claims": [],
            "current_node": "extract_claims",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed,
            "_last_node_metrics": None,
        })

    system_prompt = f"""You are a compliance document analyst. Extract all factual claims from the given text chunk of a {doc_type} document.

For each claim, identify:
- claim_text: The exact factual assertion (e.g., "interest rate is 24% per annum")
- confidence: How confident you are this is a real factual claim (0.0-1.0)
- category: One of "financial_term", "date", "party_name", "obligation", "condition", "amount", "rate", "duration"

Respond with JSON: {{"claims": [{{"claim_text": "...", "confidence": 0.9, "category": "..."}}]}}

Extract ALL factual claims — amounts, rates, dates, party names, obligations, conditions, etc."""

    all_claims: list[ExtractionResult] = []
    total_inp = 0
    total_out = 0
    full_text = state.get("extracted_text") or ""

    def _locate_span(claim_text: str, batch: list[dict]) -> tuple[int, int, str]:
        """Resolve a claim's true document-level span.

        Tries the full extracted text first, then chunk-local search with
        proper chunk-start offset math. Falls back to token-anchor fuzzy
        matching — LLMs paraphrase claims ("X is Y" for source "X: Y"),
        and exact-substring-only lookup marked supported claims
        unverifiable. Returns (start, end, citation_status); unverifiable
        spans are (0, 0).
        """
        if claim_text:
            pos = full_text.find(claim_text)
            if pos >= 0:
                return pos, pos + len(claim_text), "grounded"
            for c in batch:
                local = c["text"].find(claim_text)
                if local >= 0:
                    start = c["start_offset"] + local
                    return start, start + len(claim_text), "grounded"
            fuzzy = resolve_span(claim_text, full_text)
            if fuzzy is not None:
                return fuzzy[0], fuzzy[1], "grounded"
        return 0, 0, "unverifiable"

    # Process chunks (batch up to 5 at a time to avoid too many API calls)
    batch_size = 3
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        combined_text = "\n\n".join(
            f"[Chunk {c['index']}] (offset {c['start_offset']}-{c['end_offset']}):\n{c['text']}"
            for c in batch
        )

        try:
            result, inp, out = await chat_completion_json(
                system_prompt=system_prompt,
                user_prompt=f"Extract claims from these chunks:\n\n{combined_text}",
                max_tokens=4096,
            )
            total_inp += inp
            total_out += out

            raw_claims = result.get("claims", [])
            for j, claim in enumerate(raw_claims):
                claim_id = f"{doc_type}-{len(all_claims) + 1:03d}"
                # Map back to the appropriate chunk
                chunk_idx = batch[min(j // max(1, len(raw_claims) // len(batch)), len(batch) - 1)]["index"]

                # Resolve the claim's real position in the document —
                # previously hardcoded start=0 / end=len(claim_text),
                # which produced meaningless spans (all start_offset: 0).
                start, end, citation_status = _locate_span(
                    claim.get("claim_text", ""), batch
                )

                all_claims.append(ExtractionResult(
                    claim_id=claim_id,
                    claim_text=claim.get("claim_text", ""),
                    chunk_index=chunk_idx,
                    start_offset=start,
                    end_offset=end,
                    confidence=float(claim.get("confidence", 0.7)),
                    citation_status=citation_status,
                    _extraction_method="llm",
                ))
        except Exception as e:
            logger.warning("Claim extraction LLM failed for batch %d (using regex fallback): %s", i, e)
            # Fallback: extract simple patterns from text
            import re

            def _add_regex_claim(c: dict, text_match: str, m_start: int, m_end: int) -> None:
                claim_id = f"{doc_type}-{len(all_claims) + 1:03d}"
                all_claims.append(ExtractionResult(
                    claim_id=claim_id,
                    claim_text=text_match,
                    chunk_index=c["index"],
                    # Regex offsets are chunk-relative — convert to
                    # document-level by adding the chunk's start.
                    start_offset=c["start_offset"] + m_start,
                    end_offset=c["start_offset"] + m_end,
                    confidence=0.6,
                    citation_status="grounded",
                    _extraction_method="regex_fallback",
                ))

            for c in batch:
                chunk_text = c["text"]
                # Find monetary amounts
                for m in re.finditer(r'(?:INR|Rs\.?|₹)\s*[\d,]+(?:\.\d+)?', chunk_text):
                    _add_regex_claim(c, m.group(0).strip(), m.start(), m.end())
                # Find percentages
                for m in re.finditer(r'\d+(?:\.\d+)?%\s*(?:per\s+annum|p\.?a\.?)?', chunk_text):
                    _add_regex_claim(c, m.group(0).strip(), m.start(), m.end())

    completed = list(state.get("completed_nodes", []))
    completed.append("extract_claims")

    # Durable record: write claims/source_locations at node completion,
    # via the same persist_fact() path the LangGraph node uses.
    # ONE retry, then mark-and-continue: a silent gap is unacceptable,
    # so the run ends as 'completed_with_persistence_gap' instead of a
    # plain 'completed'.
    session_factory = ctx.get("session_factory")
    if session_factory is not None and all_claims:
        from src.pipeline.source_linker import persist_extraction_results

        persisted = False
        for attempt in (1, 2):
            try:
                n = persist_extraction_results(
                    session_factory,
                    dict(state),
                    [dict(c) for c in all_claims],
                )
                logger.info(
                    "Persisted %d claims (with source locations) for run %s",
                    n,
                    state.get("run_id"),
                )
                persisted = True
                break
            except Exception as e:
                logger.warning(
                    "Claim persistence failed (attempt %d/2) for run %s: %s",
                    attempt, state.get("run_id"), e,
                )
        if not persisted:
            state["_persistence_gap"] = True

    return PipelineState(**{
        **state,
        "claims": all_claims,
        "current_node": "extract_claims",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": NodeMetrics(input_tokens=total_inp, output_tokens=total_out),
    })


async def _node_match_rules(state: PipelineState, ctx: dict) -> PipelineState:
    """Match claims against compliance rules using DeepSeek."""
    claims = state.get("claims", [])

    if not claims:
        completed = list(state.get("completed_nodes", []))
        completed.append("match_rules")
        return PipelineState(**{
            **state,
            "verdicts": [],
            "claim_findings": [],
            "current_node": "match_rules",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed,
            "_last_node_metrics": None,
        })

    # Format claims for the LLM
    claims_text = "\n".join(
        f"{i+1}. [{c['claim_id']}] {c['claim_text']} (confidence: {c['confidence']:.2f})"
        for i, c in enumerate(claims)
    )

    system_prompt = """You are a microfinance compliance officer. Evaluate each claim against standard lending regulations:

Rules to check:
1. Interest rates must not exceed 36% APR (usury limit)
2. Processing fees must not exceed 3% of principal
3. Penal rates must not exceed base rate + 6%
4. All fee disclosures must be present
5. Repayment schedules must match agreed terms
6. Moratorium/grace periods must be honored
7. Documentation must be consistent across related documents

For each claim, provide a compliance verdict:
- "compliant" — claim is within regulatory bounds
- "non_compliant" — claim violates a rule
- "indeterminate" — cannot determine compliance without more context

Respond with JSON: {"verdicts": [{"claim_id": "...", "verdict": "compliant|non_compliant|indeterminate", "confidence": 0.0-1.0, "rule_id": "RULE-X", "reason": "..."}]}"""

    try:
        result, inp_tokens, out_tokens = await chat_completion_json(
            system_prompt=system_prompt,
            user_prompt=f"Evaluate these claims for compliance:\n\n{claims_text}",
            max_tokens=4096,
        )

        raw_verdicts = result.get("verdicts", [])
        verdicts: list[ComplianceVerdict] = []
        findings: list[dict] = []

        for v in raw_verdicts:
            claim_id = v.get("claim_id", "")
            verdict_val = v.get("verdict", "indeterminate")
            if verdict_val not in ("compliant", "non_compliant", "indeterminate"):
                verdict_val = "indeterminate"

            confidence = float(v.get("confidence", 0.5))
            needs_review = verdict_val == "non_compliant" or confidence < 0.7

            verdicts.append(ComplianceVerdict(
                claim_id=claim_id,
                verdict=verdict_val,  # type: ignore[arg-type]
                confidence=confidence,
                needs_human_review=needs_review,
                rule_id=v.get("rule_id"),
                evidence_refs=[],
            ))

            # Non-compliant claims become findings
            if verdict_val == "non_compliant":
                findings.append({
                    "claim_id": claim_id,
                    "rule_id": v.get("rule_id", ""),
                    "verdict": verdict_val,
                    "reason": v.get("reason", ""),
                    "source": "match_rules",
                    # This path evaluated via DeepSeek — record it so the
                    # enqueue-time resolver doesn't have to guess.
                    "evaluation_method": "llm",
                })

    except Exception as e:
        logger.warning("Rule matching LLM failed (using fallback): %s", e)
        # Fallback: mark all claims as indeterminate
        verdicts = []
        findings = []
        for claim in claims:
            claim_id = claim["claim_id"]
            verdicts.append(ComplianceVerdict(
                claim_id=claim_id,
                verdict="indeterminate",
                confidence=0.5,
                needs_human_review=True,
                rule_id=None,
                evidence_refs=[],
            ))
        inp_tokens = 0
        out_tokens = 0

    completed = list(state.get("completed_nodes", []))
    completed.append("match_rules")

    return PipelineState(**{
        **state,
        "verdicts": verdicts,
        "claim_findings": findings,
        "current_node": "match_rules",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": NodeMetrics(input_tokens=inp_tokens, output_tokens=out_tokens),
    })


async def _node_match_rules_against_sources(state: PipelineState, ctx: dict) -> PipelineState:
    """Check source document spans against compliance rules using DeepSeek."""
    chunks = state.get("chunks", [])
    claims = state.get("claims", [])

    if not chunks or not claims:
        completed = list(state.get("completed_nodes", []))
        completed.append("match_rules_against_sources")
        return PipelineState(**{
            **state,
            "source_findings": [],
            "current_node": "match_rules_against_sources",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed,
            "_last_node_metrics": None,
        })

    # Use representative chunks for source-level rule checking
    sample_chunks = chunks[:5]  # Limit to first 5 chunks for performance
    chunk_text = "\n\n".join(f"[Section {c['index']+1}]: {c['text'][:500]}" for c in sample_chunks)

    system_prompt = """You are a compliance auditor checking source document spans for regulatory violations.

Look for:
1. Contradictions between different sections
2. Missing mandatory disclosures
3. Ambiguous or misleading language
4. Terms that conflict with standard regulations

For each violation found in the source text, provide:
- finding_type: "contradiction" | "missing_disclosure" | "misleading_language" | "regulatory_violation"
- description: What the issue is
- section_index: Which section contains the issue
- severity: "high" | "medium" | "low"

Respond with JSON: {"findings": [{"finding_type": "...", "description": "...", "section_index": 0, "severity": "..."}]}
If no issues found, return {"findings": []}"""

    try:
        result, inp_tokens, out_tokens = await chat_completion_json(
            system_prompt=system_prompt,
            user_prompt=f"Check these document sections for compliance issues:\n\n{chunk_text}",
            max_tokens=4096,
        )

        source_findings = []
        for f in result.get("findings", []):
            source_findings.append({
                "finding_type": f.get("finding_type", ""),
                "description": f.get("description", ""),
                "section_index": f.get("section_index", 0),
                "severity": f.get("severity", "medium"),
                "source": "match_rules_against_sources",
            })

    except Exception as e:
        logger.warning("Source rule matching LLM failed (using fallback): %s", e)
        source_findings = []
        inp_tokens = 0
        out_tokens = 0

    completed = list(state.get("completed_nodes", []))
    completed.append("match_rules_against_sources")

    return PipelineState(**{
        **state,
        "source_findings": source_findings,
        "current_node": "match_rules_against_sources",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": NodeMetrics(input_tokens=inp_tokens, output_tokens=out_tokens),
    })


async def _node_merge_findings(state: PipelineState, ctx: dict) -> PipelineState:
    """Merge findings from both rule-checking paths."""
    claim_findings = state.get("claim_findings", [])
    source_findings = state.get("source_findings", [])
    merged = claim_findings + source_findings

    completed = list(state.get("completed_nodes", []))
    completed.append("merge_findings")

    return PipelineState(**{
        **state,
        "findings": merged,
        "current_node": "merge_findings",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": None,
    })


async def _node_score_confidence(state: PipelineState, ctx: dict) -> PipelineState:
    """Refine confidence scores using DeepSeek."""
    verdicts = list(state.get("verdicts", []))
    config = state["config"]
    threshold = config["confidence_threshold"]

    if not verdicts:
        completed = list(state.get("completed_nodes", []))
        completed.append("score_confidence")
        return PipelineState(**{
            **state,
            "current_node": "score_confidence",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed,
            "_last_node_metrics": None,
        })

    # Apply threshold flagging
    refined_verdicts = []
    for v in verdicts:
        updated = dict(v)
        if v["confidence"] < threshold:
            updated["needs_human_review"] = True
        if v["verdict"] == "non_compliant":
            updated["needs_human_review"] = True
        refined_verdicts.append(ComplianceVerdict(**updated))  # type: ignore[arg-type]

    completed = list(state.get("completed_nodes", []))
    completed.append("score_confidence")

    return PipelineState(**{
        **state,
        "verdicts": refined_verdicts,
        "current_node": "score_confidence",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": None,
    })


async def _node_route_to_queue(state: PipelineState, ctx: dict) -> PipelineState:
    """Partition claims into queue buckets."""
    verdicts = state.get("verdicts", [])
    claims = state.get("claims", [])
    config = state["config"]
    threshold = config["confidence_threshold"]

    auto_approve: list[str] = []
    escalate: list[str] = []
    auto_reject: list[str] = []

    verdict_map = {v["claim_id"]: v for v in verdicts}

    for claim in claims:
        claim_id = claim["claim_id"]
        v = verdict_map.get(claim_id)

        if v is None:
            escalate.append(claim_id)
        elif v["verdict"] == "non_compliant" or v.get("needs_human_review"):
            escalate.append(claim_id)
        elif v["confidence"] < threshold:
            escalate.append(claim_id)
        else:
            auto_approve.append(claim_id)

    completed = list(state.get("completed_nodes", []))
    completed.append("route_to_queue")

    return PipelineState(**{
        **state,
        "queue_buckets": QueueBuckets(
            auto_approve=auto_approve,
            escalate=escalate,
            auto_reject=auto_reject,
        ),
        "current_node": "route_to_queue",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": None,
    })


async def _node_human_review(state: PipelineState, ctx: dict) -> PipelineState:
    """Human review node — enqueue escalated claims into the approval service.

    Each escalated claim becomes a pending approval item that can be
    approved/rejected via the /approval/ API or MCP decide_approval tool.
    This is the human gate — claims are NOT auto-approved.
    """
    from src.pipeline.approval_api import get_approval_service as _get_svc

    escalated = state.get("queue_buckets", {}).get("escalate", [])
    run_id = ctx.get("run_id") or state.get("run_id", "")

    # Get approval service (set during app lifespan)
    try:
        approval_service = _get_svc()
    except Exception:
        approval_service = None

    # Enqueue each escalated claim as a pending approval item.
    # Dedup by claim_id — same guarantee as the populate-queue backfill
    # (main.py) so node re-execution can never create duplicates.
    decisions: list[Decision] = []
    claims = state.get("claims", [])
    claim_map = {c["claim_id"]: c for c in claims}

    existing_claim_ids: set[str] = set()
    if approval_service is not None:
        for existing_item in approval_service.get_all(run_id):
            cid = (
                existing_item.payload.get("details", {}).get("claim_id")
                or existing_item.payload.get("claim_id", "")
            )
            if cid:
                existing_claim_ids.add(cid)

    for claim_id in escalated:
        if approval_service is not None and claim_id in existing_claim_ids:
            logger.info(
                "Skipping enqueue for claim %s (already in queue for run %s)",
                claim_id, run_id,
            )
            continue
        claim_data = claim_map.get(claim_id, {})
        claim_text = claim_data.get("claim_text", claim_id)
        confidence = claim_data.get("confidence", 0)

        # Build payload matching the frontend QueueItemPayload shape:
        #   { summary, details, source_citations[] }
        payload = {
            "summary": claim_text,
            "details": {
                "claim_id": claim_id,
                "confidence": confidence,
                "severity": "medium" if confidence < 0.7 else "low",
                "evaluation_method": resolve_evaluation_method(
                    claim_data, state.get("claim_findings", [])
                ),
            },
            "source_citations": [
                build_source_citation(
                    claim_data,
                    document_id=state.get("document_id"),
                    document_version_id=state.get("document_version_id"),
                    extracted_text=state.get("extracted_text"),
                )
            ],
        }

        if approval_service:
            approval_service.enqueue_item(
                run_id=run_id,
                item_type="finding",
                payload=payload,
            )
            existing_claim_ids.add(claim_id)
        # No decision yet — items stay pending for human review

    completed = list(state.get("completed_nodes", []))
    completed.append("human_review")

    return PipelineState(**{
        **state,
        "decisions": decisions,
        "current_node": "human_review",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": None,
    })


async def _node_finalize(state: PipelineState, ctx: dict) -> PipelineState:
    """Finalize pipeline — persist the deliverable and mark complete.

    Builds the run's deliverable from the final state (same builder the
    incremental flow uses) and upserts it into the `deliverables` table
    so GET /runs/{id}/deliverable and the MCP get_deliverable tool can
    serve it after the process is gone.
    """
    completed = list(state.get("completed_nodes", []))
    completed.append("finalize")
    try:
        from src.pipeline.deliverable_store import persist_deliverable

        session_factory = ctx.get("session_factory")
        if session_factory is not None:
            record = persist_deliverable(
                session_factory, state["run_id"], dict(state)
            )
            logger.info(
                "Deliverable persisted for run %s (%d sections, %d claims, hash=%s)",
                state["run_id"],
                record["section_count"],
                record["claim_count"],
                record["deliverable_hash"][:12],
            )
    except Exception as e:
        logger.exception(
            "Failed to persist deliverable for run %s: %s", state.get("run_id"), e
        )
        return _error_state(
            state,
            "finalize",
            f"Deliverable persistence failed: {e}",
        )

    return PipelineState(**{
        **state,
        "current_node": "finalize",
        "node_status": "completed",
        "error_type": None,
        "error_detail": None,
        "completed_nodes": completed,
        "_last_node_metrics": None,
    })


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _error_state(
    state: PipelineState, node_name: str, detail: str, permanent: bool = False
) -> PipelineState:
    """Return an error state."""
    return PipelineState(**{
        **state,
        "current_node": node_name,
        "node_status": "error",
        "error_type": "permanent" if permanent else "transient",
        "error_detail": detail,
        "completed_nodes": list(state.get("completed_nodes", [])),
        "_last_node_metrics": None,
    })


async def _broadcast(callback: Optional[SSECallback], data: dict) -> None:
    """Broadcast an SSE event if callback is configured."""
    if callback:
        try:
            await callback(data)
        except Exception as e:
            logger.debug("SSE broadcast failed: %s", e)


async def _update_run_status(session_factory, run_id: str, status: str) -> None:
    """Update the run status in the database."""
    from sqlalchemy import update
    from src.models.runs import Run

    session = session_factory()
    try:
        session.execute(
            update(Run).where(Run.id == uuid.UUID(run_id)).values(
                status=status,
                ended_at=datetime.now(timezone.utc)
                if status in ("completed", "failed")
                or status.startswith("completed_with_")
                else None,
            )
        )
        session.commit()
    finally:
        session.close()


async def _create_step(session_factory, run_id: str, step_name: str, step_order: int) -> None:
    """Create a run_steps row with status running."""
    from src.models.runs import RunStep

    session = session_factory()
    try:
        step = RunStep(
            id=uuid.uuid4(),
            run_id=uuid.UUID(run_id),
            step_name=step_name,
            step_order=step_order,
            status="running",
            started_at=datetime.now(timezone.utc),
            input_state={},
            output_state={},
        )
        session.add(step)
        session.commit()
    finally:
        session.close()


async def _write_checkpoint(
    session_factory,
    run_id: str,
    step_name: str,
    step_order: int,
    output_state: dict,
    status: str,
    duration_ms: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Write checkpoint to the database."""
    from sqlalchemy import select, update
    from src.models.runs import RunStep

    # Map pipeline node status to DB-allowed values
    db_status = status
    if db_status == "error":
        db_status = "failed"
    elif db_status not in ("pending", "running", "completed", "failed", "skipped"):
        db_status = "completed"

    session = session_factory()
    try:
        step = session.execute(
            select(RunStep).where(
                RunStep.run_id == uuid.UUID(run_id),
                RunStep.step_name == step_name,
            )
        ).scalar_one_or_none()

        if step:
            step.output_state = output_state
            step.status = db_status
            step.ended_at = datetime.now(timezone.utc)
            step.duration_ms = duration_ms
            step.input_tokens = input_tokens
            step.output_tokens = output_tokens
            cost = (input_tokens * 0.000001 + output_tokens * 0.000002)  # DeepSeek pricing approx
            step.cost_usd = cost
            session.commit()
    finally:
        session.close()
