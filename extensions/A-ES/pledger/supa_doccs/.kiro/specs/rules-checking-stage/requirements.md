# Requirements Document

## Introduction

The Rules Checking Stage adds a parallel source-evaluation node (`match_rules_against_sources`) to the LangGraph pipeline. While the existing `match_rules` node checks extracted claims against compliance rules, the new node evaluates rules directly against source document spans. Rules are authored in YAML playbooks, loaded and validated at run time, and evaluated via LLM (default) or structured checks (opt-in). Both nodes' findings converge before human review. The system guarantees honest output — no padded or forced findings — and exact source citations on every finding.

## Glossary

- **Pipeline**: The LangGraph-based document intelligence pipeline that processes microfinance documents through Understand, Examine, and Stay-Alive stages.
- **match_rules_against_sources Node**: A new LangGraph node that evaluates compliance rules directly against source document spans rather than extracted claims.
- **match_rules Node**: The existing LangGraph node that evaluates compliance rules against extracted claims.
- **Playbook**: A YAML file under `rules/` containing a list of compliance rules with metadata and evaluation instructions.
- **Rule**: A single compliance check defined in a playbook, containing an id, description, check_description, scope, and optional check_type.
- **Scope**: A per-rule tag indicating whether the rule applies to claims, source spans, or both. Valid values: `claims`, `source`, `both`.
- **playbook_id**: A whitelisted identifier that maps to a known YAML file under `rules/`. Provided per-run and stored on the run record.
- **Finding**: A structured result produced when a rule is violated, containing the rule id, verdict, cited source span, and explanation.
- **Verdict**: The evaluation outcome for a rule against a span. One of: `pass`, `fail`, `not_applicable`, `insufficient_evidence`.
- **Evaluation Method**: The mechanism used to evaluate a rule. Either `llm` (default) or `structured` (opt-in via `check_type: structured`).
- **Source Span**: A contiguous text region within the source document identified by start and end offsets.
- **Playbook Schema**: A Pydantic model that validates the structure and content of playbook YAML files at load time.
- **Run Record**: The persistent record of a pipeline execution, stored in the `runs` table.

## Requirements

### Requirement 1: Playbook Loading and Validation

**User Story:** As a compliance analyst, I want rules defined in YAML files so that I can add or modify rules without changing Python code.

#### Acceptance Criteria

1. WHEN a pipeline run is initiated with a playbook_id, THE Pipeline SHALL resolve the playbook_id to a YAML file path under the `rules/` directory using a whitelist of known playbook names.
2. WHEN the playbook YAML file is loaded, THE Pipeline SHALL validate the file contents against the Playbook Schema using Pydantic.
3. IF the playbook_id does not match any entry in the whitelist, THEN THE Pipeline SHALL return a permanent error with a descriptive message indicating the unknown playbook_id.
4. IF the playbook YAML fails Pydantic schema validation, THEN THE Pipeline SHALL return a permanent error with validation details.
5. THE Playbook Schema SHALL require each Rule to contain the fields: id (string), description (string), check_description (string), and scope (one of `claims`, `source`, `both`).
6. THE Playbook Schema SHALL accept an optional field check_type on each Rule, defaulting to `llm` when absent.
7. WHEN a pipeline run completes playbook loading, THE Pipeline SHALL store the playbook_id on the Run Record.

### Requirement 2: Rule Scoping and Routing

**User Story:** As a compliance analyst, I want rules scoped to claims, sources, or both so that each rule runs against the appropriate data.

#### Acceptance Criteria

1. WHEN the Pipeline loads a validated playbook, THE Pipeline SHALL partition rules by scope: rules with scope `claims` route to the match_rules Node, rules with scope `source` route to the match_rules_against_sources Node, and rules with scope `both` route to both nodes.
2. THE Pipeline SHALL execute the match_rules Node and the match_rules_against_sources Node in parallel within the LangGraph graph.
3. WHEN both nodes complete, THE Pipeline SHALL merge findings from both nodes into a single findings list before passing control to the score_confidence node.

### Requirement 3: Source Span Evaluation

**User Story:** As a compliance analyst, I want rules evaluated directly against source document text so that violations in source materials are detected independently of claim extraction.

#### Acceptance Criteria

