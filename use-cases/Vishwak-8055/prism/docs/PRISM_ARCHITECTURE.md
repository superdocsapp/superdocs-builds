# PRISM Architecture

## What actually exists

```
                       @prism/ui
        (real HTTP server + browser workspace,
         backed directly by the packages below —
         no mocked responses)
                           |
                    @prism/registry
                (Task Registry + Workflow Engine)
                           |
    +-----------+----------+----------+-----------+
    |           |          |          |           |
@prism/delta @prism/gate @prism/vault @prism/grid
(material-   (approval   (version/    (table
 change        fidelity)   revert)     structural
 intelligence)                         fidelity)
    |           |          |          |
    +-----------+----------+----------+-----------+
                           |
                      @prism/core
        (DocumentModel: read-docx, write-docx,
         snapshot/fingerprint, paragraph alignment)
```

Every arrow above is a real `package.json` dependency (npm workspaces),
not an aspirational diagram — `packages/gate/package.json` really does
depend on `@prism/core` and `@prism/delta`; `packages/registry` really
does depend on all three capability packages.

## Shared core services — status against the directive's full list

The directive names 28 shared-core services. Built for real: 8. The rest
are not silently claimed — see the table below and
docs/TASK_TRACEABILITY.md for the full capability-level mapping.

| Directive's service | Built as | Status |
|---|---|---|
| DocumentModel | `@prism/core` paragraph + table model | Real (paragraphs and tables; no headers/footers/notes/tracked-changes yet) |
| DocumentParser | `@prism/core#readDocx` | Real |
| DiffEngine | `@prism/core#alignParagraphs` + `@prism/delta`'s classifiers | Real |
| VersionEngine | `@prism/vault` | Real |
| ApprovalEngine | `@prism/gate` | Real |
| EditEngine | `@prism/core#writeDocx` | Real, paragraph-level content; tables pass through verbatim, not edited |
| TableIntegrityEngine | `@prism/grid` | Real — structural comparison (merges, cell text, shape); visual/layout properties not compared |
| WorkflowEngine | `@prism/registry#Workflow` | Real, explicit state machine |
| StructureAnalyzer, SemanticAnalyzer, RetrievalEngine, EvidenceEngine, ClaimEngine, ChangePlanner, RevisionEngine, ReferenceEngine, VisualIntegrityEngine, ReviewEngine, PolicyEngine, AgentRuntime, IntegrationRuntime, AuditEngine, TelemetryEngine, EvaluationEngine, BenchmarkEngine, CostEngine, SessionEngine | — | Not built. See docs/KNOWN_LIMITATIONS.md for why each bucket (model-tier / external-integration / infrastructure) is out of reach this session. |

## The UI layer (`@prism/ui`)

A plain `node:http` server (no framework — see docs/DECISIONS.md) serving
a static HTML/CSS/JS frontend plus a small real JSON API. Every route
calls directly into `@prism/delta`, `@prism/gate`, `@prism/vault`,
`@prism/grid`, or `@prism/registry` — there is no mock data layer. The frontend's render
logic (`public/render.js`) is deliberately pure (data in, HTML string out,
no DOM/fetch access) so the exact same functions the browser uses are
importable into Node tests and checked with real `axe-core` — see
docs/TESTING.md and docs/KNOWN_LIMITATIONS.md #1 for what that does and
doesn't prove.

Layout matches the directive's exact 4-pane spec (Tasks/Documents left,
Document/Diff/Workflow center, Evidence/Verification right, Timeline
bottom) with one shared in-memory workspace per server process — a real,
documented, single-operator-tool constraint, not multi-tenant
infrastructure (docs/KNOWN_LIMITATIONS.md #7).

## Why this composition, specifically

Delta → Gate → Vault was chosen (over, say, starting with Nexus or Proof)
because it's the one chain in the whole directive that is **entirely
deterministic** — no retrieval, no semantic reasoning, no external
service — and therefore the one place where "real, measured, verified"
was fully achievable without a model in the loop or a live integration.
Every other capability in the locked 30 needs at least one of those three
things this sandbox doesn't have. That's not a preference for easy work;
it's the actual honest boundary of what's buildable here, stated as
architecture rather than discovered as an excuse partway through.

## The Workflow Engine specifically

`packages/registry/src/workflow-engine.js` implements the directive's
exact state list (`CREATED` ... `EXPORTED`) plus its six failure states,
as a real transition graph (the `TRANSITIONS` object) — not an enum used
loosely. Two properties are enforced by the graph itself, not by
convention:

1. **`UNVERIFIED` cannot reach `EXPORTED`** by any path. Tested directly
   (`registry.test.js`, "UNVERIFIED is a structural dead end").
2. **Every transition is checked.** Calling `.transition('EXPORTED')` from
   `CREATED` throws immediately rather than silently succeeding.

`packages/registry/src/compose.js` drives a real run of Delta → Gate →
Vault through this graph, and — the part that makes VERIFYING meaningful
rather than a label — re-runs PRISM DELTA against the applied output and
compares the remaining change count to what the approval decisions
predicted before allowing the `VERIFIED` transition at all.

## Data flow for one composed run

1. `compareFiles(base, target)` → DELTA report, carrying the raw alignment
   `ops[]` (every paragraph pairing, not just the "interesting" ones) plus
   `changes[]` tagged with `opIndex` back-references.
2. `createApprovalSet(report)` → one stable `changeId` per change, all
   `pending`.
3. `decide(...)` per change → `approved` / `rejected` / `edited`.
4. `applyApprovedChanges(report, approvalSet, outPath)` → walks `ops[]` in
   full document order (not just `changes[]`), picks base/target/edited
   paragraph content per decision, calls `writeDocx` once.
5. `compareFiles(outPath, base)` → independent re-verification; its
   `totalChanges` must equal `approved + edited` from step 3 or the
   workflow transitions to `UNVERIFIED` and refuses to proceed.
6. `vault.commit(...)` → immutable version of the applied result.
