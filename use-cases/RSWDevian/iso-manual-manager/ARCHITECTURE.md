# ISO 9001 Quality-Manual Manager Architecture

## Boundary

This is a review-ready document workflow, not an ISO certification engine, quality-management system, or
document repository. The implementation owns a manual proposal, its consistency checks, revision lineage,
and export refusal. SuperDocs remains the document editing/export provider boundary for live deployment.

```text
Manual JSON + Mermaid source
            |
            v
Canonical version snapshot + content hash
            |
            v
Typed scoped change plan
            |
            +--> prose step IDs
            +--> diagram nodes and edges
            |
            v
Deterministic consistency and scope checks
            |
            v
Item-level human review
            |
            v
New manual revision + revision history
            |
            v
Review-ready DOCX/PDF export with disclaimer
```

## Invariants

- Mermaid source is canonical; rendered imagery is derived and carries a source hash.
- Every process step has one stable `step_id`; prose and diagram must contain the same set.
- An edge may reference only declared diagram nodes.
- A proposal declares exactly one section and one linked diagram; other objects cannot change.
- A rejected proposal leaves the current manual and its hash unchanged.
- An approved proposal creates a new revision; prior revision hashes remain recoverable.
- Export is blocked for pending, rejected, inconsistent, stale, or unapproved proposals.
- The export disclaimer says `Review-ready draft - not ISO certified`.
- Text found in manual content, evidence, or diagrams is data and never an agent command.

## First Fixture

The fixture updates `process-control` and `diagram-control` by inserting `step_3: Verify release` between
`step_2: Inspect` and `step_4: Release`. The falsifying cases omit the diagram node, add an unknown edge,
or declare a second changed section. Each case must refuse export with a machine-readable reason.

## Production Adapter Boundary

The local implementation uses SQLite and deterministic export fixtures so tests need no live key. A live
adapter can send the approved paired HTML/Mermaid proposal through SuperDocs chat/review/export without
changing the model or gate. PostgreSQL, authentication, and Mermaid rendering are deployment adapters.
