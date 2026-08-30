# PRISM

Four of the thirty capabilities in the PRISM-for-SuperDocs master
directive, built for real and composed together: **PRISM DELTA**
(material-change intelligence), **PRISM GATE** (approval fidelity,
including real `.docx` write-back), **PRISM VAULT** (version/revert
engine), and **PRISM GRID** (table structural fidelity) — driven through
an explicit Task Registry and Workflow Engine, and exposed through a
real, tested browser UI (**`@prism/ui`**), not glued together ad hoc.

**71/71 tests passing, 0 type errors, 0 lint issues.**
`npm install && npm run check` runs the full quality gate (typecheck →
lint → test) — real, run for the first time this session (see
docs/DECISIONS.md: the first typecheck run surfaced 20 genuine errors,
all fixed at the root cause, not suppressed). `npm test` alone for a
faster loop. `npm run demo` for the composed CLI run, `npm run ui` for
the browser workspace (http://localhost:8787).

## Start here

- [`docs/FINAL_QA_REPORT.md`](docs/FINAL_QA_REPORT.md) — what's actually
  verified, with numbers.
- [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) — what isn't,
  and why, in the directive's own required WHAT/WHY/IMPACT format.
- [`docs/PRISM_ARCHITECTURE.md`](docs/PRISM_ARCHITECTURE.md) — how the
  four packages fit together and why this particular slice was chosen.
- [`docs/DEMO.md`](docs/DEMO.md) — an explicit, honest mapping of the
  directive's flagship scenario onto what this demo actually does (a
  fraction of it, itemized rather than blurred).

## Structure

```
packages/
  core/      @prism/core     — DocumentModel: read/write real OOXML (paragraphs + tables), fingerprinting, paragraph alignment
  delta/     @prism/delta    — PRISM DELTA: material-change classification
  vault/     @prism/vault    — PRISM VAULT: immutable versions, undo/redo/revert
  gate/      @prism/gate     — PRISM GATE: approval decisions, exact application
  grid/      @prism/grid     — PRISM GRID: table structural comparison (verbatim preservation, never edited)
  ui/        @prism/ui       — real server + browser workspace, Verification Center backed by real checks
  registry/  @prism/registry — Task Registry (all 30, honestly) + Workflow Engine + the composed run
cli.js       — root demo
docs/        — the 16 documents the directive requires, written against what's actually here
```

## Two-session context

This repository is the product of two consecutive directives in one
conversation. The first built PRISM DELTA alone, against a public
open-source document editor (`superdoc/docx-editor`) found and cloned
because neither directive's referenced "SuperDocs starter repo" or "Open
Task List" was ever actually provided — that gap is still open (see
docs/RISK_REGISTER.md #1) and is stated here rather than allowed to fade
between sessions. This session extended that codebase into shared
infrastructure and two new composed capabilities rather than starting
over, per the second directive's own "no giant rewrite" instruction.

## What this is not

Not a 30-capability platform. Not a UI covering all 30. Not connected to
any live external service. 26 of 30 named capabilities and 20 of 28 named
shared-core services are explicitly `not_implemented` in
`packages/registry/src/task-registry.js` — queryable data, not marketing
copy. See docs/TASK_TRACEABILITY.md for the complete, itemized account.

## Credits

Built and engineered by **Vishwak**.

