# Invoice Anomaly Investigator

Invoice Anomaly Investigator is an offline-capable Task 2 Type 3 extension for accounts-payable review. It
turns invoice documents into immutable, content-addressed snapshots, runs deterministic anomaly checks, and
holds an evidence-backed investigation report behind an explicit human review gate.

It detects:

- duplicate invoice IDs within a submitted batch;
- declared totals that differ from the sum of source line-item totals;
- vendor payment-detail changes against a supplied baseline registry.

The parser treats document text as untrusted data. An instruction inside an invoice is never executed. Every
finding includes the source document, pointer, and excerpt used to support it. A clean batch also creates a
`no_anomalies` review item so a reviewer explicitly signs off on the absence of findings.

## Run The Tests

No live account, API key, model, database, or external service is required:

```bash
cd extensions/RSWDevian/invoice-anomaly-investigator
python3 -m unittest discover -s tests -v
```

## Run The Local Machine Surface

```bash
python3 -m invoice_anomaly.server
```

The REST surface is:

- `POST /v1/investigations` to ingest one or more text or JSON invoices;
- `GET /v1/investigations/{run_id}` to inspect durable state;
- `GET /v1/investigations/{run_id}/review` to list review items;
- `POST /v1/investigations/{run_id}/review/{item_id}` to approve, reject, or mark an item `needs_review`;
- `POST /v1/investigations/{run_id}/export` to export the approved report as HTML or JSON;
- `POST /mcp` for the equivalent JSON-RPC methods.

Use `X-Tenant-ID` to scope runs. SQLite is the fixture persistence boundary and can be replaced by a production
store without changing the anomaly or review logic.

## Fixture Input

Text fixtures use one field per line and pipe-delimited items:

```text
Invoice ID: INV-100
Vendor: Acme Parts
Invoice date: 2026-08-01
Due date: 2026-08-31
Currency: USD
Payment details: Bank account 001122
ITEM|row-1|Widget|2|10.00|20.00
Total due: 20.00
```

A batch payload can include a baseline:

```json
{
  "idempotency_key": "batch-001",
  "documents": [{"name": "invoice.txt", "text": "..."}],
  "vendor_registry": {"Acme Parts": "Bank account 001122"}
}
```

## Review And Export Contract

The four integration operations are represented by the local transport: upload, chat, approve, and export.
Runs, findings, decisions, operation keys, and export certificates are persisted. Export is blocked while any
item is pending or `needs_review`; final `approved` or `rejected` decisions are both retained in the report.
Retries after an uncertain transport result must reuse the same operation key, which replays the committed
result instead of creating a duplicate side effect.

This is a first-pass investigation aid, not a fraud determination, bank verification service, OCR benchmark, or
production permissions system. The output requires human review.

Built for the SuperDocs Task 2 Type 3 build.
