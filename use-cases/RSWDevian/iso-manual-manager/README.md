# ISO 9001 Quality-Manual Manager

This use case maintains a manufacturing quality manual as a versioned document set. A scoped proposal
updates one process section and its linked Mermaid diagram together. Stable `step_id` values make prose and
diagram consistency mechanically testable. Human review is required before a new revision or export is
created.

This produces a **review-ready draft, not an ISO-certified manual**.

## Architecture

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the model, invariants, fixture, failure policy, and production
adapter boundary.

## Run

No live key, model, database server, or external renderer is required for the fixture path.

```bash
cd use-cases/RSWDevian/iso-manual-manager
python3 -m unittest discover -s tests -v
```

## Workflow

1. Create a `Manual` with sections and canonical Mermaid diagrams.
2. Submit a typed plan naming exactly one `section_id` and linked `diagram_id`.
3. The manager checks scope, Mermaid syntax, node edges, and prose/diagram `step_id` parity.
4. Reviewers approve or reject the paired proposal.
5. Approval creates revision `N+1`; rejection leaves the previous manual unchanged.
6. Export requires an approved proposal for the current revision and includes the professional-review disclaimer.

The fixture also emits valid local `html`, `docx`, and `pdf` bytes through
`export_bytes(manual, format)`. These are deterministic offline artifacts for testing. A hosted SuperDocs
export adapter can replace that renderer while keeping Mermaid source and the review gate unchanged.

## Machine Interfaces

Run the local REST/MCP wrapper with:

```bash
python3 -m iso_manual.api
```

REST routes include `POST /v1/builds/manual`, `GET /v1/manuals/{manual_id}`,
`POST /v1/manuals/{manual_id}/chat`, `GET /v1/proposals/{proposal_id}`,
`POST /v1/proposals/{proposal_id}/decision`, and
`POST /v1/manuals/{manual_id}/export`. The same lifecycle is available at `POST /mcp` with
`manual_start`, `manual_get`, `manual_chat`, `manual_review`, `manual_decide`, and `manual_export`.

## SuperDocs Surface

The workflow maps to SuperDocs chat editing, review approval, images/diagram rendering, and export. This
repository slice uses deterministic Mermaid parsing and SQLite so the safety contract is testable without a
live operation. The hosted adapter is intentionally separate: Mermaid source remains canonical and rendered
assets must never be edited independently.

## Limitations

The Mermaid parser covers the constrained fixture subset, not every Mermaid grammar feature. SQLite is the
local persistence implementation; production should use PostgreSQL. The implementation makes no ISO
certification, legal, or quality conclusion.
