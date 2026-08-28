# PROGRESS.md

**Project Start Date:** 2026-08-08

## 2026-08-08 — Phase 1 complete

**Built:**
- Core Postgres schema design (reviewed)
- LangGraph node/edge structure + routing conditions (reviewed)

## 2026-08-08 — Core Schema Implementation complete

**Built:**
- 7 SQL migration files (001–007), verified against live PostgreSQL 16
- 10 database tables: documents, document_versions, runs, run_steps, claims, source_locations, approval_queue, decisions, audit_events, schema_migrations
- 3 database triggers: version immutability, run status state machine, audit append-only guard, decision pending guard
- 23 indexes for query performance
- Migration runner (`migrations/run_migrations.py`) with idempotency and transaction safety
- 8 SQLAlchemy model modules with relationships and OCC version columns
- 14 property-based tests (Hypothesis) — all passing (15 test functions, 100 examples each)

**Key schema features:**
- Content-hash deduplication for document versions
- Run status state machine enforced at DB level (pending → running → completed|failed|cancelled)
- Append-only audit trail with trigger protection
- Optimistic concurrency control on runs, run_steps, approval_queue
- ON DELETE RESTRICT on all parent-child FK relationships
- IF NOT EXISTS on all DDL for migration idempotency

## 2026-08-08 — LangGraph Pipeline Implementation complete

**Built:**
- Full 3-stage pipeline: Understand (4 nodes) → Examine (3 nodes) → Stay-Alive (3 nodes)
- 10 async pipeline nodes with dependency-injected services (LLM, storage, DB)
- Routing function factory with per-node conditional edge logic (retry, skip, escalate, unhandled fallback)
- State schema (`PipelineState` TypedDict) with JSONB serialization round-trip
- Config loader with constraint validation and defaults
- Checkpoint persistence layer (write iff success, never on error/retry)
- Kill-and-resume logic with advisory lock enforcement and orphan cleanup
- LangGraph StateGraph assembly module (all nodes + conditional edges registered)
- FastAPI endpoints: `POST /runs` (create), `POST /runs/{id}/resume`
- Human review polling service (decision completeness checks + reminder audit events)
- 489 pipeline tests passing (unit tests + 16 property-based correctness tests)

**Property-based tests (Hypothesis) verify:**
- P1: Stage ordering invariant
- P2: Routing determinism (exactly one match)
- P3: Retry routing correctness
- P4: Unrecognized error type escalation
- P5: Checkpoint iff success
- P6: State JSONB round-trip
- P7: Skip routing and metadata
- P8: Claim partitioning priority
- P9: Escalate bucket determines human review routing
- P10: Resume restart correctness
- P11: Chunk coverage (no gaps)
- P12: Extraction offset ordering
- P13: Verdicts-claims length parity
- P14: Confidence flagging threshold
- P15: Post-human-review always finalizes
- P16: Node completion contract

**Still open / next:**
- LangGraph runtime integration (requires `langgraph` package install)
- Wire real PDF/DOCX extractors (pdfplumber, python-docx)
- Wire real embedding service (OpenAI, etc.)
- Wire real LLM client for rule evaluation (currently protocol-based, mock-tested)
- MCP + React UI + cost tracking

## 2026-08-12 — Microfinance Ingestion Pipeline complete

**Built:**
- `classify_document` node (MIME validation, threshold-based "unclassified" routing, custom routing function)
- 3 type-specific extractors: `LoanAgreementExtractor` (9 fields), `ModificationExtractor` (per-change groups), `RepaymentExtractor` (per-row parsing)
- `SourceLinker` (attach + resolve) + `persist_fact` utility (claim_type compound naming)
- Extractor registry with strategy dispatch in `extract_claims`
- Synthetic document generator (deterministic 5-doc piles with 2 factual conflicts)
- 20 Hypothesis property tests (classification, extraction, normalization, source linking, generator)
- End-to-end provenance test (all 5 synthetic docs → extract → source-link → resolve → verify)
- 807 total tests passing

