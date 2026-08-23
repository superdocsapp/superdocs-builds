# SuperDocs Edit Precision Evaluator

This extension measures whether a document edit changed everything it should—and nothing it should not. It runs the same labelled corpus through two SuperDocs editing approaches, calculates intended-change coverage and collateral-damage rate, and publishes per-instruction-type evidence in a reviewable dashboard.

The checked-in dashboard uses clearly marked demonstration data. Benchmark conclusions must come from a live run after the labels receive independent second review.

The API integration has completed a capped live small-sample run. Its verified metrics and failure evidence are published in [results/SMALL_RUN.md](results/SMALL_RUN.md). This is integration evidence, not a substitute for the independently reviewed full-corpus benchmark.

## What it evaluates

The corpus contains 13 synthetic HR-policy cases across all required instruction types:

| Instruction type | Cases | Example |
| --- | ---: | --- |
| Single sentence | 3 | Change one leave entitlement without touching adjacent rules |
| One section | 4 | Replace one policy section while preserving its heading |
| Table row | 3 | Update one allowance record without changing other rows |
| Global rename | 3 | Replace every named term and leave other wording intact |

One case is deliberately ambiguous and carries three documented acceptable scopes. See [the labelling protocol](corpus/LABELING.md) for the independent-review and adjudication process.

## Metrics

For an acceptable label scope:

```text
intended-change coverage = successfully changed expected units / expected units
collateral-damage rate   = changed protected units / protected units
precision loss           = (1 - coverage) + collateral rate
```

A target unit counts as successful only when it changed and its required/forbidden after-state checks pass. Text, structure, and formatting changes to protected chunks count as collateral. Unexpected inserted chunks count as additional collateral units.

Legitimately ambiguous cases are scored against every pre-documented acceptable scope; the lowest-loss scope is reported. Labels never enter the edit prompt.

## Competing approaches

- **Direct instruction** sends the original instruction to SuperDocs.
- **Search-scoped** first asks SuperDocs to search the uploaded document for likely target chunk IDs, then supplies that label-free scope to the same edit instruction.

Both approaches use the same source document and labels. Search-scoped costs one additional search/analysis operation per case, which is included in the report.

## SuperDocs workflow

Every evaluated run completes the platform loop:

1. Upload the HTML document to `POST /v1/documents/upload`.
2. Align corpus labels to the returned chunk IDs before editing, without leaking labels into prompts.
3. Send the instruction through `POST /v1/chat/async` with `approval_mode=ask_every_time`.
4. Poll the job, capture proposed changes, and approve the benchmark batch through `POST /v1/chat/{session_id}/approve`.
5. Score the returned HTML against the uploaded pre-edit HTML.
6. Export the finished session through `POST /v1/documents/export`; exported HTML evidence is written beside the live report.

The API key exists only in the Python process. It is never returned by the API or sent to the React client.

## Repository layout

```text
backend/     Python evaluator, SuperDocs client, FastAPI service, tests
corpus/      Labelled JSONL cases, source HTML, review protocol
frontend/    React + TypeScript + Vite dashboard
results/     Marked demonstration report; live results are git-ignored
```

## Local setup

Requirements: Python 3.11+ and Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
cd frontend
npm ci
```

Validate the reusable corpus and run all backend checks:

```bash
.venv/bin/edit-precision validate-corpus
cd backend
../.venv/bin/ruff check src tests
../.venv/bin/pytest
```

Build the dashboard:

```bash
cd frontend
npm run typecheck
npm run build
```

Run the API and dashboard in two terminals:

```bash
cd backend
../.venv/bin/uvicorn edit_precision_evaluator.api:app --host 127.0.0.1 --port 8080
```

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`. API documentation is at `http://127.0.0.1:8080/docs`.

Alternatively, build the combined dashboard and API container:

```bash
docker compose up --build
```

Then open `http://127.0.0.1:8080`.

## Live evaluation and budget guard

Do not put the key in Git, the browser, a command argument, or a screenshot. Copy `.env.example` to `.env`, fill `SUPERDOCS_API_KEY` locally, and keep the file untracked.

The first run must be the small sample: one case per instruction type across both approaches. It estimates 12 operations, and the cap is declared before execution:

```bash
.venv/bin/edit-precision run-live --mode small --approach both --max-operations 12
```

The full 13-case, two-approach run estimates 39 operations. Run it only after inspecting the small sample and completing second review:

```bash
.venv/bin/edit-precision run-live --mode full --approach both --max-operations 39
```

The runner stops before a request that would exceed the declared cap. Very large edits may be billed as more than one operation; actual `ops_charged` values are reconciled and reported. This corpus uses small documents to keep that risk low.

Live outputs are written to `results/live/latest.json` and `results/live/exports/`. The dashboard automatically prefers the live report when present. Before publishing results, copy an audited report to a tracked path and state both the declared cap and actual operation usage.

## API endpoints

- `GET /api/health` — corpus integrity status
- `GET /api/corpus` — case counts, ambiguity, and second-review status
- `GET /api/cases` — public labelled corpus metadata
- `GET /api/report` — live report when available, otherwise explicit fixture data

## SuperDocs features used

- REST API and server-side API-key authentication
- document upload and chunk-ID parsing
- document search through chat analysis
- async chat editing and job polling
- human-in-the-loop proposed-change approval
- high-fidelity document export
- operation usage reporting

No secrets are committed. The extension is self-contained inside `extensions/Viekasai/edit-precision-evaluator/` as required by the parent repository.
