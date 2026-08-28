# Implementation Plan: LangGraph Pipeline Design

## Overview

This plan implements the LangGraph StateGraph topology for the three-stage document-intelligence pipeline (Understand → Examine → Stay-Alive). Implementation proceeds bottom-up: state schema and configuration first, then routing logic, then individual nodes, then checkpoint/resume infrastructure, and finally human-in-the-loop interrupt/resume wiring. All code is Python 3.11 using LangGraph, FastAPI, SQLAlchemy, and PostgreSQL 16 with pgvector.

## Tasks

- [x] 1. Define State schema, configuration, and core types
  - [x] 1.1 Create the PipelineState TypedDict and supporting types
    - Create `src/pipeline/state.py` with `PipelineState`, `ChunkEntry`, `ExtractionResult`, `ComplianceVerdict`, `Decision`, `SkippedNodeEntry`, `PipelineConfig`, `QueueBuckets` TypedDicts
    - Include type literals for `node_status`, `error_type`, and `verdict` values
    - Add a factory function `create_initial_state(run_id, document_id, document_version_id, config)` that returns a valid initial PipelineState with all defaults
    - _Requirements: 7.1, 7.2, 7.3, 7.5_

  - [x] 1.2 Create JSONB serialization/deserialization utilities
    - Create `src/pipeline/serialization.py` with `serialize_state(state: PipelineState) -> dict` and `deserialize_state(data: dict) -> PipelineState`
    - Handle bytes ↔ base64, UUID ↔ string conversions
    - Ensure round-trip fidelity for all field types
    - _Requirements: 7.5, 6.2_

  - [x] 1.3 Write property test for State JSONB round-trip
    - **Property 6: State JSONB Round-Trip**
    - Create `tests/pipeline/test_properties_state.py`
    - Build a Hypothesis composite strategy for generating valid `PipelineState` instances
    - Assert `deserialize_state(serialize_state(state)) == state` for all generated states
    - **Validates: Requirements 7.5, 6.2**

  - [x] 1.4 Create PipelineConfig loader with defaults
    - Create `src/pipeline/config.py` with `load_config(overrides: dict) -> PipelineConfig`
    - Apply defaults: max_retries=3, chunk_max_size=1000, chunk_overlap=200, confidence_threshold=0.7, review_timeout_hours=72, reminder_interval_hours=24, poll_interval_seconds=30, extract_text_timeout_seconds=60, min_chunk_threshold=200
    - Validate constraints (chunk_max_size > chunk_overlap > 0, thresholds in range)
    - _Requirements: 7.1_

- [x] 2. Implement routing functions
  - [x] 2.1 Create the routing function factory and per-node routing logic
    - Create `src/pipeline/routing.py`
    - Implement `make_routing_fn(node_name: str, config: PipelineConfig)` factory
    - Implement per-node routing logic as documented in the routing conditions table: `ingest` (next/escalate), `extract_text` (next/retry/escalate), `chunk` (next), `embed` (next/retry/escalate), `extract_claims` (next/retry/escalate), `match_rules` (next/retry/escalate), `score_confidence` (next/retry/escalate), `route_to_queue` (escalate/next based on escalate bucket), `human_review` (finalize), `finalize` (end/retry/escalate)
    - Implement unhandled-state fallback that sets permanent error and returns "escalate"
    - _Requirements: 1.6, 1.7, 2.1, 2.2, 2.5, 11.3, 11.4_

  - [x] 2.2 Write property test for routing determinism
    - **Property 2: Routing Determinism — Exactly One Match**
    - Create `tests/pipeline/test_properties_routing.py`
    - Generate arbitrary post-node States; assert exactly one routing condition matches per source node
    - **Validates: Requirements 11.4, 1.7**

  - [x] 2.3 Write property test for retry routing correctness
    - **Property 3: Retry Routing Correctness**
    - Generate States with `node_status="error"`, `error_type="transient"`, varying retry counts
    - Assert "retry" when retries < max_retries, "escalate" when retries >= max_retries
    - **Validates: Requirements 2.1, 2.2**

  - [x] 2.4 Write property test for unrecognized error type escalation
    - **Property 4: Unrecognized Error Type Escalation**
    - Generate States with `error_type` values other than "transient"/"permanent" (including None, random strings)
    - Assert routing always returns "escalate"
    - **Validates: Requirements 2.5, 1.7**

  - [x] 2.5 Write property test for skip routing and metadata
    - **Property 7: Skip Routing and Metadata**
    - Generate States with `node_status="skipped"` and varied `skip_reason` strings (valid, empty, null, >255 chars)
    - Assert "next" for valid reasons with correct `skipped_nodes` entry; assert escalation for invalid reasons
    - **Validates: Requirements 3.1, 3.4, 3.5**