1. WHEN the match_rules_against_sources Node receives rules with scope `source` or `both`, THE match_rules_against_sources Node SHALL evaluate each rule against the source document spans available in the pipeline state.
2. THE match_rules_against_sources Node SHALL batch multiple rules per source span to reduce the number of LLM calls.
3. WHEN no source spans are available in the pipeline state, THE match_rules_against_sources Node SHALL complete with an empty findings list and status `completed`.
4. THE match_rules_against_sources Node SHALL tag each Finding with the evaluation_method used (`llm` or `structured`).

### Requirement 4: LLM-Based Rule Evaluation

**User Story:** As a compliance analyst, I want rules evaluated by an LLM by default so that complex regulatory language is interpreted correctly.

#### Acceptance Criteria

1. WHEN a rule has check_type `llm` or no explicit check_type, THE match_rules_against_sources Node SHALL evaluate the rule using the LLM.
2. THE LLM evaluation SHALL return a structured verdict containing: verdict (one of `pass`, `fail`, `not_applicable`, `insufficient_evidence`), cited_span (exact text location that triggered the evaluation), and explanation (reasoning for the verdict).
3. WHEN the LLM returns a verdict of `not_applicable`, THE match_rules_against_sources Node SHALL produce no Finding for that rule-span pair.
4. IF the LLM API call fails, THEN THE match_rules_against_sources Node SHALL set a transient error status to enable retry.

### Requirement 5: Structured Rule Evaluation

**User Story:** As a compliance analyst, I want deterministic structured checks for rules where LLM interpretation is unnecessary so that evaluation is faster and reproducible.

#### Acceptance Criteria

1. WHEN a rule has check_type `structured`, THE match_rules_against_sources Node SHALL evaluate the rule using deterministic structured logic instead of the LLM.
2. THE structured evaluation SHALL return the same verdict schema as the LLM evaluation: verdict, cited_span, and explanation.
3. WHEN a rule specifies check_type `structured` and the structured evaluator does not support that rule's check_description, THE match_rules_against_sources Node SHALL fall back to LLM evaluation and log a warning.

### Requirement 6: Finding Integrity

**User Story:** As a compliance analyst, I want findings to be honest and precisely cited so that I can trust the system output.

#### Acceptance Criteria

1. THE match_rules_against_sources Node SHALL produce findings only when a rule evaluation returns a verdict of `fail`.
2. WHEN no rules are violated for a given document, THE match_rules_against_sources Node SHALL return an empty findings list.
3. THE match_rules_against_sources Node SHALL never generate synthetic or padded findings.
4. WHEN a Finding is produced, THE Finding SHALL contain the exact source span (start offset, end offset, and text) that triggered the violation.
5. THE Finding SHALL contain the rule id, the verdict, the cited source span, the explanation, and the evaluation_method.

### Requirement 7: Extensibility Without Code Changes

**User Story:** As a compliance analyst, I want to add new rules by editing YAML only so that the development team is not a bottleneck for rule updates.

#### Acceptance Criteria

1. THE Pipeline SHALL evaluate any rule present in a valid playbook YAML without requiring changes to Python source files.
2. WHEN a new rule is added to an existing playbook YAML file, THE Pipeline SHALL evaluate the new rule on the next run that references that playbook_id.
3. THE Playbook Schema SHALL permit an unbounded number of rules per playbook file.

### Requirement 8: Testability

**User Story:** As a developer, I want deterministic test scenarios so that I can verify the rules checking stage works correctly.

#### Acceptance Criteria

1. WHEN the match_rules_against_sources Node is run against a clean test corpus (no violations), THE match_rules_against_sources Node SHALL return zero findings.
2. WHEN the match_rules_against_sources Node is run against a violation test corpus containing exactly one known violation, THE match_rules_against_sources Node SHALL return exactly one Finding with the correct rule id and a cited span that matches the violation location.

### Requirement 9: Error Handling

**User Story:** As a developer, I want clear error classification so that the pipeline can retry transient failures and stop on permanent ones.

#### Acceptance Criteria

1. IF the LLM API call fails during rule evaluation, THEN THE match_rules_against_sources Node SHALL set node_status to `error` and error_type to `transient`.
2. IF the playbook YAML is missing or fails schema validation, THEN THE Pipeline SHALL set node_status to `error` and error_type to `permanent`.
3. IF the playbook contains zero rules with scope `source` or `both`, THEN THE match_rules_against_sources Node SHALL complete with an empty findings list and status `completed`.