## 2026-08-12 — Rules Checking Stage implementation complete

**Built:**
- `src/pipeline/playbook.py` — Pydantic playbook schema (`RuleDefinition`, `Playbook`), `load_playbook()` async loader, `PLAYBOOK_WHITELIST`, `partition_rules()` scope partitioner
- `src/pipeline/findings.py` — `CitedSpan`, `EvaluationResult`, `Finding` dataclasses + type aliases (`FindingVerdict`, `EvaluationMethod`)
- `src/pipeline/evaluators.py` — `RuleEvaluator` protocol, `LLMEvaluator` (batch multiple rules per span), `StructuredEvaluator` (deterministic, registry-based, with sample APR check)
- `src/pipeline/nodes/match_rules_against_sources.py` — new node evaluating rules against source spans; partitions by check_type, batches LLM calls, produces findings only on `verdict == "fail"`
- `src/pipeline/nodes/merge_findings.py` — concatenates `claim_findings` + `source_findings` with no deduplication
- Extended `PipelineState` with `playbook_id`, `source_rules`, `claims_rules`, `findings`, `claim_findings`, `source_findings`
- Updated `graph.py` — 13 nodes, sequential flow: `extract_claims` → `match_rules` → `match_rules_against_sources` → `merge_findings` → `score_confidence`
- `rules/microfinance_v1.yaml` — sample playbook with 4 compliance rules (MF-001 through MF-004)
- 58 new tests (all passing): 9 property-based (Hypothesis), 3 integration (clean corpus, violation corpus, extensibility), 5 error handling, 1 YAML validation
- Extensibility validated: added MF-004 rule via YAML only — no Python file modified

**Property-based tests verify:**
- P17: Playbook schema round-trip
- P18: Invalid playbook ID → permanent error
- P19: Rule scope partitioning correctness (no rules lost)
- P20: Default check_type is "llm"
- P21: Unbounded rules per playbook
- P22: Finding structural completeness (all fields valid)
- P23: Findings merge preserves all items
- P24: Empty inputs → empty findings + "completed"
- P25: Findings produced iff verdict is "fail"

**873 total tests passing.**

## 2026-08-22 — Incremental Update Path complete

**Built:**
- `src/pipeline/incremental_api.py` — API module for focused incremental document updates
- `POST /piles/{pile_id}/incremental` — upload document + incremental update (no full re-run)
- `PATCH /piles/{pile_id}/watch` — configure watched folder path per pile (stored in pile metadata JSONB)
- Wired into `main.py` with shared `ApprovalService` instance
- Frontend: `uploadIncrementalDocument()` API function + "Add document (incremental)" button in PilesPanel
- 13 new tests (`tests/test_incremental_api.py`) — all passing
- FolderWatcher now connected to the pile system via the incremental API

### How the Incremental Path Differs from a Full Run

| Aspect | Full Run (`POST /runs/start`) | Incremental (`POST /piles/{pile_id}/incremental`) |
|--------|-------------------------------|---------------------------------------------------|
| **Nodes executed** | All 13 (ingest → finalize) | Only 3: text-extract, classify, extract-claims — for the new doc only |
| **Scope** | Processes the entire document corpus from scratch | Processes ONLY the new document |
| **Deliverable** | Built fresh from all claims | Reconstructed from latest completed run, then surgically updated |
| **Unaffected sections** | Rebuilt entirely | Byte-identical (SHA-256 verified, never touched) |
| **Conflict handling** | Findings → approval queue | Contradictions → approval queue with `item_type="conflict"` |
| **Silent overwrite** | N/A | Never — contradictions always routed to human gate |
| **Trigger** | Manual (UI "Start Run" button) | "Add document (incremental)" button or FolderWatcher scan |
| **Cost** | Full LLM pipeline (13 nodes, all chunks) | Minimal LLM usage (classify + extract for 1 doc) |
| **Audit trail** | Run + RunStep records | `audit_events` with `action="incremental_update"` |

### Invariants Guaranteed

