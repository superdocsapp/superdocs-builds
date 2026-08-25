# VocDigest — Voice-of-Customer Digest System

Built for the SuperDocs Round 2 engineering task.

Takes a quarter of support conversations, analyses them into themes with volume trends,
anonymizes verbatim quotes, compares against last quarter's digest, and produces a
styled document through the SuperDocs API — pausing for human review before anything is
published.

---

## What It Does

Support teams accumulate thousands of conversations a quarter. The signal in them is
real but nobody has time to read them, so it gets summarised from memory in a meeting
and the resulting "customers are complaining about X" is unfalsifiable. VocDigest turns
that into something traceable: every theme carries the file and line number of every
conversation supporting it, every quote is anonymized with its redactions visible, and
every quarter-over-quarter figure is computed from the prior digest rather than recalled.

The pipeline is nine stages: ingest, classify, extract, cluster, anonymize, compare,
draft, **human gate**, publish. It pauses at the gate and refuses to continue until a
person has accepted or rejected each finding. Rejecting a theme removes it from the
document; the rest still publishes. The same gate is exposed as an MCP tool, so an agent
can drive the whole workflow without touching the UI.

---

## The Five Required Behaviours

**1. Visible steps.** Every stage reports its status, duration, token count and cost to
`GET /runs/{id}`, rendered as a timeline in the UI. Beyond status, each node writes a
*decision log* — why it skipped a stage, why it marked a theme low-confidence, why it
flagged an injection attempt. A real run produces entries like:

```
theme      CLUSTERED           Formed 29 themes from 200 conversations at threshold 0.35
theme      LOW_CONFIDENCE      3 theme(s) have fewer than 3 supporting conversations
anonymize  UNCERTAIN_REDACTION 5 quote(s) contain spans the anonymizer could not classify
```

**2. Survives being stopped.** Each node checkpoints to Postgres before it starts and
after it finishes. On restart the graph re-enters and every completed stage returns its
cached result without re-calling anything. `test_resume.py` proves it: it kills a run
mid-theming, restarts, and asserts classify and extract make *zero* new LLM calls.

**3. Human holds the gate.** `human_gate` writes one `ApprovalItem` per reviewable unit
and raises a pause. The run sits at `AWAITING_APPROVAL` until every item has a decision.
Quotes whose anonymization was uncertain become their own items so they cannot be
skimmed past. Rejection is scoped — it drops one section, never the run.

**4. Machine-drivable.** Seven MCP tools cover the entire flow including approval:
`start_run`, `get_run_status`, `list_approval_items`, `approve_run_items`,
`get_cost_report`, `get_themes`, `export_digest`. A full 200-conversation run has been
driven end to end through these tools alone.

**5. Never bluffs.** Themes with fewer than three supporting conversations carry an
explicit confidence note instead of being stated as trends. With no prior digest the
digest says so and contains no growth figures at all — verified by a test asserting the
"What Changed" section contains no `%` character. When the model returns no verdict for a
record, the record is kept and marked `"model returned no verdict; retained by default"`
rather than silently dropped. Anonymization is never claimed to be exhaustive.

---

## Architecture

```
CSV/JSON/TXT ──> ingest ──> classify ──> extract ──> theme ──> anonymize
                              │            │           │
                        (filters junk, (pgvector    (clusters      ──> compare ──> draft
                         flags injection) embeddings) by meaning)        │           │
                                                              (matches prior     (per-section
                                                               quarter by         instructions)
                                                               similarity)             │
                                                                                       v
   export <── SuperDocs <── [ HUMAN GATE ] <────────────────────────────────────────────
             (upload,        pauses here
              per-section    until every item
              edits,         is decided
              approve,
              export)
```

Every node inherits one base class that makes checkpointing, skip-if-complete, retry
with backoff, cost accounting and decision logging structural rather than something each
node remembers to do.

**Stack:** FastAPI · LangGraph · PostgreSQL + pgvector · SQLAlchemy async · Groq
(llama-3.3-70b) · FastMCP · React 18 + TypeScript + Tailwind.

---

## Quick Start

```bash
./setup.sh
```

Brings up Postgres, installs dependencies, migrates, runs the tests, generates sample
data, and starts the API, MCP server and frontend. Then open http://localhost:3000.

No Docker? `./setup.sh --no-docker` uses SQLite instead — the models are dialect-portable,
so this is a real fallback rather than a degraded mode.

Just want the tests? `./setup.sh --test-only`.

---

## Running Tests

