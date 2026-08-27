# Threat model

## Assets

Private source documents, source hashes, report content, reviewer decisions, workspace membership, database credentials, object-storage credentials, and model-provider credentials.

## Threats and controls

| Threat | Control |
| --- | --- |
| Prompt injection in a source | Source text is untrusted evidence; instruction-like patterns become security findings and are never executed. |
| Cross-workspace data access | Workspace/run foreign keys, scoped queries, authorization at the API boundary, and isolation tests. |
| Duplicate or implicit approval | Stable finding IDs, duplicate/unknown validation, complete decision-set checks, and append-only decision provenance. |
| Crash during analysis | Durable stage checkpoints, leases, resumable status, and deterministic interruption tests. |
| Secret leakage | No credentials in fixtures, logs, prompts, report citations, or `.env.example`; secret scans in CI. |
| Malicious file | Size limits, supported-format allowlist, ZIP parsing only for DOCX text extraction, and no execution of embedded content. |
| Tampered evidence | SHA-256 source hashes, immutable versions, citation locators, and provenance events. |
| Concurrent mutation | Per-run locking, state versions, unique constraints, and concurrent-run tests. |

## Residual risks

The SQLite offline lock is process-local. Production must use PostgreSQL advisory locks or a distributed lease. Deterministic embeddings are a test substitute; production semantic retrieval requires a reviewed embedding provider and data-processing agreement. Authentication and tenant authorization require integration with the deployment’s identity provider before production use.
