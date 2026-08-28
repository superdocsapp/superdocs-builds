# tests/

Two test suites: schema correctness (PostgreSQL) and pipeline logic (pure Python), plus integration tests for infrastructure invariants and domain-level extraction quality.

Current size: **1,083 collected tests** (1,065 passing without a live Postgres; schema tests need one), including ~95 property-based cases across 25 Hypothesis modules (`tests/microfinance/`, `tests/pipeline/`, `tests/test_schema/`).

## Schema Tests (`tests/test_schema/`)

Require PostgreSQL running via `docker compose up -d postgres`.

| File | Properties | Validates |
|------|-----------|-----------|
| `test_source_locations.py` | 5 | start_offset < end_offset CHECK |
| `test_resume_query.py` | 6 | Resume query returns highest completed step |
| `test_run_status.py` | 7 | Run status state machine transitions |

## Pipeline Tests (`tests/pipeline/`)

Pure Python, no database required. Includes unit tests and ~47 property-based cases (P1–P25 plus playbook/finding/rules properties).

### Unit Tests

| File | Covers |
|------|--------|
| `test_state.py` | PipelineState TypedDict + factory |
| `test_config.py` | Config loader, defaults, validation |
| `test_serialization.py` | JSONB round-trip (bytes ↔ base64) |
| `test_routing.py` | All routing conditions per node |
| `test_checkpoint.py` | Checkpoint persistence layer |
| `test_resume.py` | Resume logic + lock acquisition |
| `test_graph.py` | Graph topology (13 nodes, edges, path maps) |
| `test_api.py` | Runs endpoints (start, resume, state, cost, report, stream) |
| `test_polling.py` | Polling service (resume, reminders) |
| `test_nodes_*.py` | Individual node behavior |
| `test_playbook_yaml.py` | Playbook YAML loading + Pydantic validation |
| `test_extensibility.py` | YAML-only rule addition (no .py changes) |
| `test_rules_checking_clean_corpus.py` | Clean corpus → zero findings |
| `test_rules_checking_violation_corpus.py` | Violation corpus → exact citation |
| `test_rules_checking_error_handling.py` | Error path coverage (permanent/transient) |

### Property-Based Tests (Hypothesis)

| File | Properties | Validates |
|------|-----------|-----------|
| `test_properties_state.py` | P6: JSONB round-trip | Serialization fidelity |
| `test_properties_routing.py` | P2: Determinism, P3: Retry, P4: Escalation, P7: Skip | Routing correctness |
| `test_properties_chunk.py` | P11: Chunk coverage | No text gaps |
| `test_properties_examine.py` | P12: Offset ordering, P13: Parity, P14: Flagging | Examine stage invariants |
| `test_properties_stay_alive.py` | P8: Partitioning, P9: Escalate routing, P15: Post-review | Stay-Alive stage |
| `test_properties_checkpoint.py` | P5: Checkpoint iff success | Checkpoint correctness |
| `test_properties_resume.py` | P10: Resume restart | Resume correctness |
| `test_properties_graph.py` | P1: Stage ordering, P16: Completion contract | Graph invariants |
| `test_properties_playbook.py` | P17–P21 | Playbook correctness |
| `test_properties_findings.py` | P22: Finding structural completeness | Finding integrity |
| `test_properties_nodes_rules.py` | P23–P25 | Rules node correctness |

## Microfinance Domain Tests (`tests/microfinance/`) — ~35 property-based cases

| File | Validates |
|------|-----------|
| `test_properties_classifier.py` | Document classification invariants |
| `test_properties_extraction.py` | Structured extraction: offset validity, field coverage, normalization |
| `test_properties_generator.py` | Synthetic document generator determinism |
| `test_properties_source_linker.py` | Span → source_locations attachment integrity |

## Infrastructure & Integration Tests (`tests/test_*.py`)

Pure Python unless noted. Validates system-level invariants from `docs/invariants.md`.

| File | Validates |
|------|-----------|
| `test_resumability.py` | Checkpointed resume: no side-effect replay, state equivalence, orphan cleanup |
| `test_concurrency.py` | Run isolation: per-run_id scoping, no interleaved writes (uses a test-local thread-safe in-memory store) |
| `test_approval_gate.py` | Approval independence: approve/reject one item has zero effect on others (service + REST) |
| `test_approval_persistence_restart.py` | Approval queue survives a real process restart (subprocess phases) |
| `test_conflicts_persistence.py` | Conflicts survive restart with both source documents attributed |
| `test_extract_claims_persistence.py` | Durable claim rows exist even after kill with zero checkpoints |
| `test_persistence_gap_fixes.py` | `completed_with_persistence_gap` status + review dedup behavior |
| `test_paraphrased_extraction.py` | Template vs paraphrased extraction coverage gap (motivates hybrid LLM fallback) |
| `test_prompt_injection_resistance.py` | Hostile document content cannot redirect pipeline behavior |
| `test_unverifiable_citation_e2e.py` | End-to-end unverifiable-citation flagging when span match fails |
| `test_citation_payload.py` | Grounded/unverifiable payload construction |
| `test_incremental_update.py` / `test_incremental_api.py` | Incremental pile updates; contradictions → approval queue, no silent overwrite |
| `test_piles.py` | Pile CRUD + membership |
| `test_cancel.py` | Run cancellation semantics |
| `test_queue_enrichment.py` | Reviewer context enrichment of queue items |
| `test_facts_endpoint.py` / `test_history_endpoint.py` / `test_history_live_endpoint.py` | Inspection/history APIs |
| `test_mcp_integration.py` | Full end-to-end via MCP tools only: start → approve → deliverable → history |
| `test_main.py` | Health endpoint baseline |

## Running

```bash
# All tests (no DB needed for pipeline + invariant tests)
python -m pytest tests/ -v --ignore=tests/test_schema

# Pipeline tests only
python -m pytest tests/pipeline/ -v

# Infrastructure invariant tests only
python -m pytest tests/test_resumability.py tests/test_concurrency.py tests/test_approval_gate.py -v

# MCP integration test only
python -m pytest tests/test_mcp_integration.py -v

# Schema tests only (needs PostgreSQL)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/docdb_test python -m pytest tests/test_schema/ -v
```
