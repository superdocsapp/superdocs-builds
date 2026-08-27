# SuperDocs Document Editing Benchmark

## Project Aim

This project builds a benchmarking harness to evaluate the token usage and cost implications of different document-editing strategies.

The main comparison is between:

1. **Whole-document editing** — the complete document is provided for every edit.
2. **Section editing** — only the relevant section is provided for an edit.

The goal is to understand how document size, edit type, and multi-turn editing sessions affect:

- Input tokens
- Output tokens
- Total token usage
- Cost
- Latency
- Request size

The benchmark is designed to be reproducible, deterministic in offline mode, and capable of validating the workflow against the real SuperDocs API.

---

## What Has Been Built

### 1. Synthetic Document Corpus

A deterministic synthetic corpus generator has been implemented.

The corpus contains:

- **5 document-size tiers:** `tiny`, `small`, `medium`, `large`, `xlarge`
- **3 document domains:** vendor contracts, project status reports, insurance claims

The generated corpus is stored under:

```text
data/corpus/
```

### 2. Multi-Turn Edit Sessions

The benchmark generates multi-turn editing sessions across the synthetic documents. Five edit types are supported. These sessions allow the benchmark to measure how token usage and cost evolve over multiple edits to the same document.

### 3. Benchmark Arms

Two editing strategies are evaluated.

**Whole-Document Arm** — the complete document is sent for every edit:

```text
Document
   ↓
Full document + edit instruction
   ↓
Model/API
```

This provides a baseline for understanding the cost of repeatedly sending large documents.

**Section-Edit Arm** — only the relevant section is sent for an edit:

```text
Document
   ↓
Relevant section + edit instruction
   ↓
Model/API
```

This tests whether targeted editing can reduce token usage and cost.

### 4. API Client Architecture

The benchmark uses a common client abstraction:

```text
BaseClient
   ├── MockClient
   └── SuperDocsClient
```

**MockClient** provides:

- Offline execution
- Deterministic behavior
- Reproducible benchmark runs
- No API key requirement

**SuperDocsClient** communicates with the real SuperDocs API. The implemented workflow covers:

```text
Upload
   ↓
Chat / Edit
   ↓
Approve
   ↓
Export
```

The real API integration has been validated against the live SuperDocs API.

### 5. Metrics

Each edit records the following metrics:

| Metric | Description |
|---|---|
| Input tokens | Tokens sent to the model |
| Output tokens | Tokens generated |
| Total tokens | Input + output |
| Cost | Estimated/calculated API cost |
| Latency | Time taken for the operation |
| Characters sent | Size of the request |
| Document tier | tiny → xlarge |
| Editing arm | Whole-document / Section-edit |
| Edit type | Type of edit performed |

Repeated runs can be used to measure variance.

### 6. Token Measurement

For offline/mock execution, an approximately 4-characters-per-token heuristic is used when an actual token count is unavailable.

For real API execution, API-reported token usage is preferred when available:

- `usage.input_tokens`
- `usage.output_tokens`

The local estimator is therefore a fallback and not the source of truth when the real API provides usage information.

### 7. Cost Measurement

Cost calculation is implemented in `benchmark/metrics.py`. Pricing is kept as configuration so it can be updated without changing the benchmark implementation.

> **Note:** The currently configured pricing values are illustrative placeholders and should be replaced with SuperDocs' actual per-model pricing before using the results as production cost estimates.

### 8. Budget Guard

The benchmark includes a cumulative budget guard. The guard checks spending after each completed edit. If the budget would be exceeded:

- Current results are written.
- The next edit is not started.
- The benchmark stops.
- Partial results are preserved.

### 9. Benchmark Workflow

The complete workflow is:

```text
Synthetic Corpus
       ↓
Document Size Tiers
       ↓
Multi-Turn Edit Sessions
       ↓
 ┌─────────────────────┐
 │                      │
 ▼                      ▼
Whole-Document      Section-Edit
     Arm                 Arm
 │                      │
 └──────────┬───────────┘
            ↓
        API Client
            ↓
      Collect Metrics
            ↓
       Budget Guard
            ↓
       Save Results
            ↓
      Generate Reports
            ↓
          Charts
```

---

## Running the Project

### 10. Install

Clone the repository:

```bash
git clone <REPOSITORY_URL>
cd doctask-shubhamdixit
```

Create the virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 11. Run Tests

Run the complete test suite:

```bash
pytest -q
```

The current test suite contains 22 tests covering areas including:

- Corpus generation
- Benchmark arms
- Metrics
- Runner behavior
- Budget handling

### 12. Run a Mock Benchmark

Mock mode does not require an API key or network access.

Run a small benchmark:

```bash
python -m benchmark.runner --mode mock --small-sample
```

Run the full benchmark:

```bash
python -m benchmark.runner --mode mock
```

