# LineCard architecture

```text
OEM manual
  -> immutable page/evidence extraction (PyMuPDF, SHA-256)
  -> local SQLite/FTS5 retrieval --------------------------+
  -> SuperDocs semantic retrieval channel -----------------+-> canonical evidence records
                                                          -> typed card/staging plan
                                                          -> SuperDocs HITL staging edits
                                                          -> direct chunk identity reconciliation
                                                          -> fail-closed decision gate
                                                          -> deterministic final composition
                                                          -> typed graph / evidence-backed SVG
                                                          -> two-page layout solver
                                                          -> independent verifier
                                                          -> SuperDocs exact-HTML export
                                                          -> PDF postflight
                                                          -> isolated batch orchestration
```

Local ingestion records the PDF hash, page map, text spans, dimensions, rotation, and rejection gates. Retrieval is task-specific and page-aware. SQLite FTS5 supplies deterministic lexical retrieval; the provider semantic channel is advisory until its result reconciles to a canonical evidence record.

The staging sidecar stores slot ID, document identity, synchronized provider chunk IDs, old HTML/text fingerprints, evidence IDs, critical/editable classification, and base version. A proposal must resolve by direct `chunk_id` and pass all secondary identity checks. The corrected live certification exposed a mismatch exactly here: 8 synchronized chunks had zero direct overlap with 6 recovered proposal targets, and a fresh run again had zero overlap with 31 proposal targets. LineCard blocks rather than fuzzy-mapping a safety-critical edit.

After explicit review decisions, LineCard composes a deterministic two-page card, renders a typed clear-jam flow as sanitized SVG, solves the page budget, verifies every critical value/step/safety/citation, and only then sends exact HTML for export. PyMuPDF postflight checks page count, warnings, clipping, required text, and diagram rendering.

SQLite stores jobs, revisions, events, idempotency records, outbox effects, and worker leases. Recovery is idempotent; leases fence a second worker and stale work cannot write. Batch tasks have separate sessions, evidence, decisions, manifests, and exports. Sample approval, operation budgets, blocked siblings, retry/resume, and safety stops are explicit in the manifest.

Manual text is untrusted data: scripts, URLs, unsafe markup, secrets, private headers, and provider identifiers are redacted or rejected. Upload type/size, encrypted/image-only PDFs, hostile content, HTTP error classes, and network failures fail closed. The React review surface exposes semantic controls and live status; Playwright exercises the served runtime.

Mermaid capability is documented, but neither the supplied reference nor live OpenAPI specifies the concrete HTML/data-* representation needed for deterministic provider construction. M4-02 therefore relies on live image upload/export proof plus the local deterministic graph/SVG path; no undocumented provider attributes are invented.
