# Task Traceability

Source-task note, unchanged from the prior session: the private "SuperDocs
Open Task List" this directive refers to as "supplied with the project"
was never actually provided — only the directive text itself, twice now.
The "SOURCE TASK" column below is therefore the directive's own capability
description, not an original SuperDocs task title. Tracked as Risk #1 in
RISK_REGISTER.md, not silently worked around.

## Implemented (3 of 30)

### PRISM DELTA

| Field | Value |
|---|---|
| Source | Directive capability `03 — PRISM DELTA` |
| Purpose | Material-change intelligence between two document versions |
| Original requirements | Structural/semantic/numeric/date/formatting diff, obligation analysis, impact analysis |
| PRISM enhancements | Materiality tiering (material/minor/cosmetic/review-required); honest fallback to review-required rather than guessing |
| Dependencies | `@prism/core` |
| Shared engines | DocumentModel, DocumentParser, DiffEngine |
| UI | None |
| Agents | None — fully deterministic |
| Tools | `readDocx`, `alignParagraphs`, `wordDiff` |
| Security | Reads local files only; no hardening against adversarial input (see RISK_REGISTER #7) |
| Error handling | Throws on missing/invalid files; never returns partial results silently |
| Tests | `packages/delta/test/*` — 10 tests |
| Benchmarks | None run |
| Acceptance evidence | `npm test` output; `fixtures/example-report.json` is real captured output |
| Status | **Implemented** |

### PRISM GATE

| Field | Value |
|---|---|
| Source | Directive capability `11 — PRISM GATE` |
| Purpose | Approval fidelity — stable change IDs, approve/reject/edit, exact application |
| Original requirements | Approve/reject/edit/partial approval/out-of-order/repeated decisions; final document must equal exactly the approved set |
| PRISM enhancements | Exactness independently re-verified by re-running PRISM DELTA on the applied output, not just asserted |
| Dependencies | `@prism/core`, `@prism/delta` |
| Shared engines | ApprovalEngine, EditEngine (via `writeDocx`) |
| UI | None |
| Agents | None — deterministic; a human (or future agent) supplies decisions, GATE only applies them |
| Tools | `writeDocx` |
| Security | Refuses to write back documents containing tables rather than silently corrupting them |
| Error handling | Throws with the specific pending change IDs; throws on unknown changeId or invalid decision |
| Tests | `packages/gate/test/*` — 5 tests, including a partial-approval test verified two independent ways |
| Benchmarks | None run |
| Acceptance evidence | `npm test` output |
| Status | **Implemented** |

### PRISM VAULT

| Field | Value |
|---|---|
| Source | Directive capability `10 — PRISM VAULT` |
| Purpose | Exact version/revert engine with immutable version identity |
| Original requirements | Undo/redo/revert/multi-revert/revert-of-revert; verify exact restoration; maintain version graph |
| PRISM enhancements | Restoration verification actually re-hashes stored content rather than trusting the stored fingerprint label (tested via a deliberate-tamper test) |
| Dependencies | `@prism/core` (`fingerprintParagraphs`) |
| Shared engines | VersionEngine |
| UI | None |
| Agents | None — deterministic |
| Tools | `fingerprintParagraphs` |
| Security | In-memory only; no persistence, so no storage-layer exposure yet |
| Error handling | Throws on undo/redo past timeline bounds and on reverting to an unknown version id |
| Tests | `packages/vault/test/*` — 5 tests |
| Benchmarks | None run |
| Acceptance evidence | `npm test` output |
| Status | **Implemented** |

### PRISM GRID

| Field | Value |
|---|---|
| Source | Directive capability `08 — PRISM GRID` |
| Purpose | Table structural fidelity — verbatim write-back plus structural comparison |
| Original requirements | Merged cells, nested tables, spanning headers, numeric formatting, row/column relationships; structural verification, not just screenshots |
| PRISM enhancements | Tables are never edited/regenerated — always passed through verbatim, anchored to original position, with a precise (not blanket) refusal only when paragraph count also changes |
| Dependencies | `@prism/core` (table reading + table-aware write path) |
| Shared engines | DocumentModel (table extraction), TableIntegrityEngine |
| UI | Verification Center's TABLES row now reports a real PASS/FAIL/NOT_APPLICABLE from `compareDocumentTables`, not a blanket status |
| Agents | None — deterministic structural comparison |
| Tools | `readDocx` (table extraction, gridSpan/vMerge), `writeDocx` (table-aware path), `compareTableStructure`/`compareDocumentTables` |
| Security | Same as core — no additional surface |
| Error handling | Precise refusal message naming the exact unsupported combination (tables + structural change), not a generic error |
| Tests | `packages/grid/test/*` (9 tests incl. real merged-cell fixtures) + `packages/core/test/write-docx.test.js` (4 table tests) + `@prism/ui` end-to-end table tests |
| Benchmarks | None run |
| Acceptance evidence | `npm test` output; a real bug (attribute-stripping in the order-recovery parser) was found via independent `pandoc` verification and fixed — see docs/DECISIONS.md |
| Status | **Implemented** (structural read/compare/preserve; table content editing itself is not yet built — see KNOWN_LIMITATIONS #2) |

## Not implemented (26 of 30)

Full reasons are in `packages/registry/src/task-registry.js` (queryable
data, not just prose) and summarized in docs/KNOWN_LIMITATIONS.md. Listed
here so nothing is implied-done by omission:

PRISM NEXUS, PRISM PROOF, PRISM TARGET, PRISM ADAPT, PRISM REVISION,
PRISM REFERENCE, PRISM VIS, PRISM AGENTDESK, PRISM MESH,
PRISM BRIDGE, PRISM SCALE, PRISM PROTOCOL, PRISM FLIGHT, PRISM RUNTIME,
PRISM INBOX, PRISM SIGN, PRISM TRUTHSET, PRISM JUDGE, PRISM REPLAY,
PRISM RESEARCH, PRISM PULSE, PRISM OFFICE, PRISM SIDE, PRISM MEMORY,
PRISM CONTINUUM, PRISM CONNECT.

Two of these (PRISM MESH, PRISM CONTINUUM) now have a real prerequisite
in place (`@prism/vault`'s version graph) that didn't exist before this
session, noted in docs/REPOSITORY_AUDIT.md's recommended evolution path —
that is the honest amount of progress toward them: a dependency exists,
the capability does not.

## UI coverage note

`@prism/ui` is cross-cutting infrastructure for the 3 implemented
capabilities above, not a 4th capability — it has no PRISM-XXX name in
the locked 30. It provides a real Task Center (left pane) listing all 30
registry entries with honest implemented/not-implemented status, but only
DELTA/GATE/VAULT have a working workflow behind their entry; clicking any
of the other 27 in the UI is disabled (`aria-disabled`), not wired to a
fake handler.
