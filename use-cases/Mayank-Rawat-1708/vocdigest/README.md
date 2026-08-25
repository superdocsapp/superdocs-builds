# VocDigest — Voice-of-Customer Digest System

**Mayank Rawat** · SuperDocs Round 2 · difficulty **S2**

Turns a quarter of raw support conversations into a styled, citable digest — pausing for
human review before anything is published.

---

## What it does

Support teams accumulate thousands of conversations a quarter. The signal in them is real,
but nobody has time to read it, so it gets summarised from memory in a meeting and
"customers are complaining about X" becomes an unfalsifiable claim.

VocDigest is for the person who has to write that summary and stand behind it. Give it a
CSV, JSON or TXT export of support conversations and, optionally, last quarter's digest:

- **Themes** clustered on semantic similarity, each carrying the file and line number of
  every conversation supporting it
- **Anonymized verbatim quotes**, showing what was redacted and with what confidence
- **Quarter-over-quarter change** computed from the prior digest, not recalled
- **Charts** inserted into the document via SuperDocs edit operations
- **A human approval gate** that blocks publication until every item has a decision

Rejecting a theme removes that section from the document. The export still succeeds.

---

## SuperDocs surfaces used

| Surface | How |
|---|---|
| **Chat** | One targeted edit per document section rather than a full rewrite, so each section is independently approvable |
| **Human-in-the-loop** | `approval_mode: ask_every_time`, then explicit per-change approval |
| **Export** | DOCX; the free structure read verifies edits landed rather than exporting to check |
| **Multi-document** | Last quarter's digest attached as a read-only reference the editing AI can cite |
| **Search** | That attachment is searchable during editing |
| **Images** | Charts as inline SVG, with a Unicode block-character fallback |

Async chat with `job_id` polling throughout — a headless resumable worker should not depend
on holding an open stream across a process restart.

---

## The five required behaviours

**1. Visible steps.** Every stage reports duration, tokens, cost and SuperDocs operations.
Beyond status, each node writes a *decision log* — why it skipped a stage, why a theme was
marked low-confidence, why an injection attempt was flagged:

```
theme      CLUSTERED           Formed 16 themes from 19 conversations at threshold 0.62
theme      LOW_CONFIDENCE      3 theme(s) have fewer than 3 supporting conversations
anonymize  UNCERTAIN_REDACTION 4 quote(s) contain spans that could not be classified
```

**2. Survives being stopped.** Each node checkpoints to Postgres before and after running.
On restart, completed stages return cached results and call nothing. `test_resume.py` kills a
run mid-theming, restarts, and asserts classify and extract make **zero** new LLM calls.

**3. Human holds the gate.** The run sits at `AWAITING_APPROVAL` until every item is decided.
Quotes whose anonymization was uncertain become their own items so they cannot be skimmed
past. Rejection is scoped — it drops one section, never the run.

**4. Machine-drivable.** Nine MCP tools covering the whole flow *including approval*:
`start_run`, `get_run_status`, `list_approval_items`, `approve_run_items`, `get_cost_report`,
`get_themes`, `export_digest`, `cancel_run`, `list_active_runs`. A full run has been driven
end to end through these alone.

**5. Never bluffs.** Themes under three conversations carry an explicit confidence note
instead of being stated as trends. With no prior digest the document contains **no growth
figures at all** — there is a test asserting the "What Changed" section contains no `%`
character. Unmatched themes are reported as NEW rather than force-matched. Anonymization is
never claimed to be exhaustive.

---

## Four corrections to the task spec

Every SuperDocs endpoint in the brief differed from the published API. Building to the brief
would have 404'd on the first call.

| Brief | Actual |
|---|---|
| `POST /documents` | `POST /v1/documents/upload` |
| `POST /documents/{id}/chat` | `POST /v1/chat` or `/v1/chat/async` |
| `POST /documents/{id}/approve` | `POST /v1/chat/{session_id}/approve` — **session-scoped** |
| `GET /documents/{id}/export` | `POST /v1/documents/export` — POST, returns binary |

