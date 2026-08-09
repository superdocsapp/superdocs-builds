# Structured Invoice Companion

This extension creates a machine-readable invoice extract and a human-readable invoice representation
from one immutable canonical invoice record. It deterministically reconciles scalar fields, line-item values,
currency, dates, and narrative figures against that source. A mismatch is a hard failure, remains visible in
review, and blocks verified export.

The included fake transport models the four integration calls: upload, chat, approve, and export. It records
operation keys and safely replays a committed result after an unknown remote outcome instead of issuing a
duplicate operation.

The local service persists runs, review decisions, operation results, and export certificates in SQLite. It
exposes the same lifecycle through a standard-library REST server and a JSON-RPC MCP-compatible handler.

## Run

No live account, API key, model, database, or external renderer is required.

```bash
cd extensions/RSWDevian/invoice-companion
python3 -m unittest discover -s tests -v
```

Start the local REST surface with:

```bash
python3 -m invoice_companion.server
```

REST routes are `POST /v1/builds/invoice`, `POST /v1/runs/{run_id}/chat`,
`GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/review`,
`POST /v1/runs/{run_id}/review/{item_id}`, `POST /v1/runs/{run_id}/export`,
and `POST /v1/runs/{run_id}/live-export`.
The machine interface is available at `POST /mcp` using JSON-RPC method names
`invoice_start`, `invoice_get`, `invoice_review`, `invoice_decide`, and `invoice_export`.

## Review Frontend

The React review UI lives in `frontend/` and implements the four review panels: source facts,
human-readable invoice preview, verification findings, and decision/audit history. It uses React from a CDN
to keep the fixture project dependency-free.

Run it in a second terminal while the API server is running:

```bash
cd extensions/RSWDevian/invoice-companion
python3 -m http.server 5173 -d frontend
```

Open `http://localhost:5173`. Use **Start fixture**, then **Demo failure** to see the export gate disable
DOCX/PDF export after the visible total is changed.

The deliberate fixture changes the visible total from `550.00` to `650.00`. The reconciliation result names
`fields.total`, expected `550.00`, observed `650.00`, source pointer `payload.total`, and severity
`hard_failure`. Approving the finding or accepting it as an exception does not enable verified export.

## SuperDocs Features

- API-shaped lifecycle: upload, chat, approve, export
- Review gate with item-level decisions
- Deterministic export gate
- Content-addressed source snapshot
- Native SuperDocs export via the documented REST API
- Generic live MCP `tools/call` client via Streamable HTTP

## Scope And Limits

The default tests are local and fixture-safe. Local exports now produce valid HTML, Open XML DOCX, and PDF
artifacts without third-party packages. For native hosted fidelity, set `SUPERDOCS_API_KEY` and call
`POST /v1/runs/{run_id}/live-export`; this uses `POST /v1/chat` to load the invoice and
`POST /v1/documents/export` for the requested `docx` or `pdf`. Live timeouts fail closed with an unknown-outcome
error and must be reconciled using the same session and operation key before retrying. The live call is not run
in CI and no credentials are committed.

SQLite is the local durable store; PostgreSQL, authentication, and a deployment-grade worker remain production
adapters rather than hidden claims about this repository.

Built for the SuperDocs Task 2 assigned extension build.
