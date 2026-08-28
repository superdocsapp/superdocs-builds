"""Extract claims node — identifies factual assertions from document chunks.

This is the first node of the Examine Stage. It processes each chunk through
an LLM to identify discrete factual assertions (e.g., "APR is 24%",
"processing fee is 500 PHP"), producing ExtractionResult entries with claim
text, source location (chunk_index, start/end offsets where start < end),
and a preliminary confidence score.

Routing logic:
1. If classification_label is in EXTRACTOR_REGISTRY, dispatch to the
   type-specific (structured/regex) extractor first.
2. Any fields that come back as "not_found" are collected and re-extracted
   via LLM fallback (field-level, not document-level).
3. If no type-specific extractor exists, use LLM extraction as the default.
4. If no LLM client is available, fall back to the legacy ClaimExtractor
   protocol (generic per-chunk extraction).

Empty claims list (no claims found in any chunk) is a valid "completed"
outcome, not an error.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from src.pipeline.extractors.base import ExtractedFact
from src.pipeline.extractors.llm_extractor import LLMClient, LLMFactExtractor
from src.pipeline.extractors.registry import EXTRACTOR_REGISTRY
from src.pipeline.source_linker import SourceLinker
from src.pipeline.state import ChunkEntry, ExtractionResult, PipelineState

logger = logging.getLogger(__name__)

# Module-level persister, injectable for testing / graph wiring
# (nodes receive only state in the LangGraph path). When set, it is
# called at NODE COMPLETION with (state, claims) so the durable record
# in claims/source_locations exists even if the run never reaches
# finalize. The JSONB checkpoint stays as-is for resumability.
_persister: Optional[Any] = None


def set_claim_persister(persister) -> None:
    """Inject the claim persistence callable: (state, claims) -> None."""
    global _persister
    _persister = persister


def get_claim_persister():
    """Return the configured claim persister, or None."""
    return _persister


def _persist_claims(state: PipelineState, all_claims: list[ExtractionResult]) -> None:
    """Call the injected persister; never fails extraction on its errors."""
    if _persister is None or not all_claims:
        return
    try:
        _persister(dict(state), [dict(c) for c in all_claims])
    except Exception:
        logger.exception(
            "Claim persistence failed for run %s — durable record not "
            "written, checkpoint still holds the data",
            state.get("run_id"),
        )


class ClaimExtractor(Protocol):
    """Protocol for extracting factual claims from chunk text via LLM."""

    async def extract(self, chunk_text: str, chunk_index: int) -> list[ExtractionResult]:
        """Extract factual claims from a single chunk of text.

        Args:
            chunk_text: The text content of the chunk to analyze.
            chunk_index: The index of the chunk in the document.

        Returns:
            List of ExtractionResult entries found in this chunk.
            May be empty if no claims are identified.

        Raises:
            Exception: If the LLM API call fails (timeout, rate-limit,
                connection error).
        """
        ...


def _convert_fact_to_extraction_result(
    fact: ExtractedFact,
    document_type: str,
    idx: int,
    extraction_method: str = "llm",
) -> ExtractionResult:
    """Convert an ExtractedFact to an ExtractionResult for downstream compatibility.

    Args:
        fact: The extracted fact to convert.
        document_type: The classification label (used in claim_id prefix).
        idx: Index for unique claim_id generation.

    Returns:
        An ExtractionResult entry compatible with the pipeline state.
    """
    if fact.source_span is not None:
        start_offset = fact.source_span.start_offset
        end_offset = fact.source_span.end_offset
        citation_status = "grounded"
    else:
        # Unverifiable citation
        start_offset = 0
        end_offset = 0
        citation_status = "unverifiable"

    return ExtractionResult(
        claim_id=f"{document_type}.{fact.field_name}_{idx}",
        claim_text=f"{fact.field_name}: {fact.value}",
        chunk_index=0,
        start_offset=start_offset,
        end_offset=end_offset,
        confidence=fact.confidence,
        citation_status=citation_status,
        _extraction_method=extraction_method,
    )


async def _dispatch_type_specific_with_fallback(
    state: PipelineState,
    document_type: str,
    llm_client: Optional[LLMClient] = None,
) -> list[ExtractionResult]:
    """Dispatch extraction to a type-specific extractor with field-level LLM fallback.

    1. Run the structured extractor (regex-based).
    2. Identify fields that came back as "not_found".
    3. For those fields, run LLM extraction on just those fields.
    4. Merge results: structured wins where it found a value, LLM fills the gaps.

    Args:
        state: The current pipeline state.
        document_type: The classification label to dispatch on.
        llm_client: Optional LLM client for field-level fallback.

    Returns:
        List of ExtractionResult entries from combined extraction.
    """
    extractor_class = EXTRACTOR_REGISTRY[document_type]
    extractor_instance = extractor_class()

    extracted_text = state.get("extracted_text") or ""
    chunks = state.get("chunks", [])
    chunk_dicts = [dict(c) for c in chunks]

    # Step 1: Run structured extraction
    facts: list[ExtractedFact] = await extractor_instance.extract(extracted_text, chunk_dicts)

    # Step 2: Identify fields that failed (value == "not_found")
    missing_fields: list[str] = [
        f.field_name for f in facts if f.value == "not_found"
    ]
    llm_lookup: dict[str, ExtractedFact] = {}

    # Step 3: LLM fallback for missing fields
    if missing_fields and llm_client is not None:
        logger.info(
            "Structured extraction missed %d fields for %s, "
            "falling back to LLM for: %s",
            len(missing_fields),
            document_type,
            missing_fields,
        )
        llm_extractor = LLMFactExtractor(llm_client, document_type)
        llm_facts = await llm_extractor.extract_fields(extracted_text, missing_fields)

        # Build a lookup of LLM results
        llm_lookup = {f.field_name: f for f in llm_facts}

        # Replace not_found facts with LLM results where available
        merged_facts: list[ExtractedFact] = []
        for fact in facts:
            if fact.value == "not_found" and fact.field_name in llm_lookup:
                llm_fact = llm_lookup[fact.field_name]
                if llm_fact.value != "not_found":
                    merged_facts.append(llm_fact)
                else:
                    merged_facts.append(fact)
            else:
                merged_facts.append(fact)
        facts = merged_facts

    # Step 4: Convert to ExtractionResult and attach source pointers
    source_linker = SourceLinker()
    document_version_id = state.get("document_version_id", "")

    results: list[ExtractionResult] = []
    for idx, fact in enumerate(facts):
        if fact.source_span is not None:
            try:
                source_linker.attach(fact, document_version_id)
            except ValueError:
                logger.warning(
                    "Skipping source pointer attachment for fact %s.%s_%d: "
                    "invalid span (%d:%d)",
                    document_type,
                    fact.field_name,
                    idx,
                    fact.source_span.start_offset,
                    fact.source_span.end_offset,
                )

        method = (
            "llm_fallback"
            if missing_fields and fact.field_name in (llm_lookup or {})
            else "structured"
        )
        results.append(
            _convert_fact_to_extraction_result(fact, document_type, idx, method)
        )

    return results


async def _dispatch_llm_only(
    state: PipelineState,
    document_type: str,
    llm_client: LLMClient,
) -> list[ExtractionResult]:
    """Dispatch extraction entirely to LLM (no structured extractor available).

    Args:
        state: The current pipeline state.
        document_type: The classification label (determines field schema).
        llm_client: The LLM client for extraction.

    Returns:
        List of ExtractionResult entries from LLM extraction.
    """
    extracted_text = state.get("extracted_text") or ""
    chunks = state.get("chunks", [])
    chunk_dicts = [dict(c) for c in chunks]

    llm_extractor = LLMFactExtractor(llm_client, document_type)
    facts = await llm_extractor.extract(extracted_text, chunk_dicts)

    source_linker = SourceLinker()
    document_version_id = state.get("document_version_id", "")

    results: list[ExtractionResult] = []
    for idx, fact in enumerate(facts):
        if fact.source_span is not None:
            try:
                source_linker.attach(fact, document_version_id)
            except ValueError:
                logger.warning(
                    "Skipping source pointer attachment for fact %s.%s_%d: "
                    "invalid span (%d:%d)",
                    document_type,
                    fact.field_name,
                    idx,
                    fact.source_span.start_offset,
                    fact.source_span.end_offset,
                )

        results.append(_convert_fact_to_extraction_result(fact, document_type, idx))

    return results


async def extract_claims(
    state: PipelineState,
    *,
    extractor: Optional[ClaimExtractor] = None,
    llm_client: Optional[LLMClient] = None,
) -> PipelineState:
    """Identify factual assertions from document chunks.

    Routing logic:
    1. If classification_label is in EXTRACTOR_REGISTRY AND extraction_method
       is not set to "llm", use structured extraction with field-level LLM fallback.
    2. If classification_label is known but no structured extractor exists,
       use LLM extraction directly (if llm_client provided).
    3. If no llm_client and no structured extractor, fall back to the legacy
       ClaimExtractor protocol.

    On success (including empty results), sets node_status="completed".
    On LLM API failure, returns a transient error.

    Args:
        state: The current pipeline state containing chunks and config.
        extractor: Optional ClaimExtractor implementation (dependency injection).
            Legacy fallback for unclassified/unknown document types.
        llm_client: Optional LLM client for LLM-based extraction and
            field-level fallback.

    Returns:
        Updated PipelineState with claims, current_node, node_status,
        and completed_nodes set appropriately.
    """
    classification_label = state.get("classification_label")

    # Path 1: Type-specific structured extractor with field-level LLM fallback
    if classification_label and classification_label in EXTRACTOR_REGISTRY:
        try:
            all_claims = await _dispatch_type_specific_with_fallback(
                state, classification_label, llm_client
            )
        except Exception as exc:
            return _error_state(
                state,
                error_detail=f"LLM API failure: {exc}",
            )

        _persist_claims(state, all_claims)

        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("extract_claims")

        return PipelineState(
            **{
                **state,
                "claims": all_claims,
                "current_node": "extract_claims",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    # Path 2: LLM-only extraction (classification known but no structured extractor)
    if classification_label and llm_client is not None:
        try:
            all_claims = await _dispatch_llm_only(
                state, classification_label, llm_client
            )
        except Exception as exc:
            return _error_state(
                state,
                error_detail=f"LLM API failure: {exc}",
            )

        _persist_claims(state, all_claims)

        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("extract_claims")

        return PipelineState(
            **{
                **state,
                "claims": all_claims,
                "current_node": "extract_claims",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    # Path 3: LLM-only extraction for unclassified documents
    if llm_client is not None:
        document_type = classification_label or "loan_agreement"
        try:
            all_claims = await _dispatch_llm_only(
                state, document_type, llm_client
            )
        except Exception as exc:
            return _error_state(
                state,
                error_detail=f"LLM API failure: {exc}",
            )

        _persist_claims(state, all_claims)

        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("extract_claims")

        return PipelineState(
            **{
                **state,
                "claims": all_claims,
                "current_node": "extract_claims",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    # Path 4: Legacy fallback — generic ClaimExtractor per chunk
    chunks: list[ChunkEntry] = state.get("chunks", [])

    if extractor is None:
        return _error_state(
            state,
            error_detail="Claim extractor service not provided",
        )

    all_claims: list[ExtractionResult] = []
    try:
        for chunk in chunks:
            chunk_claims = await extractor.extract(chunk["text"], chunk["index"])
            all_claims.extend(chunk_claims)
    except Exception as exc:
        return _error_state(
            state,
            error_detail=f"LLM API failure: {exc}",
        )

    _persist_claims(state, all_claims)

    completed_nodes = list(state.get("completed_nodes", []))
    completed_nodes.append("extract_claims")

    return PipelineState(
        **{
            **state,
            "claims": all_claims,
            "current_node": "extract_claims",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )


def _error_state(state: PipelineState, *, error_detail: str) -> PipelineState:
    """Return a transient error state for the extract_claims node.

    All extract_claims errors are transient — LLM API failures are retryable.
    """
    return PipelineState(
        **{
            **state,
            "current_node": "extract_claims",
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