```bash
pytest backend/tests/ -v
```

78 tests, about 8 seconds, **no API keys, no Postgres, no network**. Groq and SuperDocs
are replaced by fakes that mimic the real HITL flow; the database is file-backed SQLite.

To run the same suite against real Postgres and pgvector:

```bash
VOCDIGEST_TEST_DATABASE_URL="postgresql+asyncpg://vocdigest:vocdigest@localhost:5432/vocdigest_test" \
  pytest backend/tests/ -v
```

Worth doing before trusting the similarity-search path: the SQLite fallback computes
distances in Python and therefore cannot catch a broken SQL operator. One such bug was
found exactly this way.

| File | Proves |
|---|---|
| `test_graph.py` | All nine nodes execute in order; run pauses at the gate then completes; every stage checkpoints; a missing prior digest produces no invented figures |
| `test_resume.py` | A killed run resumes from its saved stage and re-runs nothing |
| `test_concurrent.py` | Two runs execute simultaneously with fully isolated state; two executions of the *same* run do not duplicate work |
| `test_injection.py` | Hostile content is flagged as data, never obeyed; the fence cannot be closed early; no system prompt or key-shaped string reaches any output |
| `test_idempotency.py` | A completed stage returns cache with zero LLM calls; identical input produces identical themes *and identical evidence citations* |
| `test_charts.py` | Chart markup is deterministic and HTML-escaped; charts are omitted rather than drawn misleadingly when data is missing |
| `test_stage_control.py` | Retry invalidates downstream stages but preserves upstream; `ingest`/`theme`/`human_gate` cannot be skipped |
| `test_sqlite_checkpoint.py` | The mirror records stages and can reconstruct a run alone; a broken mirror never fails a run |
| `test_local_render.py` | No editor instruction phrasing survives into the rendered document; headings are clean; the theme table is rendered once |
| `test_degraded_mode.py` | Every service-failure path: no Groq, Groq outage, no SuperDocs, quota exhausted, both down. Asserts a digest is still produced, that redaction still runs, and that the document discloses degradation |

---

## Supported Input Formats

**Conversations:** CSV (probes for `text`/`body`/`message`/`content` columns), JSON
(array, or `{"conversations": [...]}`), TXT (one per line).

**Prior digest:** DOCX, TXT, MD, HTML.

---

## Sample Data

```bash
python scripts/generate_sample_data.py
```

200 synthetic conversations for a fictional SaaS company, seeded so regeneration is
byte-identical. Includes names, emails, phone numbers and account IDs so the anonymizer
has real work to do. The Q2 digest deliberately uses *different* theme names
("Data export reliability" vs. what Q3 clustering produces) so comparison exercises
semantic matching rather than string equality.

---

## Cost Per Run

**Measured** on a live run — 20 conversations resolving into 16 themes:

| | |
|---|---|
| SuperDocs operations | **24** |
| Groq tokens | 11,809 |
| Estimated Groq cost | ~$0.008 |
| Wall clock | 1,052s, of which 982s was SuperDocs |

Extrapolating to 200 conversations gives roughly **240 operations — about half the free
tier's 500/month in one run.** Section count is driven by theme count, so anything that
inflates theme count inflates cost; the offline embedder over-fragments, which makes this
worse than it needs to be.

Groq's free tier is **100,000 tokens per day**, and a full run uses ~74,000.

An earlier version of this README estimated ~34 operations. That figure came from mocked
calls and was wrong by an order of magnitude — recorded in `PROGRESS.md` rather than quietly
corrected.

## What I Cut, and Why

- **`sentence-transformers` by default.** It pulls ~2GB of torch. Default is the
  deterministic hash embedder; the real model is one `pip install` away. Clustering
  quality is meaningfully better with it, and the system says which one it used.
- **Alembic in the demo path.** `AUTO_CREATE_TABLES=true` exists for the zero-infra run.
  Migrations own the schema in any real deployment.
- **Auth.** No login. Single-tenant local tool.
- **Live SuperDocs verification.** Not a choice — see below.

---

## Controlling Spend

Every run on one API key draws from the same provider allowance, so a forgotten run can
exhaust it and make unrelated work look broken. Three things address that:

- **`POST /runs/{id}/cancel`** — stops a run at the next stage boundary, keeping completed
  stages. Also `cancel_run` over MCP, and a Cancel button on the run page.
- **`MAX_TOKENS_PER_RUN`** (default 40,000) — a hard ceiling per run. Exceeding it degrades
  the remaining stages to heuristics instead of continuing to spend. This is the one that
  works when nobody is watching.
