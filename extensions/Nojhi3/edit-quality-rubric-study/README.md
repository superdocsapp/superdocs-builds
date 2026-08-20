# Edit-Quality Rubric + Inter-Rater Agreement Study

A rubric for scoring the quality of AI document edits, plus an inter-rater
agreement study between a **human judge** and an **automated LLM judge** —
with honest reporting of where the automated judge is unreliable.

Built on SuperDocs' minimum four-call contract for every edit:
`upload` -> `chat` (async, HITL) -> `approve` -> `export`.

## What it does

1. **Runs edits.** A corpus of 3 documents (a project plan, meeting notes, a
   service contract with a pricing table) x a battery of instructions across
   four difficulty bands (easy / medium / hard / ambiguous) = 11 edits. Every
   edit goes through SuperDocs with human-in-the-loop approval of each
   proposed change, then exports the finished file.
2. **Scores with a rubric.** A 6-dimension ordinal rubric (1-4 with written
   anchors) for document edit quality: faithfulness to instruction, fact
   accuracy, content preservation, structural integrity, formatting fidelity,
   language quality.
3. **Measures agreement.** A human judge and an automated judge (an LLM, blind
   to the other's scores) each score every edit. Cohen's kappa (unweighted and
   linear-weighted), percent agreement, per-dimension confusion matrices,
   percentile-bootstrap 95% CIs, and a case-by-case disagreement review —
   computed in pure Python, no scipy.
4. **Reports honestly.** The study report (markdown, plus a PDF/DOCX export
   produced through SuperDocs' export endpoint) states the budget cap before
   each run, reports actual operation spend, and names every judgment where
   the automated judge was unreliable, quoting both raters' evidence.

## Finding from the pilot: SuperDocs chat is an editor, not a scorer

The automated judge was first implemented with SuperDocs' own chat model.
Pilot runs showed it will not reliably score documents: it answers long
scoring prompts with short acknowledgments ("Done.", "I'll score the edit
now."), and with `approval_mode=ask_every_time` it only acknowledges. A JSON
scoring turn therefore uses a general-purpose LLM (default: Gemini via any
OpenAI-compatible endpoint, `JUDGE_PROVIDER=gemini`), recorded in its own
token ledger (`data/ledger_gemini.jsonl`). The SuperDocs-chat judge is kept
for comparison (`JUDGE_PROVIDER=superdocs`). This is itself a reliability
finding about automated judging on this platform.

## Budget guard

- Cap stated before every run: **60 operations** (default, editable in
  `app/budget.py`). Every billable call is checked against the cap before it
  starts and recorded in `data/ledger.jsonl` (endpoint, billable flag, ops
  charged, monthly remaining).
- Small-sample mode: `--small` runs the first 6 cases; the full run is all 11.
- Actual spend is printed after every step and published in the report.

## How to run

```bash
pip install -r requirements.txt

# 1) SuperDocs key (free agent self-signup, no human needed):
#    POST https://api.superdocs.app/v1/agents/signup  {"terms_accepted": true}
cp .env.example .env   # fill SUPERDOCS_API_KEY, GEMINI_API_KEY

# 2) Run the edit pipeline (small sample first):
python scripts/run_study.py --small --edits

# 3) Human judging UI:
uvicorn app.main:app          # open http://127.0.0.1:8000/judge

# 4) Automated judge (blind to human scores):
python scripts/run_study.py --small --judge-auto

# 5) Report + export through SuperDocs:
python scripts/run_study.py --report
curl -o report.pdf "http://127.0.0.1:8000/study/report/export?format=pdf"

# 6) Offline integrity self-check (no API calls, no spend; exit 0 = all pass):
python scripts/selftest.py

# 7) Full test suite (141 tests, offline, no spend):
pip install -r requirements-dev.txt
python -m pytest          # or: pytest tests/test_stats.py -v
```

### Quick recipes

**Export the report** (non-billable, 0 ops):
```bash
python scripts/run_study.py --report
curl -o report.pdf  "http://127.0.0.1:8000/study/report/export?format=pdf"
curl -o report.docx "http://127.0.0.1:8000/study/report/export?format=docx"  # or html|markdown|txt
```

**Check the rubric's value** (dimensions, scale, written anchors):
```bash
curl -s http://127.0.0.1:8000/rubric   # live, from the API
python -m json.tool data/rubric.json   # offline, straight from the file
```

**Start a run whose budget estimate is over the cap** — the guard refuses
*before* any billable call, so this spends **0 ops**:
```bash
python scripts/run_study.py --edits plan-01 --cap 0
# Cap stated before this run: 0 operations.
# >>> done in 2s (0 completed, 1 failed)
#     failed: {'case_id': 'plan-01', 'error': 'budget cap exceeded'}
# [budget] after edits: spent 12/60 ops (12 billable calls)   <- ledger unchanged
```

Every scenario with commands and exact expected output lives in
**[HOW_TO_RUN.md](HOW_TO_RUN.md)**.

The self-check verifies the rubric schema, all 11 cases' edit artifacts,
both raters' score sheets, the statistics on hand-derived examples (kappa =
1.0 / 0.0 / 2/3, Landis-Koch band edges), report rendering, the exported
DOCX/PDF files, ledger consistency, and that no API keys are committed
outside `.env`.

The pytest suite is behavioral and network-mocked. It covers: hand-derived
kappa (unweighted, linear-weighted, band edges, bootstrap CIs, analyze() on
synthetic sheets), the full edit pipeline against a scripted fake SuperDocs
client (happy path, revision loop, no-op completion, failures, budget cap),
both judges against a mocked HTTP layer (JSON extraction incl. the
double-encoded second parse, retries, invalid-score rejection), the report
markdown/HTML conversion (including the multi-bold regression), every FastAPI
endpoint (validation, 404/409/422/502 paths), and — most importantly — an
**integration test that pins the study's headline numbers** (11 cases, 66
judgments, kappa 0.339, weighted 0.405, 8 disagreements, per-dimension
values, score distributions, 12 ops spent). If a code change ever alters a
study number, that test fails by design.

The FastAPI service (`app/main.py`) also exposes every step as an endpoint:
`/rubric`, `/cases`, `POST /study/edits`, `POST /study/judge/auto`, `/judge`,
`/judge/submit`, `/study/analysis`, `/study/budget`, `/study/report`,
`/study/report/export`.

## SuperDocs features used

- REST API: `POST /v1/documents/upload-base64` (upload), `POST /v1/chat/async`
  with `approval_mode=ask_every_time` (edit + HITL review),
  `POST /v1/chat/{session_id}/approve` (approve proposed changes, including
  the AI's revision loop after approval), `POST /v1/documents/export` (export
  finished documents AND the study report itself), `GET /v1/jobs/{job_id}`
  (polling), `GET /v1/agents/whoami` (quota/usage).
- Operation-level billing telemetry from every chat response (usage block),
  recorded per call in `data/ledger.jsonl`.

## Repo layout

```
app/            FastAPI service + client, budget guard, rubric, pipeline,
                judges, statistics, report generation
scripts/        run_study.py CLI (--small / --full / --edits / --judge-auto / --report),
                selftest.py (offline integrity checks)
tests/          pytest suite (141 tests): stats, pipeline, judges, client
                utils, report, API endpoints, real-data integration
data/corpus/    3 source documents (real + synthetic)
data/rubric.json     the rubric (dimensions, anchors)
data/instructions.json   the 11 edit cases with difficulty labels
data/edits/<case_id>/    per-edit artifacts: upload, pending changes,
                         approvals, job result, before/after, exported docx
data/judgments/          human + automated score sheets
data/ledger.jsonl        SuperDocs operation ledger (cap + actual spend)
data/ledger_gemini.jsonl judge token ledger
report/                  generated study report
```

## License

MIT. No API keys are committed; all secrets live in a gitignored `.env`.

Built for the SuperDocs engineering task (round 2) by Akshat Rai.