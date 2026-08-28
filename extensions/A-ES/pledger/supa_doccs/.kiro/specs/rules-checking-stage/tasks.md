# Implementation Plan: Rules Checking Stage

## Overview

Implement the `match_rules_against_sources` node and supporting infrastructure to evaluate compliance rules directly against source document spans. The implementation adds Pydantic playbook models, a rule partitioner, evaluator protocol with LLM and structured implementations, the new pipeline node, a merge node, pipeline state extensions, and graph wiring — all designed so that adding a new rule requires only editing YAML (no .py changes).

## Tasks

- [x] 1. Playbook models, loader, and rule partitioner
  - [x] 1.1 Create Pydantic playbook schema and loader module
    - Create `src/pipeline/playbook.py` with `RuleDefinition`, `Playbook` models, `PLAYBOOK_WHITELIST`, `PlaybookLoadError`, and `load_playbook()` async function
    - `RuleDefinition` fields: id, description, check_description, scope (Literal["claims","source","both"]), check_type (Literal["llm","structured"], default "llm")
    - `Playbook` fields: playbook_id, name, version (default "1.0"), rules (list[RuleDefinition])
    - Validators: id_not_empty, rules_have_unique_ids
    - `load_playbook()`: resolve playbook_id via whitelist, load YAML, validate with Pydantic, raise `PlaybookLoadError` on unknown ID or validation failure
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 1.2 Create rule scope partitioner
    - Create `partition_rules()` function in `src/pipeline/playbook.py` (or separate `src/pipeline/partitioner.py`)
    - Returns `PartitionedRules` dataclass with `claims_rules` and `source_rules`
    - Rules with scope "both" appear in both lists
    - _Requirements: 2.1_

  - [x] 1.3 Write property tests for playbook schema and partitioner
    - **Property 1: Playbook Schema Round-Trip** — serialize and re-validate any valid Playbook
    - **Property 2: Invalid Playbook ID Produces Permanent Error** — any non-whitelist string raises PlaybookLoadError
    - **Property 3: Rule Scope Partitioning Correctness** — all rules appear in correct lists, none lost
    - **Property 8: Default Check Type Is LLM** — omitting check_type defaults to "llm"
    - **Property 9: Unbounded Rules Per Playbook** — N rules with unique IDs validate successfully
    - **Validates: Requirements 1.2, 1.3, 1.5, 1.6, 2.1, 7.3**

- [x] 2. Finding and EvaluationResult data models
  - [x] 2.1 Create findings data models
    - Create `src/pipeline/findings.py` with `CitedSpan`, `EvaluationResult`, and `Finding` dataclasses
    - `CitedSpan`: start_offset (int), end_offset (int), text (str)
    - `EvaluationResult`: rule_id, verdict (FindingVerdict), cited_span, explanation, evaluation_method
    - `Finding`: rule_id, verdict (Literal["fail"]), cited_span, explanation, evaluation_method
    - Type aliases: `FindingVerdict`, `EvaluationMethod`
    - _Requirements: 6.4, 6.5, 3.4_

  - [x] 2.2 Write property test for Finding structural completeness
    - **Property 7: Finding Structural Completeness** — every Finding has non-empty rule_id, verdict=="fail", valid cited_span (start < end, non-empty text), non-empty explanation, valid evaluation_method
    - **Validates: Requirements 6.4, 6.5, 3.4**