- **`GET /runs/active/summary`** — which runs are spending right now and how much. The
  dashboard warns when more than one is active.

Groq's free tier is **100,000 tokens per day**. A full 200-conversation run uses ~25,000.

---

## Performance Note

The anonymizer originally made one LLM call per quote, sequentially — ~144 round trips on
a 200-conversation run, and most of the token spend. Now it pre-screens for name-shaped
tokens (most quotes have none and skip the model entirely), batches one call per theme,
and runs four themes concurrently. Net: at most 48 calls instead of 144, most skipped.

Tuned with `ANONYMIZE_CONCURRENCY` (default 4) — low enough not to trip a free-tier rate
limit, since 429 backoff costs more than the parallelism saves.

---

## What Breaks

- **Cold-start clustering quality with the hash embedder.** 200 conversations that
  should form ~6 themes produce ~29, because the hash embedder is not semantically
  trained. Install `sentence-transformers` for real results. The threshold is tunable
  (`CLUSTER_THRESHOLD`) but no threshold fixes a weak embedding space.
- **Resume replays no-op stages.** LangGraph restarts at the entry point, so resuming a
  run paused at the gate walks eight nodes that each hit their checkpoint and return
  immediately. Correct, but eight database round-trips to reach the pause point.
- **`EMBEDDING_DIM` changes need a migration.** The pgvector column width is fixed at
  migration time; changing the setting alone produces a confusing insert error.
- **QoQ matching is only as good as the embedding.** With the hash embedder, matches
  frequently fall below the 0.55 similarity threshold and every theme is reported as NEW.
  Install `sentence-transformers` for real matching. The failure is in the honest
  direction — an unmatched theme is reported as new rather than force-matched to a prior
  theme it does not correspond to.
- **Anonymization is not guaranteed.** Two passes and an explicit uncertainty marker do
  not equal a promise. The human gate is the control, and the digest's methodology
  section says exactly that.
- **Cancellation is not instant.** `POST /runs/{id}/cancel` takes effect at the next
  stage boundary; it cannot interrupt a provider call already in flight. That is why
  `MAX_TOKENS_PER_RUN` exists alongside it — a bound on spend should not depend on
  somebody watching.
- **No live SuperDocs verification.** See below.

---

## Groq Notes

**The free tier is 100,000 tokens per day.** A full 200-conversation run uses ~25,000, so
roughly four runs daily. Once spent, every call returns 429 until the window resets.

The client handles this specifically, because a per-day limit and a per-minute limit need
opposite responses:

- **Per-minute burst** → waited out and retried, using the delay Groq states
- **Per-day allowance** → fails immediately and trips a run-level circuit breaker, so no
  further call is attempted. The run completes on heuristics and the digest says so.

Groq states the wait in the **error message body** ("try again in 20m48.48s"), not only in
a `Retry-After` header — reading only the header, capping the wait at 60s, and retrying is
what turned a 40-conversation run into three hours of 429s during testing. Documented in
`PROGRESS.md` under the 2026-08-14 entry.

**Models get retired without warning.** `llama-3.3-70b-versatile` returned 404
`model_not_found` mid-session, having worked an hour earlier. `GROQ_MODEL` is an env var for
this reason — a provider retiring a model should not require a code change. Verify a
candidate with a *realistic* prompt: `qwen/qwen3.6-27b` is listed and accepts requests but
cannot reliably honour `json_object` mode, so "exists" and "works" are different checks.