**The API is session-centric, not document-centric.** `session_id` is a client-chosen string;
there is no "create session" call. Approvals are scoped to `(session_id, job_id)`. That single
fact reshapes the whole client.

**The "double parse" note is half right.** It applies to the SSE `proposed_change_batch.content`
field, **not** to polling — where `metadata.pending_changes` is already an array and
double-parsing throws.

Two behaviours worth flagging for other integrators:

1. **`approved` is required at the top level** of an approve request even when every entry in
   `changes` carries its own flag. Omitting it returns a generic 422 that reads like a schema
   bug rather than a missing field.
2. **`awaiting_approval` means two different things.** Branch on `metadata.awaiting_kind`:
   `"continue_prompt"` needs `/continue`, anything else needs `/approve`. The wrong endpoint
   returns 409.

Also: `GET /v1/users/me` rejects `sk_` keys, which makes a working key look broken. Verify with
`GET /v1/sessions`, which accepts them and costs no operations.

---

## Bugs found against the live API

Four things no amount of local testing would have surfaced.

**409 `session_busy`, and a wrong error message that cost more than the bug.** Session ids are
deterministic so a resumed run reconnects rather than re-uploading. But a run that fails
mid-edit leaves an *active job* in that session, SuperDocs permits one, and so the retry
collides with its own orphan — permanently. My handler for this existed but never fired,
because `error_code` arrives nested under `detail` and I checked only the top level. So the
error surfaced as "likely the wrong resume endpoint", which sent debugging in entirely the
wrong direction.

Fixed by classifying `session_busy` separately, cancelling unfinished jobs on entry, and
falling back to a fresh session if a job proves uncancellable. **The real cause was
sequencing:** a completed job id does not mean a free session, because approving changes can
leave follow-on work in flight. The stage now waits for the session to clear between sections.

**A section applied twice.** Ordering used `startswith("theme_")` to collect deep dives —
which also catches `theme_table`. Confirmed in live output as a duplicate "Top Themes This
Quarter" heading plus one wasted metered operation. It was the same bug I had already fixed in
the local renderer and had not thought to grep for elsewhere.

**Groq requires the literal word "json"** in the messages when using
`response_format: json_object`. OpenAI imposes no such requirement, so a working prompt returns
`400` here. Every classify call failed.

**A daily token cap turned into three hours of 429s.** Groq states the wait in the *error
message body* ("try again in 20m48s"), not only in a header. I read only the header, capped any
wait at 60s, and retried — per batch, across 25 themes, each independently rediscovering the
same exhausted quota. Fixed with a `Retry-After` parser, a per-day vs per-minute distinction,
and a run-level circuit breaker.

---

## Resilience

Neither service is a hard dependency.

| Failure | Behaviour |
|---|---|
| No Groq key, outage, out of credits | Keyword heuristics for classify, extract, theme naming, prior-digest parsing, summary. **Clustering unaffected** — it is embedding-based. |
| No SuperDocs key, rejected, unreachable | Renders the approved digest locally to DOCX |
| SuperDocs quota exhausted mid-run | Finishes remaining sections locally; applied ones kept |
| Both unavailable | Full pipeline still produces a document |

Two properties matter more than the fallback existing:

**Redaction never silently weakens.** Emails, phones, URLs and identifiers are regex-based and
survive an outage. Only *name* detection is lost, and the quote is then flagged
`name detection not run` so a reviewer knows coverage was reduced rather than assuming a clean
pass meant no names were present.

**The document discloses it.** The methodology section names every degraded stage verbatim.
Silent degradation — output that looks normal but came from word frequency — is exactly the
failure this system exists to prevent.

---

## Quick start

```bash
pip install -r backend/requirements.txt
PYTHONPATH=. pytest backend/tests/ -q      # 78 passed, no API keys needed
./setup.sh                                  # then open localhost:3000
```