- [x] 3. Checkpoint - Ensure state schema and routing tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement Understand Stage nodes
  - [x] 4.1 Implement the `ingest` node
    - Create `src/pipeline/nodes/ingest.py`
    - Read document bytes from `document_versions.storage_ref` via SQLAlchemy
    - Validate MIME type against allowed set (application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, text/plain)
    - Set `raw_content`, `mime_type`, `current_node`, `node_status`, `completed_nodes`
    - Return permanent error for invalid MIME, zero bytes, or unreadable file
    - _Requirements: 8.1, 1.2_

  - [x] 4.2 Implement the `extract_text` node
    - Create `src/pipeline/nodes/extract_text.py`
    - Convert raw_content to plain text based on MIME type (PDF extraction, DOCX extraction, text/plain passthrough)
    - Support skip: if mime_type == "text/plain", set status="skipped" with skip_reason="input_already_text" and copy raw content to extracted_text
    - Set transient error on timeout/memory, permanent error on corruption
    - _Requirements: 8.2, 3.2_

  - [x] 4.3 Implement the `chunk` node
    - Create `src/pipeline/nodes/chunk.py`
    - Split extracted_text into segments of config["chunk_max_size"] with config["chunk_overlap"] overlap
    - Each chunk entry: index, text, start_offset, end_offset
    - Support skip: if len(extracted_text) < config["min_chunk_threshold"], produce single-element chunk list and set status="skipped"
    - Permanent error if extracted_text is None or empty
    - _Requirements: 8.3, 3.3, 1.2_

  - [x] 4.4 Write property test for chunk coverage
    - **Property 11: Chunk Coverage**
    - Generate arbitrary non-empty text and valid chunk_max_size/chunk_overlap parameters
    - Assert union of all chunk text ranges covers every character in original text with no gaps
    - **Validates: Requirements 8.3**

  - [x] 4.5 Implement the `embed` node
    - Create `src/pipeline/nodes/embed.py`
    - Generate vector embeddings for all chunks in a single atomic batch (call embedding API)
    - Store vectors in pgvector-enabled table linked to document_version_id
    - Set embeddings_stored=true on success, false + transient error on any failure
    - Discard all partial results on failure
    - _Requirements: 8.4, 1.2_

- [x] 5. Implement Examine Stage nodes
  - [x] 5.1 Implement the `extract_claims` node
    - Create `src/pipeline/nodes/extract_claims.py`
    - Process each chunk through LLM to identify factual assertions
    - Produce ExtractionResult entries with claim_text, chunk_index, start_offset, end_offset (start < end), confidence
    - Empty claims list is "completed" not error
    - Transient error on LLM API failure
    - _Requirements: 9.1, 9.4_

  - [x] 5.2 Write property test for extraction offset ordering
    - **Property 12: Extraction Offset Ordering**
    - Generate ExtractionResult entries; assert start_offset < end_offset and both within chunk text bounds
    - **Validates: Requirements 9.1**

  - [x] 5.3 Implement the `match_rules` node
    - Create `src/pipeline/nodes/match_rules.py`
    - Compare each claim against compliance rules from config
    - Produce ComplianceVerdict per claim (compliant/non_compliant/indeterminate)
    - Empty claims → empty verdicts (completed, not error)
    - Transient error on LLM API failure, permanent error on missing/unparseable rule config
    - _Requirements: 9.2, 9.4, 9.5_

  - [x] 5.4 Write property test for verdicts-claims length parity
    - **Property 13: Verdicts-Claims Length Parity**
    - Generate non-empty claims lists; assert verdicts list has same length with 1:1 claim_id correspondence
    - **Validates: Requirements 9.2**

  - [x] 5.5 Implement the `score_confidence` node
    - Create `src/pipeline/nodes/score_confidence.py`
    - Refine confidence scores based on verdict certainty and source location completeness
    - Flag claims with confidence < config["confidence_threshold"] as needs_human_review=true
    - Transient error on LLM API failure, permanent error on rule config issue
    - _Requirements: 9.3, 9.4, 9.5_

  - [x] 5.6 Write property test for confidence flagging threshold
    - **Property 14: Confidence Flagging Threshold**
    - Generate verdicts with varied confidence values; assert needs_human_review=true when below threshold and false when at/above (unless non-compliant)
    - **Validates: Requirements 9.3, 4.1**

- [x] 6. Checkpoint - Ensure Understand and Examine stage tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Stay-Alive Stage nodes
  - [x] 7.1 Implement the `route_to_queue` node
    - Create `src/pipeline/nodes/route_to_queue.py`
    - Partition claims into auto_approve (compliant + confidence >= threshold), escalate (non-compliant OR confidence < threshold OR needs_human_review OR permanent-error origin), auto_reject (duplicate claims within same run)
    - Priority: escalate > auto_reject > auto_approve
    - Transient error on resource failure during partitioning
    - _Requirements: 4.4, 10.1_

  - [x] 7.2 Write property test for claim partitioning priority
    - **Property 8: Claim Partitioning Priority**
    - Generate claims with various verdicts and confidence scores; assert each claim appears in exactly one bucket following priority ordering
    - **Validates: Requirements 4.4, 4.1, 4.3**

  - [x] 7.3 Write property test for escalate bucket routing
    - **Property 9: Escalate Bucket Determines Human Review Routing**
    - Generate post-route_to_queue States; assert routing → human_review when escalate non-empty, → finalize when empty
    - **Validates: Requirements 4.5, 4.6**

  - [x] 7.4 Implement the `human_review` interrupt node
    - Create `src/pipeline/nodes/human_review.py`
    - Insert escalated claims into approval_queue with status "pending"
    - Call LangGraph `interrupt()` to suspend graph execution
    - On resume: query decisions table, populate state["decisions"], return completed
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 10.2_

  - [x] 7.5 Write property test for post-human-review routing
    - **Property 15: Post-Human-Review Always Finalizes**
    - Generate States with varied decisions (all approved, all rejected, mixed); assert routing always returns "finalize"
    - **Validates: Requirements 5.6**

  - [x] 7.6 Implement the `finalize` node
    - Create `src/pipeline/nodes/finalize.py`
    - Within single DB transaction: write verified/rejected claims, update runs to "completed", insert audit events
    - Handle human-review-skipped case (no decisions needed)
    - Transient error on DB transaction failure
    - _Requirements: 10.3, 10.4, 10.5, 10.6_

