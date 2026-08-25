# How to Work With VocDigest

Operating guide. For design rationale see `README.md`; for assumptions and known gaps
see `PROGRESS.md`.

---

## Starting a run

**HTTP**
```bash
curl -X POST http://localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -d '{
        "conversations_path": "sample_data/q3_2026_conversations.csv",
        "last_digest_path": "sample_data/q2_2026_digest.docx",
        "quarter_label": "Q3 2026"
      }'
# -> {"run_id": "...", "status": "PENDING"}
```

`last_digest_path` is optional. Without it the digest states that no comparison was
available and contains no growth figures — it does not estimate them.

**Upload instead of paths** (files stream to disk, never buffered whole in memory):
```bash
curl -X POST http://localhost:8000/runs/upload \
  -F conversations=@q3.csv -F last_digest=@q2.docx -F quarter_label='Q3 2026'
```

**MCP**
```python
start_run(conversations_path="…/q3.csv", last_digest_path="…/q2.docx", wait=True)
```
`wait=True` blocks until the run pauses or finishes, which saves an agent from polling.

---

## Checking status

```bash
curl http://localhost:8000/runs/{id}
```

Returns status, the nine-stage timeline with per-stage timing and token cost, and the
decision log. The decision log is the interesting part — it records *why* the agent did
what it did, not just what ran.

Live updates: `GET /runs/{id}/events` is a Server-Sent Events stream. The frontend uses
it and falls back to 3-second polling if the stream errors, because some proxies buffer
SSE indefinitely, which is indistinguishable from a hung backend.

---

## Approving items

The run stops at `AWAITING_APPROVAL` and will not proceed until every item is decided.

```bash
curl http://localhost:8000/runs/{id}/approval-items
```

Items are grouped by type. Review `QUOTE` items first: those are the ones where
anonymization was uncertain and a span is marked `[POSSIBLE-NAME]`.

```bash
curl -X POST http://localhost:8000/runs/{id}/approve \
  -H 'Content-Type: application/json' \
  -d '{"approved_ids": ["…"], "rejected_ids": ["…"], "notes": {"…": "why"}}'
```

The run resumes automatically once nothing is pending. `POST /runs/{id}/approve-all`
accepts everything outstanding.

**Rejecting removes content, it does not fail the run.** A rejected theme is dropped
from the document and the export still happens. This is deliberate and tested.

---

## Retrying or skipping a single stage

```bash
# Re-run one stage. Clears its checkpoint AND every stage after it, because their
# results were computed from output that is about to change. Upstream is preserved.
curl -X POST localhost:8000/runs/{id}/stages/retry \
  -H 'Content-Type: application/json' -d '{"stage": "theme"}'

# Skip a stage entirely and move past it.
curl -X POST localhost:8000/runs/{id}/stages/skip \
  -H 'Content-Type: application/json' -d '{"stage": "compare"}'
```

`ingest`, `theme` and `human_gate` cannot be skipped and return 409. Skipping ingest
leaves no data, skipping theme leaves nothing to report, and skipping the gate would
publish unreviewed content. Operator skips are recorded in the decision log as
`SKIPPED_BY_OPERATOR`.

Both are also available from the run detail page in the UI.

---

## Resuming after a crash

Restart the server. Checkpoints live in Postgres, not in memory.

```bash
curl http://localhost:8000/runs/{id}          # see where it stopped
curl -X POST http://localhost:8000/runs/{id}/resume
```

Completed stages return their cached results and make no LLM or SuperDocs calls. A
resumed run costs only the work that had not finished.

The same command resumes a run paused for a non-crash reason — Groq being unavailable,
or a SuperDocs quota or timeout. Those pause the run rather than failing it, so nothing
already paid for is discarded.

---

## Cost and results

```bash
curl http://localhost:8000/runs/{id}/cost      # per-stage tokens, time, SuperDocs ops
curl http://localhost:8000/runs/{id}/themes    # themes with quotes and citations
curl -OJ http://localhost:8000/runs/{id}/export
```

---

## MCP usage

```bash
python -m backend.mcp.server     # listens on :8001
```

Connect any MCP client to `http://localhost:8001`. Seven tools:

| Tool | Purpose |
|---|---|
| `start_run` | Begin a digest run |
| `get_run_status` | Stage, status, timeline, recent decisions |
| `list_approval_items` | The review queue |
| `approve_run_items` | Accept/reject, then resume |
| `get_cost_report` | Per-stage tokens, time, operations |
| `get_themes` | Themes with volumes, trends, quotes, citations |
| `export_digest` | Path to the finished document |

