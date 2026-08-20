# Operator quick-reference cards from OEM manuals — LineCard

## Problem
Operators need a concise card, but OEM manuals remain the authority. A wrong torque value, omitted safety step, or bad citation is unacceptable.

## What I built
LineCard ingests synthetic OEM PDFs, retrieves task evidence, stages reviewed content, composes a deterministic two-page card, verifies it independently, and postflights export. It includes batch isolation, recovery/idempotency, budget gates, accessibility, and security boundaries.

## How it works
Immutable page evidence and SQLite/FTS5 retrieval feed a typed plan. SuperDocs is the semantic/HITL boundary. Direct synchronized chunk identity is required before a proposal can affect the card. Composition, SVG flow, layout, verifier, exact-HTML export, and PDF postflight are release gates.

## Safety / trust guarantees
Exact values, safety wording, required steps, restart checks, page citations, supported numbers, and two-page structure are checked. Unknown targets, wrong documents, stale bases, hostile content, and impossible budgets fail closed.

## SuperDocs integration
M0 contract behavior and M4 image upload/export are live-verified. During corrected live HITL certification, SuperDocs proposal targets had zero direct overlap with synchronized `document_sync` chunk IDs (8/6 in recovery and 8/31 in a fresh run). LineCard fails closed rather than heuristically applying an edit to a safety-critical section. The sanitized reproduction is included.

## Demo, testing, metrics, and batch
See `docs/demo-script.md`. Run `make check`, `make demo`, and `scripts/metrics_full.py`. The public metrics snapshot is `examples/metrics-report.md`; the committed three-card manifest is `examples/linecard-batch-manifest.json`.

## Reviewer quickstart and artifacts
Create `.venv`, install `.[test]`, and run `docs/evaluation.md`. Representative HTML/JSON is in `examples/`; architecture/evaluation are in `docs/`; 400-page and second-manual fixtures are in `fixtures/generated/`.