1. **Hash identity**: Sections not affected by the new document retain their exact SHA-256 content hash. Verified by `TestIncrementalApiHashIdentity` (4 tests).

2. **No silent overwrite**: When a new document contradicts an existing claim (same section key, different value), the conflict lands in the approval queue as a pending item. The original deliverable section is never auto-modified. Verified by `TestIncrementalApiContradiction` (4 tests).

3. **Existing gates re-used**: Conflicts use the same `ApprovalService` → `POST /approval/items/{id}/decide` flow as the full pipeline's stay-alive stage.

4. **Audit events emitted**: Every incremental update records an `audit_events` row with before/after section hashes and the list of affected sections.

### Watched Folder Configuration

A pile can optionally have a `watched_folder_path` in its metadata (set via `PATCH /piles/{pile_id}/watch`). The `FolderWatcher` class (already implemented) can monitor this path and call `process_single_file()` when new documents appear, triggering the same incremental engine internally.

**886 total tests passing (873 + 13 new).**

## Assumptions Log

| Date | Assumption | Reasoning |
|------|------------|-----------|
| 2026-08-08 | OCC version increment is application-enforced via WHERE clause, not auto-managed by SQLAlchemy | Gives explicit control over conflict detection and retry logic |
| 2026-08-08 | Tests use transaction rollback isolation (no cleanup between tests) | Faster tests, zero side effects between runs |
| 2026-08-24 | Migration 010 extends `approval_queue` (nullable `claim_id`, new `run_id`/`item_type`/`payload`/`decided_at`) instead of reusing the table as-is | The Phase 2.3 schema modeled claim-scoped rows only; the ApprovalService contract requires run-scoped items with JSONB payloads, and items can exist without a backing claims row. `decisions` needed no changes — justification/reviewer stay there, sourced via LEFT JOIN. |
| 2026-08-24 | Malformed (non-UUID) item ids are treated as "not found" rather than a parse error | The store keys items by server-generated UUIDs; a non-UUID id cannot exist, so ItemNotFoundError preserves the original REST 404 contract (`tests/test_approval_gate.py::test_nonexistent_item_returns_404`). |
| 2026-08-24 | `persist_fact()` is now called at extract_claims NODE COMPLETION (both executors); the JSONB checkpoint is unchanged | The tables are the durable queryable record; the checkpoint remains the resumability mechanism. Persistence is idempotent per run (delete-then-insert) so resumed/retried runs don't duplicate rows. Test: `tests/test_extract_claims_persistence.py` proves rows exist after a real process kill with zero checkpoints written. |
| 2026-08-24 | All-zero `start_offset` values in run d039ebef were a BUG, not chunk-relative-by-design | demo_executor's LLM extraction path hardcoded `start_offset=0, end_offset=len(claim_text)` — verified numerically (all 4 stored end_offsets exactly equal claim-text lengths; impossible for real document spans). Fixed by locating claim text in extracted_text/chunks; regex-fallback offsets were also chunk-relative and are now document-level. Unlocatable text → citation_status "unverifiable". |
| 2026-08-24 | Pipeline tests that delete runs must first delete their claims/source_locations | claims.run_id FK is ON DELETE RESTRICT by design (durable audit record); until persistence was wired, the tables were always empty so tests never hit the constraint. Cleanup helpers updated in test_piles.py. |
| 2026-08-24 | History endpoint wired to audit_events via SQLHistoryStore; decisions/nodes/incremental writes are schema-conforming now | Phase 5.2's 503 was two bugs: set_history_store() never called, AND the incremental flow's audit writes used enum values ('pile', 'incremental_update') rejected by migration 006's CHECK constraints — failing silently since Day 1. Migration 012 legalizes 'pile'; incremental-update events now use entity_type='run'/action='updated'. Original Phase 5.2 test could never have caught this: it injected its own InMemoryAuditStore into the very seam that was broken and bypassed production writers entirely. Live rerun: tests/test_history_live_endpoint.py. |
| 2026-08-24 | Conflicts reuse `approval_queue` (item_type='conflict') instead of a new table; exposed via GET /runs/{id}/conflicts | The queue was designed with a 'conflict' item type and the incremental engine already routed contradictions there (`incremental.py` `enqueue_item(item_type="conflict")` with full existing/new claim attribution in payload). Reusing it gives conflicts the pending→approved/rejected lifecycle, decisions, reviewer attribution, and Postgres durability for free — a separate table would duplicate all of that and split review state across two stores. Since migration 010 made the queue durable, conflicts already survive restarts; only the read endpoint was missing. Test: tests/test_conflicts_persistence.py (real process restart, conflict still pending with both source documents attributed). |
| 2026-08-24 | B-fixer followups: human_review enqueue dedup + 'completed_with_persistence_gap' run status (migration 013) | _node_human_review now dedups by claim_id exactly like populate-queue's backfill, so node re-execution can't create duplicate pending items. Durability writes (claims/source_locations, audit_events) retry ONCE then flag `_persistence_gap`; the run then ends 'completed_with_persistence_gap' instead of a plain 'completed', visible in GET /runs without opening details. Deliberate cuts, documented not fixed: B2's transient-finalize-failure handling and B4's checkpoint-before-audit ordering window remain as-is. Tests: tests/test_persistence_gap_fixes.py. |

