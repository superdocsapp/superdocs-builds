# Draft answers to the four required submission questions

> **PDF wording pending:** The authoritative task PDF was not present at its supplied path during this review. The headings below are a neutral four-question draft, not a claim about the literal PDF text. Replace each heading with the exact PDF question before submission.

## 1. What problem does this solve, and for whom?

Release managers, engineering leads, and reviewers must decide whether a release is supported by requirements, design notes, tests, and checklists that live in different documents. The Release Readiness Analyst turns those sources into a cited readiness brief, calls out contradictions and missing evidence, and keeps a human in control of consequential decisions. The companion `sdx` CLI makes document preparation and reviewed editing pipe-friendly for scripts and humans. The value is a traceable decision workflow rather than an unsupported “ready” label.

## 2. What did you build, and how does the workflow work?

The Task 1 project is a separate FastAPI/React application with a durable staged workflow: ingest sources, preserve provenance, analyze evidence, apply release rules, request item-level decisions, and incrementally update the report. Offline persistence uses SQLite with a PostgreSQL/pgvector migration path; typed MCP-compatible operations are available at the service boundary. Checkpoints, leases, and run identifiers support deterministic interruption/resume and concurrent-run isolation. The `sdx` project is shown as a separate verified CLI: it accepts stdin, presents section-level diffs, emits schema-compliant JSON, requires explicit approval, and verifies PDF/DOCX exports.

## 3. How is the result grounded, safe, and human-controlled?

Findings carry source name, SHA-256, line range, and a quote. Contradictions and missing evidence are visible branches, not hidden model assumptions. Source text is untrusted: an instruction embedded in a document cannot override policy, system instructions, authorization, or tools. Every proposal receives exactly one approve, reject, or request-more-evidence decision; an incomplete or conflicting set remains pending. Incremental updates retain unaffected finding identities and citations. The offline demo completed six stages and produced three cited findings, with a synthetic `blocked` verdict because critical evidence was intentionally unresolved.

## 4. What evidence, limitations, and next steps should the reviewer know?

The prior credential-free `sdx` audit reported 132 passing tests, one skip, and no failures across the full suite; Task 1 backend tests reported 9 passed, the frontend test reported 1 passed, the frontend build passed, and the offline demo completed. Historical potentially billable usage is exactly two operations; this package performs zero live operations. The assigned PDF was unavailable, so clause-level compliance and exact question wording still need confirmation. No live cassette or renderer-measured 120-page count exists. PostgreSQL/pgvector production validation, native MCP transport, production identity, browser accessibility E2E, and publication/hosting remain follow-up work. Next steps are to reconcile the PDF, record the approved synthetic demo, and obtain reviewer approval before any upload or submission.
