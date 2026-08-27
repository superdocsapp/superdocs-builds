# Release Readiness Analyst — project explanation

## Problem

Release managers and engineering leads often have requirements, design decisions, test evidence, meeting notes, and checklists in separate documents. A useful readiness brief must identify what is supported, what conflicts, and what is still missing, while letting a human decide consequential findings.

## What is built

The Release Readiness Analyst is a separate FastAPI/React project with a durable staged workflow. It ingests document fixtures, records source SHA-256 and line-level provenance, extracts evidence, detects contradictions and missing coverage, applies policy rules, and creates a cited report. The offline implementation persists checkpoints in SQLite and includes the documented PostgreSQL/pgvector migration path. A typed MCP-compatible HTTP boundary exposes machine operations without weakening the decision gate.

The SuperDocs `sdx` project is shown as a complementary pipe-friendly document tool. Its verified offline workflow accepts stdin, presents section-level edits, emits schema-version-1.0 JSON, requires explicit item-level approval, and verifies PDF/DOCX exports. The two projects are demonstrated together but do not share a runtime or claim a shared API.

## Human control and safety

Each proposed finding has an explicit approve, reject, or request-more-evidence decision. An incomplete decision set cannot complete. Embedded instructions in source documents are treated as untrusted evidence, not as policy or tool commands. Run identifiers, checkpoints, leases, source hashes, and report revisions isolate concurrent work and support interruption/resume in deterministic offline tests.

## Evidence and outcome

The offline Task 1 demo completed with six stages and three cited findings. Its synthetic policy verdict was `blocked`, intentionally demonstrating that critical evidence is not silently waived. Prior `sdx` verification recorded 132 passing tests, one skip, and no failures; the current audit performed zero live operations. Historical potentially billable usage remains exactly two operations. These are offline or historical facts, not a promise of production performance.

## Limits

The assigned PDF was unavailable during package preparation, so exact submission clauses and question wording remain to be reconciled. No live cassette was recorded; renderer-based 120-page visual counting was unavailable. PostgreSQL/pgvector, production identity, native MCP transport, and browser-level accessibility checks remain deployment or follow-up work. This package is a draft and has not been uploaded, published, or submitted.