**Approval queue is now Postgres-backed** (`src/pipeline/approval_postgres.py`), replacing the in-memory store whose contents were lost on every restart: enqueue → one `approval_queue` row; decide → atomic INSERT into `decisions` + status transition under `SELECT ... FOR UPDATE` (the Phase 2.3 guard trigger enforces decision-before-status ordering). Durability across a real process restart is proven by `tests/test_approval_persistence_restart.py` (subprocess phases) and verified live against the dockerized API (`docker compose restart api` between seed and read).

## 2026-08-26 — Documentation audit: info files synced to current state

Full drift audit of README/src/tests docs against code. Corrections:

| Doc claim (stale) | Actual state |
|---|---|
| 8 migrations / 10 tables | 15 migrations / 13 tables (`piles`, `pile_documents`, `deliverables`) |
| "No real LLM calls" | DeepSeek client wired (`src/llm/deepseek_client.py`), env-gated; used by `demo_executor.run_pipeline` with SSE streaming |
| "No LangGraph runtime" | langgraph installed (1.2.x); `graph.py` compiles a real `StateGraph`; custom executor still owns checkpointing |
| "Regex extraction as default" (DECISIONS PENDING) | Implemented as **hybrid**: structured-first + field-level LLM fallback for known types; LLM-only path for unregistered types; per-claim `_extraction_method` recorded (migration 014); verbatim-quote citation strategy with `citation_status: unverifiable` downgrade |
| "embed node is a no-op stub" | Fully implemented behind `EmbeddingService`/`VectorStore` protocols; no default provider configured |
| MCP 6 tools | 8 tools (+ `get_run_cost`, `cancel_run`) |
| "870+ tests (25 property-based)" / "886 total" | 1,078 collected; ~95 property-based cases across 25 Hypothesis modules |

**Known issue surfaced by audit:** `tests/test_concurrency.py` failed collection — imported `ThreadSafeCheckpointStore`, removed from `src/pipeline/stores.py` in commit ac65af8 ("removing mock / dead elements"). **Resolved same day:** the store now lives in the test file itself (matching the convention of test_resumability's local InMemoryCheckpointStore), rebuilt as genuinely thread-safe — mutex-guarded step rows keyed `(run_id, step_order)` plus atomic per-run_id `threading.Lock`s with the executor's blocking-wait protocol (`_get_run_lock`). All 5 concurrency tests pass; full non-DB suite green (1,065 passed).

Updated: `README.md`, `src/README.md`, `tests/README.md`, `docs/invariants.md` (section renumbering), recreated `frontend/README.md`. DECISIONS.md pending extraction item marked RESOLVED with implementation evidence.
