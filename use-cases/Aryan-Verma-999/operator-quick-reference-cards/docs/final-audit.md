# Final implementation audit

This audit does not add or relabel acceptance rows. It expands the frozen
ledger into reviewer-facing evidence. `LIVE_VERIFIED` is real provider proof;
`OFFLINE_VERIFIED` is local deterministic/synthetic proof;
`BLOCKED_REAL_DEFECT` is a real provider interaction that LineCard correctly
stopped.

| requirement | milestone | implementation location | test/evidence | status | notes |
|---|---|---|---|---|---|
| upload, reviewed edit, approval, read-back, export contract | M0 | `superdocs_client.py` | `docs/superdocs-contract.md` and recorded M0 run | LIVE_VERIFIED | historical bounded contract proof |
| exact staging HTML and explicit target | M1 | `chat_async` | `docs/superdocs-contract.md` | LIVE_VERIFIED | no new operation |
| document sync and authoritative chunk map | M1 | `staging.py` | documented `document_sync.content`; 8 synchronized chunks | LIVE_VERIFIED | complete HTML recovered |
| direct chunk identity and version/content checks | M1 | `proposal_slot`, `review.py` | reconciliation tests and bug report | BLOCKED_REAL_DEFECT | zero direct matches: 8/6 recovery and 8/31 fresh live run |
| ordered SSE/reconnect event handling | M1 | `stream_events` | sequence 1 precedes sequence 7; replay tests | LIVE_VERIFIED | direct reconnect separately unproven |
| pending-review recovery | M1 | `pending_review` | awaiting job recovered, then a fresh job returned 31 pending proposals | LIVE_VERIFIED | no decision submitted |
| mixed review, final reconciliation, unchanged manual, two-page PDF | M1 | `m1.py`, `fallback.py`, `layout.py` | offline integration; live bug report | BLOCKED_REAL_DEFECT | implementation verified; provider path blocked |
| native PDF ingest, hash, page/spans, rejection gates | M2 | `ingest.py` | ingest fixture suite and 400/60-page manifests | OFFLINE_VERIFIED | native text only |
| task-specific retrieval across separated sections | M2 | `retrieval.py` | FTS5/conflict tests and gold ledgers | OFFLINE_VERIFIED | local plus provider semantic channel |
| exact torque/safety values and citation per required step | M2/M3 | `m1.py`, evidence pack | sabotage tests, report JSON | OFFLINE_VERIFIED | `24 N·m ± 2 N·m`; six records |
| safety ledger and required wording | M3 | `fallback.py`, `m1.py` | missing/weakened safety tests | OFFLINE_VERIFIED | no required step silently dropped |
| human proposal decisions and rejected content absence | M3 | `review.py`, frontend | mixed decision tests and review surface | OFFLINE_VERIFIED | live provider approval intentionally blocked |
| durable worker recovery and outbox | M3/M5 | `storage.py`, `worker.py` | restart/lease/effect tests | OFFLINE_VERIFIED | stale worker fenced |
| typed flow diagram and unsupported number blocking | M4 | `flow.py` | deterministic Mermaid/SVG and rejection tests | OFFLINE_VERIFIED | Mermaid provider wire format not invented |
| provider diagram/image contract | M4 | `flow.py`, client export | `docs/superdocs-contract.md` | LIVE_VERIFIED | image upload/export proof plus local SVG |
| bounded two-page layout | M4 | `layout.py` | impossible-fit tests | OFFLINE_VERIFIED | `PAGE_BUDGET_UNSATISFIABLE` |
| exact two-page export and PDF postflight | M4 | `layout.py`, `m1.py` | public PDF, postflight tests | OFFLINE_VERIFIED | 2 pages; no warning claim beyond recorded proof |
| three isolated tasks | M5 | `batch.py` | public batch manifest and ZIP test | OFFLINE_VERIFIED | separate card/evidence/session fields |
| sample gate, concurrency, blocked sibling | M5 | `execute_batch` | batch continuation tests | OFFLINE_VERIFIED | aggregate never hides blocked item |
| operation budget and safety stop | M5 | `batch.py`, client budget | budget tests and manifest | OFFLINE_VERIFIED | live budget not spent here |
| retry/resume and truthful manifest | M5 | `retry_resume`, `batch_manifest` | continuation tests | OFFLINE_VERIFIED | attempts and stage visible |
| HTTP/network error matrix and idempotent API | M6 | `errors.py`, `api.py`, `storage.py` | error matrix tests | OFFLINE_VERIFIED | normalized recovery guidance |
| hostile/prompt-injection content inert | M6 | `security.py`, sanitization | hostile fixture/security tests | OFFLINE_VERIFIED | no route/tool/approval selection |
| accessible review surface | M6 | `frontend/src/main.tsx` | unit and keyboard Playwright | OFFLINE_VERIFIED | actual served runtime |
| fresh clone/reviewer setup | M6 | `scripts/fresh_clone_check.sh` | clean temporary copy | OFFLINE_VERIFIED | no live call; Docker not claimed |
| multi-manual/multi-task metrics | M6 | `scripts/metrics_full.py`, examples | raw/report and public snapshot | OFFLINE_VERIFIED | synthetic timings; memory unavailable |

Assigned-task invariants are therefore explicitly covered: long OEM manual,
task retrieval, separated-section search, exact values/safety, per-step source
pages, flow, two-page budget, safety preservation, batch, second manual, two
retrieval channels, conflict handling, unsupported numeric/wrong citation/
manual-target blocking, hostile content inertness, impossible-task fail-closed,
review, recovery/idempotency, three-task isolation, stopping behavior, export,
accessibility, error matrix, security, fresh-copy proof, and metrics.

The acceptance ledger remains exactly 27 rows: 19 `OFFLINE_VERIFIED`, 6
`LIVE_VERIFIED`, 2 `BLOCKED_REAL_DEFECT`, 0 `TODO`, and 0 `IMPLEMENTED`.
