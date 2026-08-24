# SuperDocs Section-Targeting Benchmark

A small, manual-review benchmark for evaluating whether SuperDocs uses the intended section of a document. It tests SuperDocs itself; it does not implement a replacement targeting algorithm or automatic judge.

Corpus version 1.1.0 contains 14 frozen DOCX documents and 60 benchmark cases. The documents are unchanged. D06-C02 and D08-C02 remain permanently removed.

## Final results

The tracked final adjudicated run (Benchmark run 4, corpus version 1.1.0) covers 14 frozen DOCX documents and 60 official cases:

- Section targeting: **56 PASS / 4 FAIL / 0 CANNOT DETERMINE — 93.3% accuracy**
- Search targeting: **42/43 PASS — 97.7% accuracy**
- Edit targeting: **14/17 PASS — 82.4% accuracy**
- Strict/end-to-end: **56 PASS / 4 FAIL — 93.3% accuracy**
- Average latency: **16,438.24 ms**
- Median latency: **15,389.39 ms**
- P95 latency: **25,314.93 ms**
- Sample latency standard deviation: **5,227.14 ms**
- API-reported operations charged: **38**
- Pre-declared operation cap: **60**; within budget: **Yes**
- Dollar spend: **not available** because it was not exposed by the stored API responses

Final metrics use the latest adjudicated execution attempt for each case in the run’s 60-case snapshot, so reruns are not counted as additional cases. Two earlier benchmark questions were excluded during corpus validation because their wording permitted unintended defensible interpretations.

The tracked final evidence is in [`outputs/final_run/results.csv`](outputs/final_run/results.csv) and [`outputs/final_run/summary.json`](outputs/final_run/summary.json).

### Final screenshot

The tracked screenshot is [`outputs/final_run/final-result-dashboard.png`](outputs/final_run/final-result-dashboard.png). It captures Benchmark run 4’s final 60-case dashboard and contains no API key or raw technical response. The CSV and JSON are the authoritative metric artifacts.

Secondary experiments remain separate from the official score. Applied-edit verification contains 15 reviewed approvals: 13 landed in the intended section, 2 could not be determined, and none showed unrelated changes. Guided recovery was attempted twice and recovered both cases.

Targeting accuracy measures whether SuperDocs identified the intended section. Strict accuracy additionally requires the returned answer or proposed edit to be correct and properly scoped. Public failure reporting uses four categories: **Wrong target**, **Should have clarified**, **Unsupported target**, and **Right target, wrong result**. Historical granular adjudication labels remain preserved internally.

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
2. Run one case, select several cases, or use **Select all shown** to select every case visible under the current filters. The configured limits still apply.
3. Wait for the saved result to open. Leaving or refreshing after completion does not lose the execution.
4. Review the written response and targeting evidence. For edit cases, proposed changes show the resolved heading path, operation, chunk ID, placement ID when applicable, and before/after content.
5. Reveal the expected result only when ready to compare.
6. Save **Pass**, **Fail**, or **Cannot determine**. A failure requires a failure reason.

For an edit that is awaiting approval, **View current document** shows the document before the pending proposal is applied. The benchmark does not approve edits automatically.

## Persistent benchmark runs

SQLite stores benchmark runs, every execution attempt, normalized and raw SuperDocs responses, latency, operation usage, and manual adjudications.

- Restarting or refreshing resumes the most recently selected benchmark run.
- The run selector can display earlier runs without making a SuperDocs call.
- Each run stores its corpus version and complete case-membership snapshot. Historical 40-case runs continue to display 40/40, while the final run uses the current 60-case snapshot.
- **Start fresh benchmark run** creates an empty scoring run against the current 60-case corpus. It does not delete prior runs or call SuperDocs.
- **Run again** creates a new attempt and requires fresh adjudication. Older attempts remain stored.
- Dashboard metrics are calculated from the latest attempt for each case in the selected run.

## Applied-edit verification

The original human adjudication is preserved as the strict/end-to-end verdict. The separate targeting verdict evaluates only whether the first proposal identified the intended section.

For a freshly run synthetic edit case that is waiting for approval, the case page can additionally:

1. Render the stored uploaded document with labelled expected-section and proposed-target markers.
2. Let a human explicitly choose **Approve test edit**. Nothing is approved automatically.
3. Resume polling the same SuperDocs job and re-fetch the session document after completion.
4. Compare the before/after HTML by `data-chunk-id` and record modified, created, deleted and unrelated chunks.
5. Save separate human judgments about proposal placement and applied placement.

Approval affects only the temporary synthetic SuperDocs session. It never rewrites the frozen local DOCX fixture. Applied evidence is stored separately and does not alter targeting or strict metrics. A second proposal batch requires another explicit approval; a large-edit continuation prompt is shown separately and is never treated as a change approval.

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

### Guided Recovery Experiment

The primary benchmark measures first-attempt section targeting. Guided recovery is an optional, secondary experiment asking whether a human can reject one incorrect edit proposal, provide one explicit correction, and obtain a correct second proposal.

For a pending edit, choose **Reject and guide**, enter the correction yourself, and submit it once. The app preserves the original proposal and benchmark verdict and rejects the original change IDs with your guidance in the API feedback field. SuperDocs revises the proposal in the same job; the app polls that job and stores the returned pending-change batch as the recovery proposal. It does not send a redundant second chat request. Recovery latency, operations, and the manual result—**Recovered**, **Did not recover**, or **Cannot determine**—are stored separately. Recovery data never changes targeting accuracy, strict accuracy, or the official run’s 38-operation total. Dollar spend remains unavailable because the API does not report it.

Recommended initial sample (run manually, at most three):

- **D05-C02:** semantic section mismatch between User Experience and Functional Requirements.
- **D01-C02:** repeated Risks heading selected under the wrong client parent.
- **D10-C02:** cross-reference confusion, providing a distinct failure mode from the first two.

## Batch limits and API usage

The defaults allow selecting all 60 cases in a new corpus-version 1.1.0 run:

```dotenv
BENCHMARK_MAX_BATCH_CASES=60
BENCHMARK_MAX_BATCH_OPERATIONS=60
```

Every selected case makes its own live SuperDocs execution. **Select all shown** only selects the visible filtered cases; it does not call SuperDocs. The batch runner stops before starting another case once the recorded operation cap has been reached. SuperDocs may enforce account quotas or return `429`; the app does not promise that all 60 calls will succeed in one batch.

Refreshing, switching benchmark runs, viewing saved results, viewing metrics, or starting a fresh run never starts a case execution.

## Validation and tests

No API key or live SuperDocs call is required:

```bash
pytest -q
python outputs/benchmark_corpus/validate_corpus.py
```

The corpus validator checks document hashes, real heading hierarchy, target content, distractors, ambiguity/no-target conditions, and the current 60-case manifest.

## Files and data safety

- `.env`, `.venv`, `benchmark.db`, exports, caches, and scratch work are gitignored.
- The 14 frozen DOCX files live in `outputs/benchmark_corpus/documents/` and must not be rewritten by the app.
- The manifest is `outputs/benchmark_corpus/benchmark_manifest.json`; the CSV is a readable companion export.
- Removing a benchmark case is a data migration because executions reference cases. Normal startup never resets runs or adjudications.
- API errors are saved with the execution and do not expose the API key.

Built for the SuperDocs task.
