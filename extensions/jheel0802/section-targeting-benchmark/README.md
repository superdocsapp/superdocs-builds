# SuperDocs Section-Targeting Benchmark

A small, manual-review benchmark for evaluating whether SuperDocs uses the intended section of a document. It tests SuperDocs itself; it does not implement a replacement targeting algorithm or automatic judge.

The official corpus contains 14 frozen DOCX documents and 40 benchmark cases. D06-C02 and D08-C02 were permanently removed. Custom experiments remain separate from official scores.

## Final results

The final adjudicated run covers 14 frozen DOCX documents and 40 official cases:

- Overall: **25 PASS / 15 FAIL — 62.5% pass rate**
- Search/question: **20 PASS / 8 FAIL — 71.4% pass rate** across 28 cases
- Edit: **5 PASS / 7 FAIL — 41.7% pass rate** across 12 cases
- Average latency: **20,840.72 ms**
- Median latency: **17,448.55 ms**
- P95 latency: **39,176.99 ms**
- Sample latency standard deviation: **9,437.36 ms**
- API-reported operations charged: **28**
- Dollar spend: **not available** because it was not exposed by the stored API responses

Final metrics use the latest adjudicated execution attempt for each official case, so reruns are not counted as additional cases. Custom experiments and rows without an external case ID are excluded. Two benchmark questions were excluded during validation because their wording permitted unintended defensible interpretations; the final official corpus therefore contains 40 cases.

The tracked final evidence is in [`outputs/final_run/results.csv`](outputs/final_run/results.csv) and [`outputs/final_run/summary.json`](outputs/final_run/summary.json).

### Final screenshot

The final screenshot has not been captured yet. Save it as `outputs/final_run/final-results-dashboard.png`. It should show the **Results** tab for **Benchmark run 2**, including the selected-run control and the visible overall totals of 40 official cases, 25 passes, 15 failures, and a 62.5% pass rate. Do not include the API key, `.env`, raw technical responses, or other secrets in the screenshot.

## Start the app

Python 3.11 or newer is recommended. Docker is not required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your SuperDocs API key in `.env`:

```dotenv
SUPERDOCS_API_KEY=your_real_key_here
```

Load the frozen corpus once if the database is new:

```bash
python -m app.import_corpus
```

Start the site:

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. To exercise the app without live SuperDocs calls, set `SUPERDOCS_CLIENT=fake` in `.env` before starting it.

## How to evaluate the benchmark

1. Open **Cases**. Cases awaiting review appear first, cases not yet run next, and reviewed cases last.
2. Run one case, select several cases, or use **Select all** to select every case currently present. The configured limits still apply.
3. Wait for the saved result to open. Leaving or refreshing after completion does not lose the execution.
4. Review the written response and targeting evidence. For edit cases, proposed changes show the resolved heading path, operation, chunk ID, placement ID when applicable, and before/after content.
5. Reveal the expected result only when ready to compare.
6. Save **Pass**, **Fail**, or **Cannot determine**. A failure requires a failure reason.

For an edit that is awaiting approval, **View current document** shows the document before the pending proposal is applied. The benchmark does not approve edits automatically.

## Persistent benchmark runs

SQLite stores benchmark runs, every execution attempt, normalized and raw SuperDocs responses, latency, operation usage, and manual adjudications.

- Restarting or refreshing resumes the most recently selected benchmark run.
- The run selector can display earlier runs without making a SuperDocs call.
- **Start fresh benchmark run** creates an empty scoring run against the same 40 cases. It does not delete prior runs or call SuperDocs.
- **Run again** creates a new attempt and requires fresh adjudication. Older attempts remain stored.
- Dashboard metrics are calculated from the latest attempt for each case in the selected run.
- Custom experiments do not affect official metrics.

## Architecture

- FastAPI serves the REST backend and dependency-free browser UI.
- SQLite is the local persistent store (`benchmark.db` by default).
- `RealSuperDocsClient` contains the SuperDocs HTTP integration.
- `FakeSuperDocsClient` supports deterministic tests without an API key.
- The manifest importer verifies all 14 DOCX SHA-256 hashes before storing them. Integrity is checked again before every official case execution.
- The original DOCX fixtures are reused. Each live execution uploads a fresh copy to a new SuperDocs session, so pending edits do not mutate the frozen local fixture.

## SuperDocs REST flow used

Search/question and edit cases use the same documented chat surface but are interpreted according to their different returned evidence.

1. Create a unique benchmark-owned session ID.
2. `POST /v1/documents/upload-base64` with `filename`, `file_base64`, `session_id`, and `return_html: true`.
3. Retain the parsed HTML and map returned `data-chunk-id` values to the frozen DOCX heading hierarchy.
4. `POST /v1/chat/async` with the instruction, the same session, `response_mode: compact`, `approval_mode: ask_every_time`, and cross-session memory/search disabled.
5. Poll `GET /v1/jobs/{job_id}` until `awaiting_approval`, `completed`, `failed`, `cancelled`, or the local timeout.
6. Persist the textual response, `metadata.pending_changes`, resolved section paths, returned metadata, complete upload/queue/job responses, latency, and reported operation usage.

For `create` changes, placement is resolved through `insert_after_chunk_id`. If a chunk cannot be mapped deterministically, the UI shows **Section path unavailable** rather than guessing.

`metadata.pending_changes` is the primary edit-targeting evidence while using `ask_every_time`. The benchmark does not automatically approve a proposal just to score it. The preview endpoint exports the current session document as HTML; while the job is awaiting approval, that is still the unchanged document.

## Batch limits and API usage

The defaults allow selecting all 40 present official cases:

```dotenv
BENCHMARK_MAX_BATCH_CASES=40
BENCHMARK_MAX_BATCH_OPERATIONS=40
```

Every selected case makes its own live SuperDocs execution. **Select all** only selects cases; it does not call SuperDocs. The batch runner stops before starting another case once the recorded operation cap has been reached. SuperDocs may enforce account quotas or return `429`; the app does not promise that all 40 calls will succeed in one batch.

Refreshing, switching benchmark runs, viewing saved results, viewing metrics, or starting a fresh run never starts a case execution.

## Add a custom experiment

Open **Create test**:

1. Name the test and choose an existing document, or upload a new one.
2. Choose question/search or edit.
3. Enter the instruction.
4. Describe the correct behavior and expected section, answer, edit scope, acceptable alternatives, or clarification behavior as applicable.
5. Optionally list sections the response must not use.
6. Save the test, then run and review it from **Custom experiments**.

Custom experiments are persisted but excluded from the frozen benchmark metrics.

## Validation and tests

No API key or live SuperDocs call is required:

```bash
pytest -q
python outputs/benchmark_corpus/validate_corpus.py
```

The corpus validator checks document hashes, real heading hierarchy, target content, distractors, ambiguity/no-target conditions, and the current 40-case manifest.

## Files and data safety

- `.env`, `.venv`, `benchmark.db`, exports, caches, and scratch work are gitignored.
- The 14 frozen DOCX files live in `outputs/benchmark_corpus/documents/` and must not be rewritten by the app.
- The manifest is `outputs/benchmark_corpus/benchmark_manifest.json`; the CSV is a readable companion export.
- Removing a benchmark case is a data migration because executions reference cases. Normal startup never resets runs or adjudications.
- API errors are saved with the execution and do not expose the API key.

Built for the SuperDocs task.
