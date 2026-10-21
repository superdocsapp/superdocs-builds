# Evaluation and reviewer guide

`OFFLINE_VERIFIED` is deterministic or synthetic local evidence; `LIVE_VERIFIED` is a real provider proof; `BLOCKED_REAL_DEFECT` is a real provider interaction that LineCard correctly refused to complete. No blocked row is relabeled green.

| requirement | milestone | implementation / evidence | status | notes |
|---|---|---|---|---|
| long OEM manual; task retrieval across separated sections | M2 | `ingest.py`, `retrieval.py`, 400-page gold ledger | OFFLINE_VERIFIED | synthetic LC-100 |
| exact torque/safety values; source page for every required step | M1/M2/M3 | `m1.py`, evidence pack, sabotage tests | OFFLINE_VERIFIED | `24 N·m ± 2 N·m` |
| flow diagram; exactly two pages; no safety step dropped | M3/M4 | `flow.py`, `layout.py`, postflight tests | OFFLINE_VERIFIED | evidence-backed SVG |
| batch; second manual; two retrieval channels | M2/M5 | AX-200 fixture, FTS5 plus provider staging, batch ZIP | OFFLINE_VERIFIED | synthetic/offline |
| conflict, unsupported number, wrong citation, manual target, hostile content | M1–M3/M6 | `staging.py`, `review.py`, `security.py` | OFFLINE_VERIFIED | fail closed |
| review decisions; recovery/idempotency; three-task isolation | M3/M5 | SQLite store/worker and batch tests | OFFLINE_VERIFIED | no merged blocked success |
| sample/budget/safety stop; export/postflight | M4/M5 | `batch.py`, `layout.py`, PDF checks | OFFLINE_VERIFIED | local path |
| accessibility; error matrix; security | M6 | React, `errors.py`, `security.py`, unit/E2E | OFFLINE_VERIFIED | served browser passes |
| SuperDocs upload/review/read-back/export contract | M0/M1/M4 | contract doc, sanitized live run, image proof | LIVE_VERIFIED | bounded provider proof |
| direct proposal chunk identity reconciliation | M1 | `staging.py`, live bug report | BLOCKED_REAL_DEFECT | corrected recovery 8/6 and fresh live run 8/31; both had zero direct matches |
| mixed decisions/final provider reconciliation | M1 | M1 runner and verifier, live bug report | BLOCKED_REAL_DEFECT | implementation verified; provider path blocked |
| metrics and fresh clone | M6 | `examples/metrics-report.md`, `scripts/fresh_clone_check.sh` | OFFLINE_VERIFIED | no peak-memory measurement |

Frozen ledger counts: **TOTAL 27; OFFLINE_VERIFIED 19; LIVE_VERIFIED 6; BLOCKED_REAL_DEFECT 2; TODO 0; IMPLEMENTED 0.** The row-level ledger is [acceptance-ledger.md](acceptance-ledger.md) and remains unchanged.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
cd frontend && npm ci && cd ..
make check
make demo
.venv/bin/python scripts/metrics_full.py
git diff --check
```

No live command is required. Do not submit decisions to the blocked job.
