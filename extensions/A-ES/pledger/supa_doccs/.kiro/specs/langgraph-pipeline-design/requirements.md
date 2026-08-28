# Requirements Document

## Introduction

This feature defines the LangGraph graph topology for the three-stage document-intelligence pipeline: **Understand**, **Examine**, and **Stay-Alive**. The pipeline processes synthetic microfinance and consumer loan agreements through ingestion, compliance analysis, and human-in-the-loop monitoring. Each stage is decomposed into discrete nodes with conditional routing edges (retry, skip, escalate) driven by node output — not sequential steps with labels. The design must support kill-and-resume semantics via per-node checkpointing against the existing PostgreSQL-backed state, ensuring no completed work is repeated after an interruption.

This is an architecture-level specification. It defines the graph shape, node responsibilities, routing conditions, and checkpoint boundaries. No implementation code is produced by this spec; the output is a signed-off topology that subsequent specs will implement.

## Glossary

- **Graph**: The LangGraph `StateGraph` instance that defines the complete pipeline as a directed graph of nodes and conditional edges.
- **Node**: A discrete unit of work within the Graph, implemented as an async function that receives the current State and returns an updated State. Each Node performs exactly one responsibility.
- **Edge**: A connection between two Nodes. Edges can be unconditional (always traverse) or conditional (traverse based on a routing function applied to the source Node's output).
- **Conditional_Edge**: An edge whose traversal is determined by a routing function that inspects the State returned by the source Node and returns the name of the next Node to invoke.
- **State**: The typed dictionary (TypedDict) that flows through the Graph, accumulating results from each Node. The State is the single source of truth for the current run's progress.
- **Checkpoint**: A durable snapshot of the State persisted to PostgreSQL after a Node completes successfully. Enables kill-and-resume by restoring the last checkpointed State.
- **Understand_Stage**: The first pipeline stage responsible for document ingestion, text extraction, chunking, embedding, and structural comprehension.
- **Examine_Stage**: The second pipeline stage responsible for claim extraction, compliance rule matching, confidence scoring, and violation detection.
- **Stay_Alive_Stage**: The third pipeline stage responsible for human-in-the-loop review, approval queue management, escalation, and run finalization.
- **Routing_Decision**: The string literal returned by a routing function that determines which Node executes next. Valid values per edge are defined in the routing conditions table.
- **Retry**: A Routing_Decision indicating the current Node should re-execute (with incremented retry count) because of a transient or recoverable failure.
- **Skip**: A Routing_Decision indicating the current Node's work should be bypassed (output marked as skipped in State) and the pipeline should advance to the next logical Node.
- **Escalate**: A Routing_Decision indicating the current Node's failure or low-confidence output requires human intervention, routing to the human review queue.
- **Human_Queue**: The `approval_queue` table and associated `decisions` table from the core schema, used to park items requiring human judgment.
- **Run**: A single end-to-end execution of the Graph for one document, tracked in the `runs` table.
- **Run_Step**: A record in `run_steps` corresponding to a single Node execution within a Run, recording status, timing, input/output state references, and retry count.
- **Confidence_Score**: A float between 0.0 and 1.0 representing the model's certainty about an extraction or classification result.
- **Extraction_Result**: The structured output of a claim-extraction Node, containing claims, source locations, and per-claim confidence scores.
- **Compliance_Verdict**: The output of a rule-matching Node, classifying a claim as compliant, non-compliant, or indeterminate with supporting evidence references.

---

## Requirements

### Requirement 1: Graph Topology — Three Stages with Discrete Nodes

**User Story:** As a system architect, I want the pipeline expressed as a LangGraph StateGraph with clearly separated stages and discrete nodes, so that each unit of work is independently testable, checkpointable, and replaceable.

#### Acceptance Criteria

1. THE Graph SHALL contain exactly three stages: Understand_Stage, Examine_Stage, and Stay_Alive_Stage, executed in that order for a nominal run (a run where every node returns `node_status` = "completed" or "skipped").
2. THE Understand_Stage SHALL contain exactly four nodes in the following nominal order: `ingest` (load raw document bytes and metadata), `extract_text` (convert document to plain text), `chunk` (split text into segments of configurable maximum size with default 1000 characters and configurable overlap with default 200 characters), and `embed` (generate vector embeddings for each chunk and store in pgvector).
3. THE Examine_Stage SHALL contain exactly three nodes in the following nominal order: `extract_claims` (identify discrete factual assertions from chunks), `match_rules` (compare each claim against compliance rule definitions), and `score_confidence` (assign a Confidence_Score between 0.0 and 1.0 to each claim-rule pair and produce a Compliance_Verdict).
4. THE Stay_Alive_Stage SHALL contain exactly three nodes in the following nominal order: `route_to_queue` (partition results into auto-approve, escalate-to-human, and reject buckets), `human_review` (an interrupt node that pauses execution until human decisions arrive), and `finalize` (write final statuses, close the Run, and emit audit events).
5. THE Graph SHALL define a single entry point at the `ingest` node and a single terminal node at `finalize`, resulting in exactly 10 nodes total across all three stages.
6. THE Graph SHALL connect nodes within and across stages exclusively via Conditional_Edges, where each edge's routing function inspects the State returned by the source Node. Cross-stage transitions (from `embed` to `extract_claims`, and from `score_confidence` to `route_to_queue`) SHALL use the same Conditional_Edge mechanism as intra-stage transitions.
7. IF a routing function receives a State that does not match any defined routing condition for that edge, THEN THE Graph SHALL treat the outcome as a permanent error, set `node_status` = "error" with `error_type` = "permanent" and `error_detail` indicating the unhandled routing state, and route to `route_to_queue` for escalation.

---

### Requirement 2: Conditional Routing — Retry Logic

**User Story:** As a system operator, I want transient failures in any node to trigger automatic retries with a bounded count, so that intermittent issues (network timeouts, rate limits) resolve without human intervention.

#### Acceptance Criteria

1. WHEN a Node returns a State with `node_status` = "error" and `error_type` = "transient" and the current `retry_count` for that Node is less than the configured maximum (default: 3), THE Routing_Function SHALL return "retry" and the Graph SHALL re-invoke the same Node immediately (no delay) with `retry_count` incremented by 1 and the input State restored to the pre-node Checkpoint State (only the `retries` dictionary is updated).
2. WHEN a Node returns a State with `node_status` = "error" and `error_type` = "transient" and the current `retry_count` equals the configured maximum, THE Routing_Function SHALL return "escalate" and the Graph SHALL route to the `route_to_queue` node with the failure context attached to State, where failure context consists of the failing node name, `error_type`, `error_detail`, and the final `retry_count` for that node.
3. THE State SHALL include a `retries` dictionary keyed by node name, where each value is the current retry count for that node within the current Run. Each node's retry count SHALL be initialized to 0 at the start of the Run and SHALL only be incremented by the retry routing logic.
4. WHEN a retry is triggered, THE Graph SHALL NOT create a new Checkpoint before re-invoking the Node — the pre-node Checkpoint from the previous attempt remains the restore point, ensuring a kill during retry does not record partial progress.
5. IF a Node returns a State with `node_status` = "error" and `error_type` is neither "transient" nor "permanent", THEN THE Routing_Function SHALL treat the error as "permanent" and return "escalate" to route to the `route_to_queue` node.

---

### Requirement 3: Conditional Routing — Skip Logic

**User Story:** As a system architect, I want nodes to support a skip decision when their input is absent or inapplicable, so that the pipeline gracefully handles documents that lack certain structures without failing the entire run.

#### Acceptance Criteria

1. WHEN a Node returns a State with `node_status` = "skipped" and a `skip_reason` string (1 to 255 characters, non-empty), THE Routing_Function SHALL return "next" (advancing to the next node in sequence) and the State SHALL append an entry to `skipped_nodes` containing the node name and the skip reason.
2. WHEN the `extract_text` node receives a document already in plain-text format (MIME type `text/plain`), THE `extract_text` Node SHALL set `node_status` = "skipped" with `skip_reason` = "input_already_text", populate `extracted_text` in State with the raw content from `raw_content` decoded as UTF-8, and return the updated State to the routing function.
3. WHEN the `chunk` node receives `extracted_text` shorter than the minimum chunk threshold (configurable, default: 200 characters), THE `chunk` Node SHALL set `node_status` = "skipped" with `skip_reason` = "below_chunk_threshold" and populate `chunks` in State with a single-element list containing the entire `extracted_text` as one chunk.
4. THE Pipeline SHALL NOT halt or raise an error when a Node returns `node_status` = "skipped" — the run SHALL continue to the next node. A skipped Node MAY populate its designated output keys in State (as defined in criteria 2 and 3) in addition to the skip metadata; downstream nodes SHALL consume whichever State keys are present regardless of whether the producing node completed or was skipped.
5. IF a Node returns `node_status` = "skipped" with `skip_reason` that is null, empty, or exceeds 255 characters, THEN THE Routing_Function SHALL treat the result as an error with `error_type` = "permanent" and route to `route_to_queue` for escalation.

---

### Requirement 4: Conditional Routing — Escalation to Human Queue

**User Story:** As a compliance officer, I want low-confidence results and non-transient failures automatically escalated to the human review queue, so that uncertain outputs are never silently passed through as verified.

#### Acceptance Criteria

1. WHEN the `score_confidence` node produces a Compliance_Verdict with `confidence` below the escalation threshold (configurable, default: 0.7), THE Routing_Function SHALL return "escalate" and the Graph SHALL route to `route_to_queue` with the low-confidence claims marked with `needs_human_review` = true in the `verdicts` list within State.
2. WHEN any Node returns `node_status` = "error" and `error_type` = "permanent" (non-retryable failure), THE Routing_Function SHALL return "escalate" and the Graph SHALL route to `route_to_queue` with the State containing the failing node name in `current_node`, the `error_detail` string describing the failure reason, and the `error_type` value preserved for human triage.
3. WHEN the `match_rules` node produces a Compliance_Verdict of "non-compliant" for any claim, THE Routing_Function SHALL return "escalate" for those claims regardless of confidence score, routing them to human review.
4. THE `route_to_queue` Node SHALL partition all pending claims into three buckets based on the routing conditions: `auto_approve` (compliant + confidence >= threshold), `escalate` (non-compliant OR confidence < threshold OR `needs_human_review` = true OR originating from a permanent-error escalation), and `auto_reject` (claims matching any rule in the configured `auto_reject_rules` list, which SHALL include at minimum a duplicate-claim-within-same-Run rule). Claims matching multiple conditions SHALL be placed in the highest-priority bucket in the order: escalate > auto_reject > auto_approve.
5. WHEN the `route_to_queue` Node produces an `escalate` bucket with one or more items, THE Graph SHALL transition to the `human_review` interrupt node for those items.
6. WHEN the `route_to_queue` Node produces only `auto_approve` and `auto_reject` buckets with zero `escalate` items, THE Graph SHALL skip the `human_review` node and proceed directly to `finalize`.
7. IF the `route_to_queue` Node fails during partitioning (returns `node_status` = "error"), THEN THE Node SHALL set `error_type` = "transient" to trigger retry logic, because the partitioning operation is deterministic and a failure is due to a transient resource issue rather than invalid input.

---

### Requirement 5: Conditional Routing — Human Review Interrupt

**User Story:** As a compliance reviewer, I want the pipeline to pause and wait for my approve/reject decisions on escalated items, resuming processing only after all escalated items have been decided.

#### Acceptance Criteria

1. THE `human_review` Node SHALL be implemented as a LangGraph interrupt node that suspends Graph execution and persists the current State as a Checkpoint.
2. WHILE the `human_review` Node is in interrupted state, THE Run SHALL have status "running" and the corresponding Run_Step SHALL have status "running" with `start_timestamp` set and `end_timestamp` NULL.
3. WHEN the number of Decisions recorded in the `decisions` table for the current Run's escalated `approval_queue` entries equals the number of items in the State's `queue_buckets["escalate"]` list, THE Graph SHALL resume execution from the `human_review` Checkpoint. THE resume SHALL be triggered by an external signal (API call or polling mechanism querying the `decisions` table at a configurable interval, default: 30 seconds) rather than by internal graph execution.
4. WHEN the `human_review` Node resumes, THE Node SHALL read all Decisions from the `decisions` table for the current Run's escalated `approval_queue` entries, update the State's `decisions` list with the approved/rejected status for each claim, and return the updated State to the routing function.
5. IF any escalated item remains without a Decision for longer than a configurable timeout (default: 72 hours), THEN THE `human_review` Node SHALL insert an Audit_Event with action "reminder_sent" for each unresolved `approval_queue` entry, repeating at a configurable interval (default: every 24 hours) until a Decision is recorded, but SHALL NOT auto-resolve the item — it remains pending until a human acts.
6. THE Routing_Function after `human_review` SHALL return "finalize" to proceed to the `finalize` node regardless of whether individual items were approved or rejected.

---

### Requirement 6: Checkpoint Strategy — Per-Node Durable Snapshots

**User Story:** As a system operator, I want the full State checkpointed to PostgreSQL after every successfully completed node, so that a kill-and-resume restores exactly the last good state without repeating finished work.

#### Acceptance Criteria

1. THE Graph SHALL persist a Checkpoint to PostgreSQL after each Node completes with `node_status` = "completed" or "skipped", before the Conditional_Edge routing function for that Node executes. THE Checkpoint write and the `run_steps` row status update to "completed" or "skipped" SHALL occur within a single database transaction.
2. THE Checkpoint SHALL contain the complete State dictionary serialized as JSONB written to the `output_state` column of the corresponding `run_steps` row, along with the Run identifier (`run_id`), the node name (`step_name`), the `step_order` value as the monotonically increasing sequence number, and the `ended_at` timestamp.
3. WHEN a Run is resumed after a kill or crash, THE Graph SHALL query `run_steps` for the row with the highest `step_order` where `status` = "completed" or "skipped" for that `run_id`, load the `output_state` JSONB as the restored State, and begin execution from the Conditional_Edge following the checkpointed Node — the completed Node SHALL NOT re-execute.
4. WHEN a Node fails (returns `node_status` = "error"), THE Graph SHALL NOT persist a Checkpoint for that Node execution, preserving the prior Checkpoint as the restore point.
5. THE Graph SHALL create a `run_steps` row with status "running" and `started_at` set before invoking each Node, so that the row exists to receive the `output_state` Checkpoint upon successful completion.
6. WHILE a retry cycle is in progress for a given Node, THE Graph SHALL NOT overwrite the pre-node Checkpoint — only the final successful (or escalated) outcome persists a new Checkpoint. Each retry attempt SHALL reuse the same `run_steps` row by incrementing its `retry_count` and resetting `started_at`.
7. IF the Checkpoint write to PostgreSQL fails (transaction cannot commit), THEN THE Graph SHALL treat the Node as failed with `error_type` = "transient", triggering the retry routing logic for that Node and incrementing that Node's retry count in State.
8. IF a Run is resumed and a `run_steps` row exists with status "running" and `ended_at` NULL from a prior interrupted execution, THEN THE Graph SHALL update that row's status to "failed" with `error_details` indicating interruption before proceeding to re-execute from the last successfully checkpointed Node.

---

### Requirement 7: State Schema — Typed Run State

**User Story:** As a developer, I want the pipeline State to be a well-defined TypedDict that accumulates results across nodes, so that each node's inputs and outputs are explicit and type-checkable.

#### Acceptance Criteria

1. THE State SHALL include the following top-level keys: `run_id` (UUID), `document_id` (UUID), `document_version_id` (UUID), `current_node` (string), `node_status` (literal: "completed" | "skipped" | "error"), `error_type` (nullable literal: "transient" | "permanent"), `error_detail` (nullable string), `retries` (dict of node_name → int), `skipped_nodes` (list of dicts with node_name and reason), and `config` (dict of configurable thresholds and limits).
2. THE State SHALL include stage-specific accumulation keys: `raw_content` (nullable bytes), `extracted_text` (nullable string), `chunks` (list of chunk dicts), `embeddings_stored` (boolean), `claims` (list of Extraction_Result dicts), `verdicts` (list of Compliance_Verdict dicts), `queue_buckets` (dict with keys auto_approve, escalate, auto_reject each containing lists of claim IDs), and `decisions` (list of Decision dicts populated after human_review).
3. THE State SHALL include a `completed_nodes` list that records the ordered sequence of successfully completed node names, used by the resume logic to determine the restart point.
4. WHEN a Node completes, THE Node SHALL update `current_node` to its own name, set `node_status` appropriately, and append its name to `completed_nodes` (only for status "completed" or "skipped").
5. THE State SHALL be serializable to JSONB without loss of information — all values SHALL be JSON-native types (strings, numbers, booleans, lists, dicts, null) or explicitly converted before checkpoint write.

---

### Requirement 8: Node Responsibilities — Understand Stage

**User Story:** As a developer, I want each Understand_Stage node to have a single, well-defined responsibility, so that failures are isolated and the stage can be tested node-by-node.

#### Acceptance Criteria

1. THE `ingest` Node SHALL read the document bytes from the storage reference in `document_versions`, validate the MIME type against the allowed set, populate `raw_content` in State, and set `node_status` = "completed". IF the document cannot be read, has an invalid MIME type, or the retrieved content is zero bytes, THEN the `ingest` Node SHALL set `node_status` = "error" with `error_type` = "permanent".
2. THE `extract_text` Node SHALL convert `raw_content` to plain text (PDF → text extraction, DOCX → text extraction, plain text → passthrough), populate `extracted_text` in State, and set `node_status` = "completed". IF conversion fails due to a corrupted file, THEN the Node SHALL set `node_status` = "error" with `error_type` = "permanent". IF conversion exceeds the configured timeout (default: 60 seconds) or exceeds available memory allocation, THEN the Node SHALL set `node_status` = "error" with `error_type` = "transient".
3. THE `chunk` Node SHALL split `extracted_text` into segments of configurable maximum size (default: 1000 characters) with configurable overlap (default: 200 characters), populate `chunks` in State where each chunk entry contains the chunk index, text content, start character offset, and end character offset, and set `node_status` = "completed". IF `extracted_text` is empty or null, THEN the `chunk` Node SHALL set `node_status` = "error" with `error_type` = "permanent".
4. THE `embed` Node SHALL generate vector embeddings for each chunk in a single atomic operation, store embedding vectors in the pgvector-enabled table linked to the `document_version_id`, set `embeddings_stored` = true in State, and set `node_status` = "completed". IF the embedding API call fails for any chunk in the batch, THEN the Node SHALL discard all partial results for that invocation, set `embeddings_stored` = false, and set `node_status` = "error" with `error_type` = "transient".

---

### Requirement 9: Node Responsibilities — Examine Stage

**User Story:** As a developer, I want each Examine_Stage node to have a single, well-defined responsibility for compliance analysis, so that extraction, rule-matching, and scoring are independently testable and replaceable.

#### Acceptance Criteria

1. THE `extract_claims` Node SHALL process each chunk, identify discrete factual assertions (e.g., "APR is 24%", "processing fee is 500 PHP"), create Extraction_Result entries with claim text, source location (chunk index, start character offset, end character offset where start < end), and a preliminary Confidence_Score (float between 0.0 and 1.0 inclusive), populate `claims` in State, and set `node_status` = "completed". IF no claims are found in any chunk, THEN the Node SHALL set `node_status` = "completed" with an empty `claims` list (not an error).
2. THE `match_rules` Node SHALL compare each extracted claim against the configured set of compliance rules referenced in `config` (e.g., maximum APR thresholds, required disclosure checks, prohibited fee structures), produce a Compliance_Verdict for each claim (compliant, non-compliant, or indeterminate), populate `verdicts` in State, and set `node_status` = "completed". IF the `claims` list in State is empty, THEN the Node SHALL set `node_status` = "completed" with an empty `verdicts` list (not an error).
3. THE `score_confidence` Node SHALL refine the Confidence_Score for each claim-verdict pair by evaluating the verdict classification certainty (how decisively the claim matched or failed a rule) and the source location completeness (whether offsets resolve to extractable text in the original chunk), update the `verdicts` list with final Confidence_Score values (float between 0.0 and 1.0 inclusive), and set `node_status` = "completed". Claims with `confidence` below the escalation threshold (as defined in `config`, default: 0.7) SHALL be flagged with `needs_human_review` = true.
4. IF the `extract_claims`, `match_rules`, or `score_confidence` Node encounters an LLM API failure (timeout, rate-limit, or connection error), THEN the Node SHALL set `node_status` = "error" with `error_type` = "transient" to trigger retry logic.
5. IF the `match_rules` or `score_confidence` Node encounters a non-recoverable failure (e.g., rule configuration missing or unparseable), THEN the Node SHALL set `node_status` = "error" with `error_type` = "permanent" to trigger escalation.

---

### Requirement 10: Node Responsibilities — Stay-Alive Stage

**User Story:** As a developer, I want the Stay-Alive stage to handle human-in-the-loop gating, run finalization, and ensure no claim reaches "verified" status without appropriate review, so that the pipeline's output is trustworthy and auditable.

#### Acceptance Criteria

1. THE `route_to_queue` Node SHALL read the `verdicts` list from State and partition claims into `auto_approve` (compliant + confidence >= threshold), `escalate` (non-compliant OR confidence < threshold OR flagged `needs_human_review`), and `auto_reject` (duplicate claims within the same Run, identified by matching extracted text and source location against previously processed claims in the current Run), populate `queue_buckets` in State, and set `node_status` = "completed".
2. THE `human_review` Node SHALL insert all `escalate`-bucket claims into the `approval_queue` table with status "pending", then invoke LangGraph's `interrupt()` to pause execution. WHEN resumed, the Node SHALL query the `decisions` table for all queued items, populate `decisions` in State, and set `node_status` = "completed".
3. THE `finalize` Node SHALL, within a single database transaction: write all `auto_approve`-bucket claims and all human-approved claims (from `decisions` with value "approved") to the `claims` table with status "verified"; write all `auto_reject`-bucket claims and all human-rejected claims (from `decisions` with value "rejected") to the `claims` table with status "rejected"; update the `runs` table row for the current Run to status "completed" with `end_timestamp` set to the current time; insert one audit event per claim status change (to "verified" or "rejected") and one audit event for the Run status change to "completed"; and set `node_status` = "completed".
4. IF the `finalize` Node's database transaction fails, THEN the Node SHALL set `node_status` = "error" with `error_type` = "transient" to allow retry (the transaction is atomic — partial writes are impossible).
5. WHEN the `finalize` Node completes successfully, THE Graph SHALL terminate the Run and return the final State as the pipeline output.
6. IF the `human_review` Node is skipped (escalate bucket is empty), THEN THE `finalize` Node SHALL treat all `auto_approve`-bucket claims as approved and all `auto_reject`-bucket claims as rejected without requiring entries in the `decisions` list.

---

### Requirement 11: Routing Conditions Table

**User Story:** As a system architect, I want all routing conditions documented in a single reference table, so that the graph's branching logic is unambiguous and reviewable at a glance.

#### Acceptance Criteria

1. THE Requirements Document SHALL include a routing conditions table with the following columns: Source Node, Condition (predicate on State), Routing_Decision (literal string), and Target Node.
2. THE routing conditions table SHALL define entries for every Conditional_Edge in the Graph — no edge SHALL exist without a corresponding table entry, and the total row count SHALL equal the total number of Conditional_Edges defined across the Graph topology.
3. EACH routing condition SHALL be expressed as a boolean expression over State dictionary keys using Python comparison and logical operators (e.g., `state["node_status"] == "error" and state["error_type"] == "transient" and state["retries"][node] < max_retries`).
4. FOR each Source Node, the set of routing conditions SHALL be mutually exclusive (no two conditions can evaluate to true for the same State) and collectively exhaustive (every possible State produced by that Node matches exactly one condition), ensuring deterministic routing with no unhandled State.
5. THE routing conditions table SHALL cover, for each source node, all terminal states that node can produce as defined by its node responsibility specification: at minimum `completed`, plus `skipped` if the node supports skip logic, plus `transient error within retry limit`, `transient error at retry limit`, and `permanent error` if the node can produce those error types.
6. IF a new Conditional_Edge is added to the Graph topology without a corresponding entry in the routing conditions table, THEN the Requirements Document SHALL be considered incomplete and SHALL fail review validation.

---

## Routing Conditions Reference Table

| Source Node | Condition | Decision | Target Node |
|---|---|---|---|
| `ingest` | `node_status == "completed"` | next | `extract_text` |
| `ingest` | `node_status == "error" and error_type == "permanent"` | escalate | `route_to_queue` |
| `extract_text` | `node_status == "completed"` | next | `chunk` |
| `extract_text` | `node_status == "skipped"` | next | `chunk` |
| `extract_text` | `node_status == "error" and error_type == "transient" and retries < max` | retry | `extract_text` |
| `extract_text` | `node_status == "error" and error_type == "transient" and retries >= max` | escalate | `route_to_queue` |
| `extract_text` | `node_status == "error" and error_type == "permanent"` | escalate | `route_to_queue` |
| `chunk` | `node_status == "completed"` | next | `embed` |
| `chunk` | `node_status == "skipped"` | next | `embed` |
| `embed` | `node_status == "completed"` | next | `extract_claims` |
| `embed` | `node_status == "error" and error_type == "transient" and retries < max` | retry | `embed` |
| `embed` | `node_status == "error" and error_type == "transient" and retries >= max` | escalate | `route_to_queue` |
| `extract_claims` | `node_status == "completed"` | next | `match_rules` |
| `extract_claims` | `node_status == "error" and error_type == "transient" and retries < max` | retry | `extract_claims` |
| `extract_claims` | `node_status == "error" and error_type == "transient" and retries >= max` | escalate | `route_to_queue` |
| `match_rules` | `node_status == "completed"` | next | `score_confidence` |
| `match_rules` | `node_status == "error" and error_type == "transient" and retries < max` | retry | `match_rules` |
| `match_rules` | `node_status == "error" and error_type == "transient" and retries >= max` | escalate | `route_to_queue` |
| `score_confidence` | `node_status == "completed"` | next | `route_to_queue` |
| `score_confidence` | `node_status == "error" and error_type == "transient" and retries < max` | retry | `score_confidence` |
| `score_confidence` | `node_status == "error" and error_type == "transient" and retries >= max` | escalate | `route_to_queue` |
| `route_to_queue` | `node_status == "completed" and escalate_bucket is non-empty` | escalate | `human_review` |
| `route_to_queue` | `node_status == "completed" and escalate_bucket is empty` | next | `finalize` |
| `human_review` | `node_status == "completed"` (all decisions received) | finalize | `finalize` |
| `finalize` | `node_status == "completed"` | end | `END` |
| `finalize` | `node_status == "error" and error_type == "transient" and retries < max` | retry | `finalize` |
| `finalize` | `node_status == "error" and error_type == "transient" and retries >= max` | escalate | (manual intervention required — Run marked "failed") |