`./setup.sh --no-docker` uses SQLite if you would rather not run Postgres.

Sample data included: 200 synthetic conversations for a fictional SaaS company, seeded so
regeneration is byte-identical, plus a prior-quarter digest with deliberately *different* theme
names so comparison exercises semantic matching rather than string equality.

---

## Cost, measured

Live run, 20 conversations resolving into 16 themes:

| | |
|---|---|
| SuperDocs operations | **24** |
| Groq tokens | 11,809 (~$0.008) |
| Wall clock | 1,052s, of which 982s was SuperDocs |

Extrapolating to 200 conversations gives ~240 operations — **about half the free tier's
500/month in one run.** Section count is driven by theme count, so anything inflating theme
count inflates cost.

An earlier estimate of ~34 operations came from mocked calls and was wrong by an order of
magnitude. Recorded in `PROGRESS.md` rather than quietly corrected — an estimate taken from
mocks is not a measurement.

---

## Trade-offs

**Granularity over speed.** One edit per section means four round trips each. Batching would be
far faster and would defeat the approval gate.

**Durability over elegance in resume.** Checkpoints live in Postgres rather than LangGraph's own
checkpointer, because an in-process one does not survive the process being killed — which is the
behaviour being asked for. Cost: resuming replays through completed stages, which no-op.

**Reproducibility over cluster quality.** Clustering is single-pass greedy, not k-means, because
identical input must produce identical clusters — otherwise a resumed run silently diverges from
the run it continues.

**Charts shipped twice.** I could not verify SVG survives a DOCX round-trip, so every chart is
emitted as SVG *and* as Unicode block characters. Redundant, but a chart that silently vanishes
is worse than a plain one.

---

## What breaks

- **Clustering over-fragments with the default embedder.** 20 conversations produce ~16 themes
  where `sentence-transformers` gives ~4. It pulls ~2GB of torch, so it is not a default
  dependency — one `pip install` and one env var.
- **QoQ matching is only as good as the embedding.** With the fallback embedder, matches
  frequently fall below the similarity threshold and themes report as NEW. The failure is in the
  honest direction.
- **Cancellation is not instant.** Effective at the next stage boundary; it cannot interrupt a
  provider call in flight. `MAX_TOKENS_PER_RUN` exists alongside it because a bound on spend
  should not depend on somebody watching.
- **Docker is unverified.** Compose file and Dockerfiles written and syntax-checked, never run —
  no Docker daemon was available in my build environment.

---

## Verified by execution

- **78 tests** passing on SQLite **and** real PostgreSQL 16 with pgvector — no API keys required
- Alembic migrations run and inspected against a live database: genuine `vector` columns, native
  enums, ivfflat cosine index, JSONB
- Full pipeline through the REST API, and separately through MCP tools alone
- **SuperDocs verified live**: 24 operations, structure confirmed, 41 KB DOCX exported
- Sample data regenerates byte-identically

`PROGRESS.md` documents every assumption and **20 bugs found in my own code across five audit
passes**, including which were caught by reasoning and which only by running.

The one I would keep: two rendering bugs survived 70 passing tests because every test asserted
the document was *produced* — none asserted what a reader would see in it. "It rendered" and "it
reads correctly" are different claims, and only the second matters.

---

## Layout

```
backend/
  agents/          LangGraph state, graph, nine nodes
  api/             FastAPI routes (runs, approval gate, health)
  db/              async engine, checkpoint store, migrations
  mcp/             FastMCP server — 9 tools
  models/          SQLAlchemy models, dialect-portable column types
  services/        SuperDocs client, Groq client, anonymizer, charts, vector store
  tests/           78 tests, no keys required
frontend/          React 18 + TypeScript + Tailwind
scripts/           sample data generator, demo server, Groq diagnostics
```

`WRITEUP.md` is the one-page summary · `ARCHITECTURE.md` describes the system diagram ·
`TASK.md` is the operating guide · `PROGRESS.md` is the assumptions and bug log.