- [x] 8. Implement checkpoint and resume infrastructure
  - [x] 8.1 Create the checkpoint persistence layer
    - Create `src/pipeline/checkpoint.py`
    - Implement `write_checkpoint(session, run_id, step_name, step_order, state)` — single transaction: serialize state to JSONB, write to run_steps.output_state, update status to completed/skipped, set ended_at
    - Implement `create_step_row(session, run_id, step_name, step_order)` — creates run_steps row with status "running" and started_at
    - Handle checkpoint write failure → transient error
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 6.7_

  - [x] 8.2 Write property test for checkpoint-if-and-only-if-success
    - **Property 5: Checkpoint If-And-Only-If Success**
    - Generate node executions with varied statuses; assert checkpoint written iff status is "completed" or "skipped", never for "error" or during retries
    - **Validates: Requirements 6.1, 6.4, 2.4, 6.6**

  - [x] 8.3 Create the resume logic
    - Create `src/pipeline/resume.py`
    - Implement `resume_run(session, run_id)` — query highest step_order with completed/skipped status, load output_state, mark orphaned "running" rows as failed, determine next node via routing function
    - Acquire exclusive advisory lock on run_id to enforce single-writer
    - _Requirements: 6.3, 6.8_

  - [x] 8.4 Write property test for resume restart correctness
    - **Property 10: Resume Restart Correctness**
    - Generate run_steps sequences with varied statuses; assert resume identifies correct last checkpoint and correct next node
    - **Validates: Requirements 6.3, 6.8**

- [x] 9. Assemble the StateGraph and wire all components
  - [x] 9.1 Build the LangGraph StateGraph with all nodes and conditional edges
    - Create `src/pipeline/graph.py`
    - Register all 10 nodes with the StateGraph
    - Register all conditional edges using `add_conditional_edges` with the routing functions from routing.py
    - Set entry point at `ingest`, terminal at END after finalize
    - Include retry edge logic that increments retries dict and restores pre-node checkpoint state
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 9.2 Write property test for stage ordering invariant
    - **Property 1: Stage Ordering Invariant**
    - Generate completed run states; assert completed_nodes follows Understand → Examine → Stay-Alive order
    - **Validates: Requirements 1.1**

  - [x] 9.3 Write property test for node completion contract
    - **Property 16: Node Completion Contract**
    - Generate node executions; assert completed/skipped nodes have current_node set correctly and name appended to completed_nodes; error nodes not in completed_nodes
    - **Validates: Requirements 7.4**

  - [x] 9.4 Create the run initialization endpoint
    - Create `src/pipeline/api.py` with FastAPI endpoints
    - `POST /runs` — create run row, freeze config_snapshot, build initial PipelineState, invoke graph
    - `POST /runs/{run_id}/resume` — trigger resume logic, re-invoke graph from checkpoint
    - Acquire advisory lock on run_id at start
    - _Requirements: 6.3, 5.3_

  - [x] 9.5 Wire the human review polling service
    - Create `src/pipeline/polling.py`
    - Implement polling worker that checks decisions table at config["poll_interval_seconds"]
    - When all decisions received for a run's escalated items, call LangGraph resume API
    - Insert reminder audit events at config["reminder_interval_hours"] intervals
    - _Requirements: 5.3, 5.5_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (Properties 1–16)
- Unit tests validate specific examples and edge cases
- The pipeline reads from and writes to existing core-postgres-schema tables (runs, run_steps, documents, document_versions, claims, approval_queue, decisions, audit_events)
- All LLM interactions (embed, extract_claims, match_rules, score_confidence) should be abstracted behind interfaces to allow mocking in tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "2.5"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.5"] },
    { "id": 5, "tasks": ["4.4", "5.1", "5.3", "5.5"] },
    { "id": 6, "tasks": ["5.2", "5.4", "5.6", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "7.4", "7.6"] },
    { "id": 8, "tasks": ["7.5", "8.1"] },
    { "id": 9, "tasks": ["8.2", "8.3"] },
    { "id": 10, "tasks": ["8.4", "9.1"] },
    { "id": 11, "tasks": ["9.2", "9.3", "9.4", "9.5"] }
  ]
}
```
