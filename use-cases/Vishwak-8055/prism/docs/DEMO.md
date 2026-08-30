# Demo

## Run it

```bash
npm install && npm run demo
```

## What it actually does

Real `.docx` fixtures (`packages/delta/fixtures/contract-v1.docx` /
`-v2.docx`) go through: PRISM DELTA (diff + classify) → a stated, visible
approval policy → PRISM GATE (apply approved subset to a real `.docx`) →
independent re-verification (re-running DELTA on the result) → PRISM
VAULT (commit a version) — all driven through the explicit workflow state
machine, printing every state transition as it happens.

## Honest mapping to the directive's flagship scenario

The directive's flagship demo asks for Contract A, Contract B, a
Proposal, and reference material, with Nexus/Proof/Delta/Target/
Revision/Reference/Grid/Gate/Vault/AgentDesk/Verification/Audit/Export all
demonstrated together, then Continuum/Memory/Bridge/Research/Pulse shown
running on the same infrastructure.

| Directive asks for | This demo does |
|---|---|
| Delta | Real — full pipeline |
| Gate | Real — full pipeline, including exactness re-verification |
| Vault | Real — one version committed per run |
| Verification | Real, narrowly — re-diff count must match prediction or the workflow refuses to reach VERIFIED |
| Export | Real — a genuine `.docx` file is written |
| Nexus, Proof, Target, Revision, Reference, Grid, AgentDesk | **Not demonstrated — not built.** No multi-document reasoning, no citation checking, no table/reference/tracked-changes handling, no agent identity model exists. |
| Continuum, Memory, Bridge, Research, Pulse ("same infrastructure supports...") | **Not demonstrated — not built.** `@prism/vault` is a real prerequisite for Continuum/Memory (durable state), but the agent loop and persistence layer on top of it don't exist. |
| Two contracts + a Proposal + reference material (4 documents) | Two documents (base/target contract). No Proposal or reference-material role modeled — Nexus (multi-doc reasoning) would be the capability that needs that, and it isn't built. |

This demo is real and worth running — it's just a fraction of the
directive's flagship scenario, mapped out explicitly above rather than
described in language that would blur the two together.

## Browser UI

```bash
npm install && npm run ui
```

Open http://localhost:8787. Click "Use bundled sample contracts", review
each of the 5 proposed changes (approve/reject/edit), click "Apply
approved changes", watch the Verification Center populate with real
PASS/NOT_APPLICABLE/UNVERIFIED status per area, then "Download result
(.docx)" for the actual applied file. The workflow-state badge in the top
bar reflects the real state machine (`@prism/registry#Workflow`) as it
transitions live.

## Table fidelity (PRISM GRID)

Upload or use a `.docx` containing a table alongside paragraph edits: the
table is never touched, and after Apply, the Verification Center's
TABLES row reports a real `PASS` — "N table(s) confirmed structurally
identical to source (PRISM GRID)" — derived from an actual structural
comparison (`compareDocumentTables`), not a static label. If the same
approval set also required adding/removing a paragraph, Apply is refused
with a precise reason instead of guessing where the table should go —
see docs/KNOWN_LIMITATIONS.md #2a.
