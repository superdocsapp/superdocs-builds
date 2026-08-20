# How to run — every scenario, with what to expect

This is the run book for the Edit-Quality Rubric + Inter-Rater Agreement study.
Commands are split into **zero-spend** (offline, safe to run any time) and
**budget-spending** (real SuperDocs calls, guarded by the operation cap).

All commands run from this project root unless stated otherwise.

---

## A. Prerequisites

```bash
pip install -r requirements.txt          # runtime
pip install -r requirements-dev.txt      # + pytest, for the test suite

cp .env.example .env                     # then fill in the values:
# SUPERDOCS_API_KEY=sk_your-key-here     # SuperDocs key (agent self-signup: POST
#                                        #   https://api.superdocs.app/v1/agents/signup)
# GEMINI_API_KEY=your-gemini-key         # only needed for the automated judge
```

- **Budget cap:** default **60 operations** (see `app/config.py`,
  `DEFAULT_BUDGET_CAP_OPS`). Override any run with `--cap N`.
- **Small sample vs full:** `--small` = first 6 cases; `--full` = all 11.
- Every billable call is checked against the cap **before** it starts and
  recorded in `data/ledger.jsonl`.

---

## B. Zero-spend scenarios (offline, no API calls)

### B1. Full test suite — 141 tests

```bash
python -m pytest
```

Expect: `141 passed`. Covers hand-derived kappa (unweighted, linear-weighted,
band edges, bootstrap CIs), the full edit pipeline against a scripted fake
SuperDocs client (happy path, revision loop, failures, budget cap), both
judges against a mocked HTTP layer, report conversion, every FastAPI endpoint,
and an integration test that pins the study's headline numbers.

### B2. Integrity self-check

```bash
python scripts/selftest.py
```

Expect: `ALL CHECKS PASSED` (exit 0). Verifies the rubric schema, all 11
cases' edit artifacts, both raters' score sheets, hand-derived kappa examples,
report rendering, the exported PDF/DOCX files, ledger consistency, and that
no API keys exist outside `.env`.

### B3. Inspect the rubric

```bash
python -m json.tool data/rubric.json        # offline, straight from the file
```

or, with the server running (see C2):

```bash
curl -s http://127.0.0.1:8000/rubric
```

Expect: `rubric_name`, `version`, `scale`, `instructions`, and 6 `dimensions`,
each with a 1-4 scale of written anchors, e.g.
`faithfulness` — "Did the edit do what the instruction asked, at the scope the
instruction implied?" with anchors for 1 (ignored the instruction) through
4 (did exactly and only what was asked).

### B4. Inspect the study data

```bash
ls data/edits/<case_id>/        # per-edit artifacts for each of the 11 cases:
#   before.html / before.md     original source document
#   after.html / after.md       edited document
#   upload.json, chat_start.json, pending_changes.json, chat_result.json,
#   job_final.json, record.json full audit of the upload->chat->approve->export flow
#   after.docx                  exported finished file
ls data/judgments/human/        # 11 human score sheets (one per case)
ls data/judgments/auto/         # 11 automated-judge score sheets (blind)
tail data/ledger.jsonl          # SuperDocs operation ledger (cap + actual spend)
```

### B5. Budget guard refusal demo — **spends 0 ops**

The guard fires **before** any billable call, so this costs nothing:

```bash
python scripts/run_study.py --edits plan-01 --cap 0
```

Expect:

```
Cap stated before this run: 0 operations.
Account: a2ab81ae-... | tier: free | remaining ops: <n> | used: <n>
Cases selected: all

>>> EDIT PIPELINE for ['plan-01']
>>> done in 2s (0 completed, 1 failed)
    failed: {'case_id': 'plan-01', 'error': 'budget cap exceeded'}
[budget] after edits: spent 12/60 ops (12 billable calls)
```

The run refuses to start the billable edit call because `spent (12) + 1 > cap (0)`.
The ledger gets **no** new entry. To see a refusal *mid*-run instead, use a cap
large enough for one case: `python scripts/run_study.py --edits plan-01 plan-02 --cap 1`
completes plan-01 (1 op) then refuses plan-02 (costs 1 op and re-runs plan-01).

---

## C. Budget-spending study scenarios

Every run prints the cap **before** it starts and the actual spend **after**
every step. Example full flow:

```bash
# 1) run the edits (small sample = 6 cases, ~1 op each)
python scripts/run_study.py --small --edits

# 2) human judging — open the UI, score every completed case
uvicorn app.main:app
# open http://127.0.0.1:8000/judge
#   each card shows the INSTRUCTION, the source document, and the edited
#   document side by side, with per-dimension 1-4 scores + an evidence box.

# 3) automated judge (blind to human scores; separate Gemini token ledger)
python scripts/run_study.py --small --judge-auto

# 4) assemble the report
python scripts/run_study.py --report
```

The full run (`--full`) covers all 11 cases instead of 6.

---

## D. Report export — non-billable

Exports the study report through SuperDocs (0 operations). With the server
running:

```bash
curl -o report.pdf  "http://127.0.0.1:8000/study/report/export?format=pdf"
curl -o report.docx "http://127.0.0.1:8000/study/report/export?format=docx"
curl -o report.html "http://127.0.0.1:8000/study/report/export?format=html"
curl -o report.md   "http://127.0.0.1:8000/study/report/export?format=markdown"
```

Expect a valid file (PDF starts with `%PDF-`). An invalid format is rejected:
`?format=exe` returns **422**.

---

## E. Server endpoint smoke checklist

`uvicorn app.main:app` then:

| Endpoint | Expected |
| --- | --- |
| `GET /` | JSON index of every endpoint |
| `GET /rubric` | rubric JSON (6 dimensions, 1-4 anchors) |
| `GET /cases` | the 11 cases with difficulty bands |
| `GET /judge` | human judging UI (HTML) |
| `GET /study/scores` | both raters' score sheets |
| `GET /study/analysis` | kappa **0.339** (95% CI), weighted **0.405**, per-dimension bands, confusion matrices |
| `GET /study/budget` | cap 60, spent 12, remaining 48 |
| `GET /study/report` | the full report as markdown |
| `GET /study/report/export?format=pdf` | report PDF (`application/pdf`) |

---

## F. Where the results are

- **`report/study_report.md`** — the study report:
  - §3 **Budget guard** — cap stated before the run
  - §4 **Actual spend** — 12 of 60 ops, full per-call ledger
  - §6 **Inter-rater agreement** — percent agreement, kappa, CIs, per-dimension
  - §7 **Disagreement review** — the 8 judgments where the automated judge was
    unreliable, quoting both raters' evidence
  - §8 **Honest limitations** — small sample, single human rater, sparse human
    evidence, ordinal ceiling, visual-blindness
- **`report/study_report.pdf` / `.docx`** — exported copies
- **`data/edits/<case_id>/`** — before/after material for every judgment
- **`data/ledger.jsonl`** — the operation ledger behind the spend numbers

## G. Reproduce / verify the headline numbers

The integration test pins the study's numbers so a code change that alters any
of them fails the suite:

```bash
python -m pytest tests/test_study_integration.py -v
```