**Groq requires the literal word "json" in the messages when using
`response_format: {"type": "json_object"}.** OpenAI does not. A prompt that works against
OpenAI returns `400 "'messages' must contain the word 'json' in some form"` on Groq.

Found on the first live call, where it failed every `classify` request. `GroqClient` now
guarantees the word is present at the point json mode is enabled, and the prompts state it
themselves as well. Two regression tests capture the outgoing request body to assert it.

---

## SuperDocs Notes

I could not reach `docs.superdocs.app` from my build environment and worked from the
documentation supplied to me. Four things in the task brief disagreed with it, and
building to the brief would have failed on the first call:

| Task brief | Actual API |
|---|---|
| `POST /documents` | `POST /v1/documents/upload` |
| `POST /documents/{id}/chat` | `POST /v1/chat` or `/v1/chat/async` |
| `POST /documents/{id}/approve` | `POST /v1/chat/{session_id}/approve` — **session-scoped** |
| `GET /documents/{id}/export` | `POST /v1/documents/export` — **POST, returns binary** |

The brief also says proposed-change content always needs a second JSON parse. That is
true of the **SSE** `proposed_change_batch.content` field, but **not** of the polling
path, where `metadata.pending_changes` is already an array — double-parsing it throws.
This backend polls, so it does not second-parse, and the client documents both.

Two API behaviours worth flagging for anyone else integrating:

1. `approved` is required at the **top level** of an approve request even when every
   entry in `changes` carries its own flag. Omitting it returns a generic 422 that reads
   like a schema bug rather than a missing field.
2. `awaiting_approval` means two different things. Branch on `metadata.awaiting_kind`:
   `"continue_prompt"` needs `/continue`, anything else needs `/approve`. The wrong
   endpoint returns 409. The client exposes these as separate properties so a caller
   cannot conflate them.

Also: `GET /v1/users/me` rejects `sk_` keys, which makes a working key look broken.
Key verification uses `GET /v1/sessions`, which accepts them and costs no operations.

**Live-key findings.** The integration has now been run against a real key, which
immediately surfaced something no amount of local testing would have:

**409 `session_busy`.** Session ids are deterministic so a resumed run reconnects instead
of re-uploading. But a run that fails mid-edit leaves an *active job* in that session, and
SuperDocs allows only one — so the retry collides with its own orphan and the run can never
be retried. Fixed by classifying `session_busy` separately from the wrong-endpoint 409,
cancelling unfinished jobs on entry, and falling back to a fresh session if a job proves
uncancellable. The API's error body suggested exactly this remediation; I had implemented
neither half of it.

**The full happy path has now completed against a live key**: 24 operations, document
structure verified, 41 KB DOCX exported. That immediately exposed one more bug — the section
ordering matched `startswith("theme_")`, which also catches `theme_table`, so that section was
applied twice and produced a duplicate heading in the real document. It was the same bug I had
already fixed in the local renderer and had not thought to grep for elsewhere. Every integration behaviour
is verified against a fake I wrote from the documentation. The fake encodes my *reading*
of the API — if I misread something, the tests confirm the misreading rather than
catching it. First contact with a real key is still the real test.

Two bugs found by finally running things for real rather than reasoning about them are
worth noting, because both were invisible to static analysis and to a passing test suite:

1. **Alembic reported success and created nothing.** Under SQLAlchemy 2.0 async,
   `connect()` opens an implicit transaction that is rolled back unless committed. The
   migration printed `Running upgrade -> 0001` and left the database empty. A silent
   no-op that looks like a working migration.
2. **`VectorType` silently lost every pgvector operator.** A `TypeDecorator` does not
   inherit the wrapped type's comparators, so `cosine_distance` raised `AttributeError`
   on Postgres — invisible on SQLite, which computes distances in Python.

Both are fixed and covered. They are the reason the "verified by execution" list below
exists separately from the test count.

---

## Verified by Execution

- 78 tests pass on SQLite **and** on real PostgreSQL 16 with pgvector
- The Groq integration against the **live API** (one bug found and fixed, see Groq Notes)
- The full pipeline with **no Groq key and no SuperDocs key**, producing a 43 KB DOCX
- `alembic upgrade head` against real Postgres, with the result inspected: `embedding`
  columns are genuine `vector` type, four native enums exist, the ivfflat cosine index is
  present, JSONB columns are JSONB. `downgrade base` cleanly reverses it.
- Full 200-conversation pipeline on real Postgres, including a genuine pgvector cosine
  search
- Full pipeline through the REST API and separately through MCP tools, both with items
  rejected at the gate and the export still produced
- The SQLite checkpoint mirror read back independently of the application
- Sample data regenerates byte-identically

**Not verified:** the live SuperDocs API, `docker compose up` (no Docker daemon
available in the build environment), and the frontend against a live backend.

---

## Project Layout

```
backend/
  agents/          LangGraph state, graph, and the nine nodes
  api/             FastAPI routes (runs, approval gate, health)
  db/              async engine, checkpoint store, Alembic migrations
  mcp/             FastMCP server — 7 tools
  models/          SQLAlchemy models + dialect-portable column types
  services/        SuperDocs client, Groq client, anonymizer, vector store
  tests/           18 tests, no keys required
frontend/          React 18 + TypeScript + Tailwind
scripts/           sample data generator, demo server
```

`PROGRESS.md` is the assumptions log — every guess, every spec correction, and a
self-audit of the bugs I found in my own architecture. `TASK.md` is the operating guide.