Typical agent loop: `start_run(wait=True)` → `list_approval_items` → inspect →
`approve_run_items` → `export_digest`.

---

## Checkpoint mirror (optional)

Set `CHECKPOINT_SQLITE_PATH` to mirror every checkpoint into a standalone SQLite file:

```bash
CHECKPOINT_SQLITE_PATH=./data/checkpoints.db
```

Postgres stays authoritative — the mirror is write-behind and best-effort, so a mirror
failure is logged and never fails a run. It exists so run state survives losing the
primary database, and so progress can be inspected with nothing but the file:

```bash
sqlite3 data/checkpoints.db "SELECT stage, status, attempts FROM checkpoints;"
```

`backend.db.sqlite_checkpoint.recover_run(run_id)` reconstructs a run's completed-stage
list from the file alone.

---

## Running without API keys

The whole test suite runs with no keys and no database server:

```bash
pytest backend/tests/ -q                 # SQLite, no infrastructure

# Same suite against real Postgres + pgvector. Do this before trusting the
# similarity-search path — the SQLite fallback computes distances in Python and
# cannot catch a broken SQL operator.
VOCDIGEST_TEST_DATABASE_URL="postgresql+asyncpg://vocdigest:vocdigest@localhost:5432/vocdigest_test" \
  pytest backend/tests/ -q
```

To exercise the real HTTP API with mocked external services:

```bash
DATABASE_URL="sqlite+aiosqlite:///./data/demo.db" AUTO_CREATE_TABLES=true \
EMBEDDING_BACKEND=hash CLUSTER_THRESHOLD=0.35 \
python scripts/demo_server.py
```

Server, routing, database, background execution and SSE are all genuine; only Groq and
SuperDocs are stubbed.

---

## Running with a service down

Both fallbacks are on by default, so nothing is required to use them.

```bash
# Force the no-LLM path to see what degraded output looks like
GROQ_API_KEY= python scripts/demo_server.py

# Force local rendering
SUPERDOCS_API_KEY= python scripts/demo_server.py
```

Check what happened after a run:

```bash
curl -sS localhost:8000/runs/{id} | jq '.summary.degraded_stages, .summary.rendered_locally'
curl -sS localhost:8000/runs/{id} | jq '.decision_log[] | select(.decision=="DEGRADED")'
```

To pause instead of degrading — useful when quality matters more than turnaround:

```bash
ALLOW_DEGRADED_ANALYSIS=false   # pause rather than use heuristics
ALLOW_LOCAL_RENDER=false        # pause rather than render locally
```

A paused run keeps every completed checkpoint. Add the key and
`POST /runs/{id}/resume` continues from where it stopped.

---

## Configuration worth knowing

| Variable | Note |
|---|---|
| `GROQ_TEMPERATURE` | Must stay `0`. Idempotency depends on it — a resumed run would otherwise diverge from the run it continues. |
| `EMBEDDING_BACKEND` | `local` for real clustering (needs `pip install sentence-transformers`), `hash` for offline. |
| `CLUSTER_THRESHOLD` | `0.62` suits MiniLM. With `hash`, use ~`0.35` or themes fragment badly. |
| `EMBEDDING_DIM` | Must match the model. Changing it requires a new migration — the pgvector column width is fixed at migration time. |
| `AUTO_CREATE_TABLES` | Demo and tests only. Alembic owns the schema in deployment. |
| `CHECKPOINT_SQLITE_PATH` | Optional write-behind checkpoint mirror. Empty disables it. |
| `ALLOW_DEGRADED_ANALYSIS` | Default true. Falls back to keyword heuristics when Groq is unavailable. False pauses instead. |
| `ALLOW_LOCAL_RENDER` | Default true. Renders the digest locally when SuperDocs is unavailable. False pauses instead. |

---

## Adding a stage

1. Subclass `BaseNode` in `backend/agents/nodes/`, set `stage` and `running_status`,
   implement `run()`.
2. Add it to `NODE_SEQUENCE` in `backend/agents/graph.py` and to `STAGES` in
   `backend/agents/state.py`.
3. Declare any new state keys in `DigestState`. Do not attach undeclared keys — that
   bug already happened once and is recorded in `PROGRESS.md`.

Checkpointing, resume, retry, cost accounting and decision logging come from the base
class. Raise `NodeSkip` to skip with a stated reason, `NodePause` to suspend without
failing.