- [x] 3. Evaluator protocol and implementations
  - [x] 3.1 Create evaluator protocol and LLM evaluator
    - Create `src/pipeline/evaluators.py` with `RuleEvaluator` Protocol, `LLMEvaluator` class
    - `RuleEvaluator` protocol: `async evaluate(rule, span_text, span_offset) -> EvaluationResult`
    - `LLMEvaluator`: implement `evaluate()` and `evaluate_batch()` (multiple rules per span to reduce LLM calls)
    - LLM prompt includes rule description, check_description, source span text, and instructions to return structured verdict
    - On API failure, raise exception (caught by node as transient error)
    - _Requirements: 4.1, 4.2, 4.4, 3.2_

  - [x] 3.2 Create structured evaluator
    - Add `StructuredEvaluator` class to `src/pipeline/evaluators.py`
    - `SUPPORTED_CHECKS` registry mapping check_descriptions to callable logic
    - `supports(rule)` method to check if rule is handled
    - `evaluate()` returns `EvaluationResult` with evaluation_method="structured"
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Pipeline node implementations
  - [x] 5.1 Implement match_rules_against_sources node
    - Create `src/pipeline/nodes/match_rules_against_sources.py`
    - Follow existing node pattern (see `match_rules.py`)
    - Read `source_rules` and `chunks` from state
    - No rules or no chunks → empty findings, status "completed"
    - Partition rules by check_type; batch LLM rules per span via `evaluate_batch()`
    - Structured rules: use structured evaluator if supported, else fallback to LLM with warning
    - Only produce Finding when verdict == "fail"
    - On LLM API failure → transient error state
    - Tag each Finding with evaluation_method
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.3, 4.4, 5.3, 6.1, 6.2, 6.3, 9.1, 9.3_

  - [x] 5.2 Implement merge_findings node
    - Create `src/pipeline/nodes/merge_findings.py`
    - Concatenate `claim_findings` and `source_findings` from state into `findings`
    - No deduplication — both perspectives valid
    - Append "merge_findings" to completed_nodes, set status "completed"
    - _Requirements: 2.3_

  - [x] 5.3 Write property tests for node logic
    - **Property 4: Findings Merge Preserves All Items** — merged list length == sum of inputs, all items present
    - **Property 5: Empty Inputs Produce Empty Findings** — empty spans or empty rules → empty findings, status "completed"
    - **Property 6: Findings Produced If and Only If Verdict Is "fail"** — exactly the "fail" results become findings, no more, no fewer
    - **Validates: Requirements 2.3, 3.3, 6.1, 6.2, 6.3, 4.3, 9.3**

- [x] 6. Pipeline state extension and graph wiring
  - [x] 6.1 Extend PipelineState with rules-checking fields
    - Add to `src/pipeline/state.py`: `playbook_id` (Optional[str]), `source_rules` (list[dict]), `claims_rules` (list[dict]), `findings` (list[dict]), `claim_findings` (list[dict]), `source_findings` (list[dict])
    - Update `create_initial_state()` factory to initialize new fields with defaults
    - _Requirements: 1.7, 2.3_

  - [x] 6.2 Wire new nodes into pipeline graph
    - Update `src/pipeline/graph.py`:
      - Import `match_rules_against_sources` and `merge_findings` nodes
      - Add both to `NODES` dict
      - Update `PATH_MAPS`: `extract_claims` routes to fan-out dispatching both match nodes in parallel; both merge into `merge_findings`; `merge_findings` routes to `score_confidence`
    - _Requirements: 2.2_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Sample playbook YAML and extensibility demonstration
  - [x] 8.1 Create sample playbook YAML file
    - Create `rules/microfinance_v1.yaml` with sample rules (MF-001 APR check, MF-002 processing fee disclosure, MF-003 interest rate match)
    - Ensure playbook validates against Pydantic schema
    - _Requirements: 7.1, 7.2_

  - [x] 8.2 Demonstrate adding a rule without touching .py files
    - Add a new rule (e.g., MF-004) to `rules/microfinance_v1.yaml`
    - Write a test that loads the updated playbook and verifies the new rule is included, partitioned correctly, and evaluable — all without modifying any Python source file
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 9. Integration tests with test corpora
  - [x] 9.1 Create clean corpus integration test
    - Create `tests/pipeline/test_rules_checking_clean_corpus.py`
    - Set up playbook with known rules, source spans from compliant document, mock LLM returning "pass" for all evaluations
    - Assert: findings list is empty, node_status is "completed"
    - _Requirements: 8.1_

  - [x] 9.2 Create violation corpus integration test
    - Create `tests/pipeline/test_rules_checking_violation_corpus.py`
    - Set up playbook with known rules, source spans containing exactly one violation at known offset, mock LLM returning "fail" for violating rule
    - Assert: exactly 1 finding, correct rule_id, cited_span offsets match violation location, correct evaluation_method
    - _Requirements: 8.2_

  - [x] 9.3 Write unit tests for error handling paths
    - Test: unknown playbook_id → permanent error
    - Test: invalid YAML → permanent error with validation details
    - Test: LLM API failure → transient error
    - Test: zero applicable source rules → empty findings, "completed"
    - Test: structured evaluator fallback to LLM with warning
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The hard requirement "adding a rule doesn't touch .py files" is explicitly validated in task 8.2
- Python is the implementation language (matches existing codebase)
- All new modules follow existing conventions (Protocol-based DI, dataclasses/TypedDict for data, async node functions)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.1"] },
    { "id": 2, "tasks": ["1.3", "3.2"] },
    { "id": 3, "tasks": ["5.1", "5.2", "6.1"] },
    { "id": 4, "tasks": ["5.3", "6.2"] },
    { "id": 5, "tasks": ["8.1"] },
    { "id": 6, "tasks": ["8.2", "9.1", "9.2"] },
    { "id": 7, "tasks": ["9.3"] }
  ]
}
```