### 13. Run the Real SuperDocs Benchmark

Configure the API key:

```bash
export SUPERDOCS_API_KEY="your-api-key"
```

Run a small real-API validation:

```bash
python -m benchmark.runner --mode real --small-sample
```

Run a full real benchmark:

```bash
python -m benchmark.runner --mode real
```

> **Warning:** Real API runs may consume API usage. Never commit API keys or credentials to the repository.

### 14. Helper Script

The repository also contains `run.sh`. Run it with:

```bash
bash run.sh
```

If required, make it executable first:

```bash
chmod +x run.sh
./run.sh
```

The available benchmark options can always be checked with:

```bash
python -m benchmark.runner --help
```

---

## Deliverables

### 15. Deliverable Locations

**Benchmark implementation** — `benchmark/`

```text
benchmark/
├── arms.py
├── client.py
├── corpus.py
├── edit_tasks.py
├── metrics.py
├── report.py
└── runner.py
```

**Tests** — `tests/`

```text
tests/
├── test_arms.py
├── test_corpus.py
├── test_metrics.py
└── test_runner.py
```

**Synthetic corpus** — `data/corpus/`

**Benchmark results** — `data/results/`

The generated results include:

- `raw_edits.csv`
- `raw_edits.json`
- `run_summary.json`
- `summary_by_arm.csv`
- `summary_by_tier_and_arm.csv`
- `variance_report.csv`
- `cost_vs_doc_size.png`
- `cumulative_session_cost.png`

### 16. Viewing the Results

List all generated results:

```bash
ls -lh data/results/
```

View the overall summary:

```bash
cat data/results/run_summary.json
```

View the comparison between benchmark arms:

```bash
cat data/results/summary_by_arm.csv
```

View results by document size and arm:

```bash
cat data/results/summary_by_tier_and_arm.csv
```

View variance:

```bash
cat data/results/variance_report.csv
```

View the first rows of the raw results:

```bash
head -20 data/results/raw_edits.csv
```

### 17. Viewing Charts

On macOS:

```bash
open data/results/cost_vs_doc_size.png
open data/results/cumulative_session_cost.png
```

The charts provide visual comparisons of:

- Cost vs. document size
- Cumulative session cost

---

## 18. Project Structure

```text
.
├── benchmark/
│   ├── __init__.py
│   ├── arms.py
│   ├── client.py
│   ├── corpus.py
│   ├── edit_tasks.py
│   ├── metrics.py
│   ├── report.py
│   └── runner.py
│
├── data/
│   ├── corpus/
│   └── results/
│
├── tests/
│   ├── __init__.py
│   ├── test_arms.py
│   ├── test_corpus.py
│   ├── test_metrics.py
│   └── test_runner.py
│
├── PROGRESS.md
├── TASK.md
├── README.md
├── requirements.txt
└── run.sh
```

---

## 19. Important Assumptions and Limitations

**Corpus sizing** — The benchmark uses 1 page ≈ 500 words as a corpus-sizing convention. It is not intended to represent a measured universal relationship.

**Section insertion** — For the section-edit arm, an insert operation is simplified by adding the new content to the targeted section rather than creating a completely new section. This may underestimate the cost and complexity of a true structural insertion.

**Token estimation** — Mock/offline runs may use the approximately 4-characters-per-token heuristic. Real API token usage is preferred when available.

**Pricing** — The pricing values currently configured in `benchmark/metrics.py` are illustrative and should be replaced with actual SuperDocs model pricing before using the benchmark for production cost analysis.

**Mock results** — Mock results are useful for deterministic comparisons but should not be presented as measured production SuperDocs costs.

---

## 20. Reproduce the Benchmark From Scratch

After cloning the repository:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest -q
python -m benchmark.runner --mode mock --small-sample
```

Then inspect the results:

```bash
ls -lh data/results/
```

View the summary:

```bash
cat data/results/run_summary.json
```

---

## 21. Final Verification

Before submission:

```bash
pytest -q
python -m benchmark.runner --help
python -m benchmark.runner --mode mock --small-sample
ls -lh data/results/
```

Check Git status:

```bash
git status
```

Review the recent commits:

```bash
git log --oneline --decorate --graph -10
```

Make sure no API keys, credentials, `.env` files, virtual environments, or other private data are committed.

---

## 22. AI Use Disclosure

Claude was used during development to assist with scaffolding and iteration of the benchmarking harness. This use of AI assistance is disclosed as part of the project submission. The implementation, assumptions, API integration, tests, benchmark workflow, and limitations were reviewed during development.

---

## Documentation Notes

This `README.md` is the single documentation entry point for the project. `PROGRESS.md` and `TASK.md` remain in the repository as project artifacts (development log and task tracking, respectively), but all setup, usage, and reference information lives here.