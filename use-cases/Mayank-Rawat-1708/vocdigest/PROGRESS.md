# Assumptions Log

Every non-obvious decision, every place the task spec disagreed with the SuperDocs API,
and every guess that could be wrong. Written as it happened, not reconstructed.

---

## 2026-08-08 — Correction: the task spec's SuperDocs endpoints were wrong

**Assumed:** the endpoints given in the task brief were authoritative.

**Found:** they are not. Every one of the four differs from the published API.

| Task brief | Actual API |
|---|---|
| `POST /documents` | `POST /v1/documents/upload` (multipart) or `/v1/documents/upload-base64` |
| `POST /documents/{id}/chat` | `POST /v1/chat` (sync) or `POST /v1/chat/async` (returns `job_id`) |
| `POST /documents/{id}/approve` | `POST /v1/chat/{session_id}/approve` |
| `GET /documents/{id}/export` | `POST /v1/documents/export` (POST; returns binary) |

**Impact if I had followed the brief:** 404 on every call. The whole integration is
built against the documented API instead.

---

## 2026-08-08 — Correction: SuperDocs is session-centric, not document-centric

**Found:** `session_id` is a client-chosen string. There is no "create session" call —
a session springs into existence the first time you use its id. Approvals are scoped to
`(session_id, job_id)`, not to a document.

**Decision:** derive the session id deterministically as `vocdigest-{run_id}`. That
makes resume free: a resumed run reconnects to the same session rather than starting a
new one and re-uploading.

**Impact if wrong:** if session ids turn out to be server-issued rather than
client-chosen, `superdocs.py` needs to store the returned id instead of deriving it.
Contained to one node.

---

## 2026-08-08 — Correction: the "double parse" applies to SSE only

**Brief said:** proposed-change content always arrives JSON-encoded and needs a second
parse; missing it is the top cause of empty diff cards.

**Found:** true for the SSE `proposed_change_batch` event, whose `content` field is a
JSON string. **Not** true for the polling path — `job.metadata.pending_changes` is
already an array of objects. Double-parsing it raises `TypeError`.

**Decision:** the backend uses polling exclusively (headless, resumable, survives a
process restart in a way an open SSE stream does not). `poll_until_settled` therefore
does *not* second-parse. The SSE quirk is documented in the client docstring for anyone
who later adds a streaming path.

**Impact if wrong:** if polling ever starts returning stringified content, one `loads`
in `poll_until_settled` fixes it.

---

## 2026-08-08 — `approved` is required at the top level of an approve request

**Found:** the field is mandatory even when every entry in `changes` carries its own
`approved` flag. Omitting it returns a generic 422 that reads like a schema mismatch
rather than a missing field.

**Decision:** `approve_changes()` always sends `"approved": true` at the top level and
per-change flags underneath. Documented inline so nobody "cleans up" the redundancy.

---

## 2026-08-08 — `awaiting_approval` has two distinct meanings

**Found:** a job pauses with `status == "awaiting_approval"` both when changes need
review and when a large edit asks whether to continue. They need different endpoints
(`/approve` vs `/continue`); calling the wrong one returns 409.

**Decision:** `poll_until_settled` branches on `metadata.awaiting_kind` and returns an
`EditResult` exposing `awaiting_approval` and `awaiting_continue` as separate
properties, so a caller physically cannot conflate them. 409 is classified as
non-retryable — retrying a wrong-endpoint call just repeats the mistake.

---

## 2026-08-08 — Groq has no embeddings API

**Assumed initially:** Groq would cover both analysis and embeddings.

**Found:** Groq serves chat completions only. The spec's `vector(1536)` column implies
OpenAI dimensions, but nothing in the stack produces them.

**Decision:** embeddings run locally via `sentence-transformers/all-MiniLM-L6-v2`
(384-dim, free, no key, deterministic). `EMBEDDING_DIM` is settings-driven and
`get_embedder()` fails loudly on a model/column dimension mismatch rather than letting
pgvector throw an opaque insert error.

A second `hash` backend produces deterministic offline vectors so the test suite never
downloads model weights or touches the network. It is not semantically trained, but it
reliably scores near-identical text higher than unrelated text — enough to exercise
clustering and QoQ matching in tests.

**Impact if wrong:** swapping to a hosted embedding provider means one new `Embedder`
subclass and an `EMBEDDING_DIM` change plus a migration.

---

## 2026-08-08 — No search endpoint for loading last quarter's digest

**Brief said:** "Load last quarter's digest document via SuperDocs search endpoint."

**Found:** no such endpoint. Retrieval is done through natural-language chat, or by
uploading a file as an attachment the AI can reference.

**Decision:** two-track. (1) We parse the prior digest ourselves (`python-docx` for
.docx, plain read for text formats) and extract themes with Groq, because the QoQ
numbers must be *computed* from data rather than recalled by a model. (2) We *also*
upload it as a SuperDocs attachment so the editing AI can cite it if an instruction
references it.

**Impact if wrong:** none — track (1) is self-sufficient; the attachment is additive and
its failure is caught and logged as non-fatal.

---

## 2026-08-08 — `GET /v1/users/me` rejects API keys

**Found:** the natural key-verification endpoint 401s on `sk_` keys. `GET /v1/sessions`
accepts them and consumes no operations.

**Decision:** `verify_key()` uses `/v1/sessions`. Prevents a working key looking broken.

---

## 2026-08-08 — Two kinds of 429 need opposite handling

**Found:** an application 429 (JSON body + `Retry-After`) means the monthly operation
quota is exhausted — retrying inside the window is pointless. An infrastructure 429
(plain text, no `Retry-After`) is a transient surge and *should* be retried.

**Decision:** `_classify_error` distinguishes them by whether the body parses as JSON.
Quota → `SuperDocsQuotaError`, non-retryable, pauses the run with an actionable message.
Surge → retryable with backoff.

**Impact if wrong:** a misclassified quota error wastes three retries before pausing.
Non-destructive.

---

## 2026-08-08 — Clustering must be deterministic, so greedy over k-means

**Assumed:** any reasonable clustering algorithm would do.

**Realised:** the idempotency requirement means the same input must produce the same
clusters on a rerun, otherwise a resumed run silently diverges from the run it is
continuing. k-means with random init breaks that.

**Decision:** single-pass greedy assignment against running centroids, over
id-sorted input. Verified deterministic across repeated runs.

**Impact if wrong:** cluster quality is lower than k-means on some distributions. Traded
knowingly for reproducibility.

---

## 2026-08-08 — Cluster threshold is model-dependent

**Assumed:** one similarity threshold would suit any embedder.

**Found:** MiniLM and the hash embedder score on different scales — 0.62 is sensible for
MiniLM, far too high for the hash backend.

**Decision:** `CLUSTER_THRESHOLD = 0.62` as the MiniLM default, but `ThemeNode` accepts
an override so tests pass a threshold appropriate to the hash embedder rather than
depending on the production constant.

---

## 2026-08-08 — Irrelevant conversations are kept, not deleted

**Decision:** `classify_node` marks non-support content `is_relevant=False` instead of
removing the row.

**Reason:** the digest's methodology section states how many inputs were excluded and
why. Deleting them would make that number unverifiable.

---

## 2026-08-08 — Themes under 3 conversations get a confidence note, not silence

**Decision:** any theme with fewer than 3 supporting conversations carries a
`confidence_note` and is rendered with a caveat rather than asserted as a trend.

**Reason:** the "never bluffs" requirement. Three is the smallest count where calling
something a pattern is arguably honest. The number is a judgement call and is exposed as
`MIN_CONFIDENT_VOLUME`.

---

## 2026-08-08 — Anonymization uncertainty is surfaced, never resolved silently

**Decision:** LLM-proposed spans at ≥0.85 confidence become `[USER]`/`[COMPANY]`.
Anything below becomes `[POSSIBLE-NAME]` and creates an approval item.

**Reason:** the brief forbids promising guaranteed PII removal. Silently redacting a
low-confidence span hides a decision; silently passing it risks a leak. Surfacing it
makes the human the control, which is what we actually claim.

**Impact if wrong:** threshold too high → more review burden. Too low → quiet
over-redaction. 0.85 is a guess and is a single constant.

---

## 2026-08-08 — Injection detection runs regex *and* LLM

**Decision:** a regex pre-pass flags known injection phrasings independently of the
model, in addition to asking the model to report them.

**Reason:** relying on the model to self-report attacks against itself is circular. The
regex is not comprehensive and is not claimed to be — it is a floor, not a guarantee.

---

## 2026-08-08 — A rejected section removes content; it does not abort the digest

**Decision:** rejecting a gate item drops its section from `draft_sections`. Export runs
on whatever survives.

**Reason:** explicit requirement ("export always works even if some approval items were
rejected"). Implemented by keying each approval item to a `section_key`.

---

## 2026-08-08 — Compare node is non-fatal

**Decision:** `CompareNode.fatal_on_error = False`, and every failure path raises
`NodeSkip` with an explicit note.

**Reason:** a missing or unreadable prior digest degrades the digest but does not
invalidate this quarter's analysis. The document then states plainly that no comparison
is available rather than implying every theme is new.

---

## 2026-08-08 — Timeout is a pause, not a failure

**Decision:** `SuperDocsTimeout` carries the `job_id`, and `superdocs_node` stores it on
the run before pausing.

**Reason:** the docs are explicit that a long operation may still be running server-side.
Marking the run FAILED would discard completed sections and burn quota re-doing them.

---

## Open questions I could not resolve from the docs

1. **Does `POST /v1/documents/export` export the whole session or one document?** The
   client sends `session_id` and assumes the session's active document. In a
   multi-document session this may need an explicit `document_id`.
2. **Exact `usage.ops_charged` semantics per chat turn.** The cost report counts
   `max(ops_charged, 1)` per edit, which may over-report if a turn charges zero.
3. **Whether `data-chunk-id` attributes survive a `.docx` round-trip.** The docs require
   preserving them; not yet verified against a real export.
4. **Attachment size and count limits per session.** Not stated; the prior-digest
   attachment failure path is caught and treated as non-fatal for this reason.

---

## 2026-08-08 — Self-audit: anomalies found in my own architecture and fixed

Parsing clean is not the same as being sound. An audit pass found seven real problems in
what I had built. All are fixed; the reasoning is recorded because several were the kind
that only bite under load or on resume.

### 1. Check-then-act race in the node base class (the serious one)

`BaseNode.__call__` read "is this stage complete?" in one transaction and wrote "I am
running it" in a second. Two workers processing the same run could both pass the read
before either wrote, and both would execute the stage — duplicating LLM spend and, worse,
duplicating SuperDocs operations against a metered quota.

**Fixed** by `claim_stage()`, which takes the row lock first and performs the read and
the claim inside one transaction. `is_stage_complete()` remains for direct use in tests
but no production path uses it.

Note this only ever affected two workers on the *same* run. Different run ids never
contend, because the lock is per-row.

### 2. Stale error state survived recovery

A non-fatal stage (`compare`) sets `state["error"]` and continues. Nothing cleared it, so
a run that recovered and completed still reported an error to the API and the UI.

**Fixed:** a node that succeeds clears an error left by a *different* stage.

### 3. `disappeared_themes` was passed between nodes untyped

`compare_node` wrote it and `draft_node` read it, but it was never declared in
`DigestState` — both sides carried a `# type: ignore` to silence the checker. A rename on
either side would have failed silently at runtime.

**Fixed:** declared in the TypedDict and initialised in `build_initial_state`. Both
escapes removed.

### 4. Seven packages had no `__init__.py`

`backend/`, `backend/agents/`, `backend/services/` and others relied on namespace
packages. It imports today, but pytest collection and some tooling handle it
inconsistently.

**Fixed:** markers added.

### 5. `create_run` wrote state keyed to a throwaway UUID

The row was constructed with `build_initial_state(uuid.uuid4(), ...)` and then
overwritten with the real id after flush. Between those two statements `checkpoint_data`
referenced a run that did not exist.

**Fixed:** insert first, flush, then build state once against the real id.

### 6. Dead code in the SuperDocs node

`first_key` was computed and never used, left from an earlier ordering approach.

**Fixed:** removed. `ruff check --select F,E9` is now clean across the backend.

### 7. The cluster threshold override was unreachable

`ThemeNode.__init__` accepted `cluster_threshold`, but `build_graph()` constructs every
node with no arguments, so production always got the module constant. Tests could
override it; a deployment could not.

**Fixed:** the default now comes from `settings.cluster_threshold` (env-tunable), with
the constructor argument still winning.

---

## Anomalies I have NOT fixed, and why

**Resume replays through completed stages.** LangGraph's `ainvoke` restarts at the entry
point, so resuming a run paused at `human_gate` walks through eight nodes that each hit
their checkpoint and no-op. It is correct but costs eight database round-trips to reach
the pause point.

The tidy fix is LangGraph's own checkpointer with `interrupt()`, which resumes at the
actual node. I did not use it because an in-process checkpointer does not survive the
process being killed, which is the behaviour being asked for. The two mechanisms overlap
and the current design privileges durability over elegance. Worth revisiting.

**`Vector(settings.embedding_dim)` is evaluated at import time.** The column width is
frozen when the model module loads, so changing `EMBEDDING_DIM` needs both a migration
and a restart, and a mismatch between them surfaces as a pgvector insert error rather
than a clear message. `get_embedder()` catches the common case (model dimension vs
setting) but not setting vs already-migrated column.

**`NodePause` escaping `graph.ainvoke()` is unverified.** `execute_run` catches it, but I
have not confirmed LangGraph propagates a custom exception unwrapped in every version.
If it wraps, the pause is misreported as a failure. This needs a real run to settle.

**Nothing has been executed end to end.** No API key, no Postgres, no live SuperDocs
call. Everything above is static analysis, import checks, graph compilation, and unit
reasoning about the code. The integration is written against the documented API, not
against observed behaviour, and that distinction should be assumed until a real run
proves otherwise.

---

## 2026-08-09 — Session 2: tests, sample data, API, MCP, frontend

### Models made dialect-portable so tests need no infrastructure

**Problem:** the models imported `pgvector.sqlalchemy.Vector` and `JSONB` directly, so
the schema only existed on Postgres. Running the suite meant running a database server.

**Decision:** added `backend/models/types.py` with a `VectorType` `TypeDecorator` that
resolves to real pgvector on Postgres and JSON-encoded text on SQLite, plus
`JSON().with_variant(JSONB(), "postgresql")` and the equivalent for UUIDs.

This is not a test hack — it is the reason `pytest` needs nothing but Python. Similarity
search in SQL remains Postgres-only; on SQLite the caller computes it in Python.

### Bugs the tests found in code I had already written

These would all have shipped silently. Listing them because the audit in the previous
session clearly did not catch everything, and pretending otherwise would be dishonest.

**1. Checkpoints were storing nothing.** `BaseNode.__call__` computed its state delta as
`self._delta(state, new_state)` — but nodes mutate state in place and return the same
object, so this diffed the dict against itself and always produced `{}`. Every
checkpoint recorded an empty delta, meaning resume would have silently lost all state.
Fixed by snapshotting `before = dict(state)` prior to calling `run()`.

This is the single worst bug in the project so far. It was invisible to static analysis,
invisible to a passing import, and only surfaced because a test asserted on a value that
had to survive a restart.

**2. Clustering was not reproducible across runs.** `theme.py` sorted conversations by
`c.id` "so the result is stable across runs". Row ids are random UUIDs generated per run,
so the sort order differed between two runs over identical input, and greedy clustering
is order-sensitive. Themes matched by name and volume but cited *different source lines*.
Fixed by ordering on `(source_file, source_line)` — the input's natural key.

Caught only because `test_idempotency` compared evidence citations rather than stopping
at theme names and counts.

**3. The credential scrubber missed real keys.** The pattern `\b(sk|lce|gsk)_[A-Za-z0-9]{8,}`
requires 8+ alphanumerics immediately after the prefix, so it stopped dead at the second
underscore in `sk_live_abcdef1234567890` — which is the format Stripe-style keys actually
use. Widened to allow `_` and `-` in the body. Same flaw existed in the SuperDocs
client's redactor and was fixed there too.

**4. The concurrency test was passing for the wrong reason.** The fixture used
`:memory:` with a `StaticPool`, which forces every session onto one shared connection.
That serialises the work the test claims to run in parallel — it was testing a single
connection, not isolated runs. Switched to a file-backed SQLite database with WAL and a
busy timeout so sessions get genuinely independent connections. The test then failed,
correctly, and passed once the underlying behaviour was right.

**5. `init_db` ran `CREATE EXTENSION vector` unconditionally**, producing a hard error on
SQLite even though the models were portable by then. Now dialect-aware.

**6. The client-patching fixture missed a module.** It hardcoded a list of import sites
and omitted `backend.agents.nodes.anonymize`, so the first full-graph test tried to reach
the real Groq. Replaced with a walk over `sys.modules` that patches every binding
pointing at the real class, plus an assertion that at least one was patched — a fixture
that silently patches nothing is worse than one that fails.

**7. A bug in my own test fake.** The classification fake bounded each record with a
fixed 400-character window, which bled into the following record and mis-attributed an
injection attempt to a benign conversation. Now bounded at the next marker. Worth
recording because a wrong fake produces confident wrong test results.

### Sample data

200 synthetic conversations, seeded (`SEED = 20260808`) and verified byte-identical on
regeneration. Names, emails, phones and account IDs are embedded so the anonymizer has
genuine work. The Q2 digest uses deliberately different theme names so QoQ matching
exercises semantic similarity rather than string equality.

### API and MCP

15 HTTP endpoints, 7 MCP tools. Both drive the full pipeline; a complete
200-conversation run has been executed end to end through each, including rejecting
items at the gate and confirming the export still succeeds.

`/health/ready` reports credentials as booleans only. Returning even a masked prefix
would put key material into logs and browser history for no diagnostic benefit.

### Verified end to end (with mocked external services)

- 18 tests, ~3s, no keys, no Postgres, no network
- Full run over 200 conversations through the **REST API**: 29 themes, 38 approval items,
  2 rejected, `COMPLETE`, export downloaded
- Full run through **MCP tools** alone: same flow, 1 theme rejected, export produced
- Sample data regeneration is byte-identical
- Frontend typechecks and builds (207 KB, 64 KB gzipped)

### Still not verified

**Nothing has touched the live SuperDocs API.** Every integration behaviour is asserted
against a fake I wrote from the documentation. The fake encodes my reading of the API —
where I misread it, the tests confirm the misreading rather than catching it. This is the
largest remaining risk in the project and no amount of local testing reduces it.

Also unverified: the frontend against a live backend (it builds and typechecks, but I
have not clicked through it), Alembic migrations against a real Postgres instance, and
the Docker stack end to end.

### Open questions still unresolved

Carried forward from session 1, none answered by further reading:

1. Does `POST /v1/documents/export` need an explicit `document_id` in a multi-document
   session, or does it always export the session's active document?
2. Exact `usage.ops_charged` semantics per turn. The cost report counts
   `max(ops_charged, 1)`, which over-reports if a turn legitimately charges zero.
3. Whether `data-chunk-id` attributes survive a DOCX export round-trip.
4. Attachment size and count limits per session.

---

## 2026-08-09 — Session 3: closing every gap

Everything previously listed as cut or unverified is now built and, where possible,
actually executed rather than reasoned about.

### Charts — built (was the largest cut)

`backend/services/charts.py` renders three charts: volume by theme, prior-vs-current
comparison, and fastest-growing issues. Each is emitted **twice**: as inline SVG and as
a Unicode block-character version wrapped in `<pre>`.

**Why both.** I could not verify how SVG survives a DOCX export round-trip, and a chart
that silently vanishes on export is worse than one that is merely plain. The block
version renders in every format SuperDocs offers, including plain text and Markdown.
Emitting both means whichever survives is present.

Dependency-free and deterministic, so charts cannot break idempotency — a resumed run
sends byte-identical instructions to the run it continues. Theme names are HTML-escaped
before entering SVG, because a theme name is untrusted text that arrived from customer
data.

Charts are **omitted rather than drawn** when the data does not support them: a theme
with no prior-quarter match is excluded from the comparison chart instead of plotted
against zero, which would convert "no comparison data" into "this went from nothing".

### Models split into per-entity modules

`run.py`, `conversation.py`, `theme.py`, `approval.py`, plus `base.py` for the
declarative base, enums and portable column types. The entities have mutual
relationships, so a direct import between them would cycle — `base.py` is what breaks it.
`__init__.py` imports in dependency order (Theme before Conversation, which has a foreign
key to it) and re-exports everything, so no existing import path changed.

### SQLite checkpoint mirror — built

`backend/db/sqlite_checkpoint.py`, using aiosqlite as the stack specified. Enabled with
`CHECKPOINT_SQLITE_PATH`.

**Postgres remains authoritative and this is write-behind.** Making SQLite the sole
checkpoint store would put a run's status and its checkpoint in two databases with no
shared transaction, so a crash between the two writes would leave them disagreeing —
precisely the failure the checkpoint exists to prevent. The mirror runs after the
authoritative commit and never raises: a mirror failure is logged and the run continues,
because progress has genuinely been made by that point. There is a test for exactly that,
pointing the mirror at an unwritable path and asserting the run still reaches the gate.

Verified by reading the resulting file back with the `sqlite3` module independently of
the application, and by reconstructing a run's completed-stage list from the file alone.

### Per-stage retry and skip — built

`POST /runs/{id}/stages/retry` clears one stage's checkpoint **and every stage after it**,
because downstream results were computed from output that is about to be replaced;
keeping them would mix generations. Upstream checkpoints survive, so a retry costs one
stage rather than a pipeline.

`POST /runs/{id}/stages/skip` refuses `ingest`, `theme` and `human_gate` with a 409.
Skipping ingest leaves no data, skipping theme leaves nothing to report, and skipping the
gate publishes unreviewed content — which is the single thing this system exists to
prevent. Operator skips are written to the decision log as `SKIPPED_BY_OPERATOR` so they
are attributable rather than silent.

### Frontend polling order corrected

Now polls first at 3s and upgrades to SSE once the stream delivers its first event,
matching the specified behaviour. Previously it was SSE-first with a polling fallback.
The specified order is better: the view populates immediately, and an SSE stream that
connects but silently buffers — which some proxies do, and which is indistinguishable
from a hung backend — degrades to a working poll instead of a frozen page.

---

## Bugs found by finally running things for real

### Alembic reported success and created nothing

`alembic upgrade head` printed `Running upgrade -> 0001` with no error and left the
database completely empty.

Under SQLAlchemy 2.0 async, `connectable.connect()` opens an implicit transaction that is
**rolled back** when the context exits unless committed. The official async template
omits the commit and appears to work in some configurations. Adding
`await connection.commit()` after `run_sync` fixed it.

A silent no-op that looks like a successful migration is about the worst failure mode
available, and no amount of static analysis would have found it. It was only visible
because I ran the migration and then looked at `\dt`.

### VectorType silently lost every pgvector operator

`Theme.embedding.cosine_distance(v)` raised `AttributeError` at query-build time on
Postgres. A `TypeDecorator` does not inherit the wrapped type's comparators, and I had
defined `cosine_distance` as an ordinary method on the type rather than on a
`comparator_factory`.

Invisible on SQLite, because that path computes distances in Python and never touches the
SQL operator. Fixed with a proper `Comparator` emitting `<=>`, `<->` and `<#>` as raw
operators, and `find_similar_themes` is now explicitly dialect-aware: SQL-side sort and
limit on Postgres, Python-side on SQLite.

### Two tests were broken against Postgres and passing on SQLite

`fastapi.testclient.TestClient` runs the app in its own event loop via a portal thread.
An asyncpg connection created in the pytest loop cannot be used from another one and
fails with "another operation is in progress". aiosqlite tolerates it, so the tests
passed on SQLite and broke the moment a real database was used.

Replaced with an `httpx.AsyncClient` over `ASGITransport`, which shares the test's loop.
Added as an `api_client` fixture so future API tests cannot reintroduce it.

### aiosqlite connections cannot be re-entered

`async with await _connect() as conn` started the connection's worker thread twice and
raised `RuntimeError: threads can only be started once`. Replaced with a proper
`@asynccontextmanager` that opens and always closes.

---

## Now verified by execution, not reasoning

- **35 tests pass on SQLite and on real Postgres 16 with pgvector.** Set
  `VOCDIGEST_TEST_DATABASE_URL` to run against Postgres — worth doing before trusting
  the similarity-search path, since the SQLite fallback cannot catch a broken SQL
  operator.
- **`alembic upgrade head` against real Postgres**, verified by inspecting the result:
  `embedding` columns are genuine `vector` type (not text), four native enums exist, the
  ivfflat cosine index is present, JSONB columns are JSONB. `alembic downgrade base`
  cleanly removes everything.
- **Full 200-conversation pipeline on real Postgres**, including a genuine pgvector
  cosine search returning 1.0 for a theme against itself and lower scores for others.
- **The SQLite mirror read back independently** of the application.
- Full pipeline through the REST API and through MCP tools, both with items rejected at
  the gate and the export still produced.

## Still not verified

**The live SuperDocs API.** Unchanged and unchangeable from here: every integration
behaviour is asserted against a fake written from the documentation, so where I misread
the docs the tests confirm the misreading. This remains the largest risk in the project.

**Docker.** No Docker daemon is available in this environment, so `docker compose up` has
never been executed. The compose file and both Dockerfiles are written and
syntax-checked, but treat the first `docker compose up` as unproven.

**The frontend against a live backend.** It typechecks and builds; I have not clicked
through it.

---

## 2026-08-09 — Session 4: fallbacks for unavailable APIs

Prompted by a direct question: what happens if a key is missing, rejected, or out of
credits. I tested rather than assumed, and found two real gaps.

### Gap 1 — a missing key retried three times, then killed the run

`MissingCredentialError` fell through `BaseNode`'s generic exception handler, so a
missing `GROQ_API_KEY` was retried three times with backoff and then marked the run
FAILED — discarding every completed stage.

A key does not appear between retry attempts. It now pauses immediately, naming the
variable to set, and completed stages survive so the run resumes once it is supplied.

### Gap 2 — there was no degraded mode at all

Without Groq the run simply died at classify, even though most of the pipeline does not
actually need a language model. Clustering is embedding-based. Redaction of emails,
phones and identifiers is regex. Theme naming and the summary already had fallbacks that
were only reachable on an exception, not on absence.

**`backend/services/heuristics.py`** now provides LLM-free classify, extract, cluster
naming, prior-digest parsing and summary. **`backend/services/llm_gate.py`** is the
single decision point: one policy for "can we use the model, and what if not", rather
than each node inventing its own.

The gate distinguishes *unavailability* from *bad output*. A missing key, an outage or
exhausted credits falls back. A `GroqError` from malformed JSON is re-raised so the
node's normal retry handles it — silently degrading on a transient parse failure would
quietly lower quality for a problem that would have fixed itself.

### Gap 3 — no digest at all without SuperDocs

Every analysis stage could complete and be human-approved, and the run would still die
at the last step over a service the *content* does not depend on.

**`backend/services/local_render.py`** renders the same approved sections to DOCX
(Markdown when python-docx is absent). It strips the "tell the editor to do X" framing
from each section, converts markdown tables to real Word tables, and uses the
block-character form of each chart — python-docx cannot embed SVG, and a chart the reader
can see beats a broken placeholder.

Triggers on: no key, rejected key, unreachable service, and quota exhaustion mid-run.

### The two properties that mattered more than the fallback existing

**Redaction must not silently weaken.** Emails, phones, URLs and identifiers are the
highest-confidence redactions and need no model. Losing them to an outage would be a
privacy failure, not a quality one. They still run. Only name detection is lost, and the
quote is then flagged `name detection not run (no language model available)` so a
reviewer knows coverage was reduced rather than assuming a clean pass meant no names.

**The document must disclose it.** The methodology section names every degraded stage
verbatim. Silent degradation — output that looks normal but was produced by keyword
frequency — would be exactly the kind of quiet bluffing this system is supposed to avoid.

### A test-setup bug this exposed

Adding the availability gate broke three tests, correctly. The suite installs fake Groq
and SuperDocs clients but never set a key, so once the gate started checking, every test
silently took the heuristic path and the primary path went untested. `conftest.py` now
sets dummy keys (the clients are fakes, so nothing is sent anywhere) and degraded mode is
covered explicitly by clearing them.

Worth recording: the gate did not cause this, it *revealed* it. Those tests had been
asserting against a path they were no longer exercising.

### Verified

- 44 tests pass on SQLite and on real Postgres
- 9 dedicated failure-mode tests: no Groq, Groq outage, no SuperDocs, quota exhausted
  mid-run, both unavailable, each fallback disabled, and redaction surviving an outage
- The worst case run for real: 200 conversations, **no Groq key and no SuperDocs key**,
  producing 29 themes, a QoQ comparison pattern-matched out of the Q2 DOCX, and a 43,432
  byte Word document whose methodology section states it ran without a model

---

## 2026-08-09 — First contact with the live Groq API

### Groq requires the literal word "json" in json_object mode

Every `classify` call failed immediately:

```
Groq 400: {"error":{"message":"'messages' must contain the word 'json' in some form,
to use 'response_format' of type 'json_object'."}}
```

My prompts said "Return ONLY:" followed by a JSON schema, but never the word itself.
**OpenAI's API imposes no such requirement**, so a prompt that works against OpenAI fails
against Groq — and the failure is a 400 at request time, not a parse error, so it never
reached the retry-worthy path.

Fixed in two places:

1. **`GroqClient` guarantees it.** At the single point where `json_object` mode is
   enabled, the messages are checked and an explicit instruction appended if the word is
   absent. Putting the guard here rather than in each prompt means a future prompt author
   cannot reintroduce the bug.
2. **The five prompts now say it themselves** ("Return ONLY a valid JSON object of this
   shape"). Redundant with the guard, but a prompt that states its own output format is
   clearer to read than one relying on a wrapper.

Two regression tests cover it, using `httpx.MockTransport` to capture the outgoing request
body: one asserts the word is present when the prompt omits it, the other asserts the hint
is *not* duplicated when the prompt already mentions JSON.

### What the failure demonstrated about the error handling

Worth recording, because this was the first unplanned failure against a real service:

- Ingest's 200 conversations were checkpointed and survived
- The failed stage was marked FAILED with the provider's actual error message, not a
  generic wrapper
- The UI offered Retry-this-stage, Skip, and Resume-run
- Nothing downstream ran
- Zero tokens were billed

The three retries were arguably wasted — a 400 for a malformed request will never succeed
on retry — but the classifier for retryable-vs-not lives in the client, and a 400 from a
provider is genuinely ambiguous between "your request is wrong" and "transient
validation blip". I have left it retryable rather than adding a special case that could
mask a real transient 400.

**This is exactly the class of bug I said could only be found by running against the real
service.** It was found within seconds of the first live call. The SuperDocs integration
has not yet had its equivalent moment.

---

## 2026-08-09 — Anonymizer was the token sink (design flaw, not config)

Reported symptom: the anonymize stage ran for several minutes on a real run and consumed
most of the token budget.

### The flaw

`anonymize_many()` looped over quotes calling `anonymize()` once each, sequentially. On a
200-conversation run that is 48 themes × 3 quotes = **~144 sequential LLM round trips**,
against a free tier that rate-limits, so each 429 added backoff on top. Classify and
extract together are only ~20 calls. The anonymizer was roughly 85% of the spend and
nearly all the wall clock.

Worse, it called the model for *every* quote — including the majority that contain no
name-shaped token at all and had nothing for a name detector to find.

### Three changes

1. **Pre-screen.** `has_name_candidate()` looks for non-sentence-initial capitalised
   tokens, minus a short list of words that are capitalised in support text but are never
   personal names (`Export`, `Dashboard`, `Chrome`, weekday and month names). On a
   representative sample, 6 of 8 quotes skip the LLM entirely. The list is kept short on
   purpose — over-filtering here turns directly into missed redactions.

2. **Batch per theme.** One call carrying every quote for a theme, indexed, instead of one
   call per quote. Requires a new prompt (`_BATCH_LLM_SYSTEM`) returning a per-index shape.

3. **Bounded concurrency across themes.** `ANONYMIZE_CONCURRENCY` (default 4). Enough to
   hide latency, low enough not to trip the rate limit — backoff from a 429 costs more
   than the parallelism saves.

Net: **~144 sequential calls → at most 48, four in flight, most skipped by the
pre-screen.**

### What I refused to trade

Speed is not worth a leak, so the test asserting the improvement checks **output**, not
call count: emails, phones, identifiers and the name `Sarah Chen` must all still be gone
after the batched path. There is a separate test that the call count dropped, kept
deliberately distinct from the correctness test.

Also preserved: if the model returns no analysis for a quote in a batch, that quote is
flagged `model returned no name analysis` rather than being treated as clean. Silence is
not a clean bill of health, and a batch makes silence easier to miss than a single call
would.

The single-quote path now shares `_apply_spans()` with the batched path, so both resolve
the confidence threshold identically rather than drifting.

### A test-fixture bug this exposed

The batched change added a new prompt, and the Groq fake did not recognise it — so it
returned no spans and the batch path silently did nothing but regex. The correctness test
caught it (`Sarah Chen` survived), which is exactly why that test asserts on output.

Recording it because it is the second time a fake has quietly stopped exercising the path
it was supposed to cover. A fake that returns a plausible empty result is more dangerous
than one that raises.

### Also noted, not yet built

There is **no way to cancel a running run.** Resume, per-stage retry and per-stage skip
all exist, but nothing stops a run that is actively spending. Killing the process works
and loses nothing (checkpoints survive), but that is not a cancel button.

Two things worth adding together:
- `CANCELLED` status plus `POST /runs/{id}/cancel`, checked on node entry so the run stops
  at the next stage boundary
- `MAX_TOKENS_PER_RUN` budget that pauses the run when exceeded — the more useful of the
  two, since it stops runaway spend without anyone watching

---

## 2026-08-14 — Groq free-tier daily cap, and two bugs it exposed

Reported symptom: a 40-conversation run reported `anonymize` taking **10,391 seconds**
(2.9 hours) and three earlier stages taking exactly 120.4s each with zero tokens.

Isolating it layer by layer showed the client, the key, and the model were all fine — a
direct request returned in 0.18s. The logs gave the answer:

```
429 Too Many Requests
"Rate limit reached ... on tokens per day (TPD): Limit 100000, Used 99792,
 Requested 612. Please try again in 5m49.056s"
```

**Groq's free tier is 100,000 tokens per day.** It was spent. Log timestamps ran
23:49 → 01:49 → 02:39 → 03:10 → 03:44 → 04:02: the run sat retrying for hours.

### Bug 1 — Retry-After was ignored and capped

The client read `Retry-After` only from the header, capped any wait at 60s, and retried
three times. Groq puts the wait in the **error message text** ("try again in 20m48.48s"),
so it was never seen. Waiting 60s against a 20-minute window three times is pure waste.

Now parsed from the message body, and a wait longer than 90s is not waited out at all.

### Bug 2 — no distinction between a burst limit and an exhausted allowance

Both arrived as `GroqUnavailable`, so both were retried. These need opposite handling: a
per-minute limit clears in seconds and is worth waiting for, a per-day allowance rejects
every subsequent call until the window resets.

`GroqQuotaExhausted` is now a separate, non-retryable exception, distinguished by matching
`per day` / `TPD` / `RPD` in the message.

### Bug 3 — the same exhaustion was rediscovered 25 times

This is where the three hours came from. The anonymizer catches its own exceptions per
theme and continues, so each of 25 themes independently made three requests, hit the same
spent quota, and moved on. Every stage after it did the same.

Added a run-level **circuit breaker** in `llm_gate`. The first `GroqQuotaExhausted` trips
it; every subsequent gated call short-circuits to heuristics without touching the network.
The anonymizer consults and trips it too, since it bypasses the gate. `execute_run()`
resets it per execution — a quota spent an hour ago may have reset, and a resumed run
deserves a real attempt rather than inheriting a stale verdict.

### Verified

Five new tests, using `httpx.MockTransport` against the **verbatim error text from the
real 429**:

- The retry hint parses to 349.056s and is correctly identified as a daily window
- A daily limit makes exactly **one** request, not three
- A per-minute limit is still retried and succeeds
- After one exhaustion, four further stages make **zero** additional network calls
- The breaker resets between runs

55 tests, passing on SQLite and real Postgres.

### What this cost, and the honest lesson

Roughly three hours of wall clock and the day's entire token allowance, to produce a
digest that had already been produced correctly on heuristics.

The fallback worked exactly as designed — the run completed and disclosed its degradation.
What failed was everything around it: the client did not read the wait the provider clearly
stated, did not distinguish "wait a moment" from "come back tomorrow", and had no memory
between calls, so it relearned the same fact 25 times.

Retry logic that ignores what the server tells it is not resilience, it is just a slower
failure.

---

## 2026-08-14 — Cancellation and a spend guardrail

Two problems reported, the second worse than the first:

1. There was no way to stop a running run.
2. **Runs left going in the background kept consuming the shared token allowance.** A
   `small.csv` run that should cost ~5,000 tokens hit the daily cap of 100,000, because
   earlier abandoned runs were still spending. Nothing surfaced that, and nothing could
   stop it.

The second is the more instructive failure. Every run on one API key draws from one
provider allowance, so a forgotten run does not just waste its own budget — it starves
unrelated work and makes it look broken for no visible reason. That is a design gap, not
an operational mistake.

### Three fixes

**`CANCELLED` status and `POST /runs/{id}/cancel`.** Every node checks for it on entry, so
cancellation lands at the next stage boundary with completed work intact. Kept distinct
from FAILED (nothing went wrong) and from PAUSED (a paused run is expected to resume; a
cancelled one is not) — conflating them would leave cancelled runs looking resumable.
`NodeCancelled` deliberately bypasses the retry path, since retrying a cancellation is
absurd.

**`MAX_TOKENS_PER_RUN` (default 40,000).** Checked on node entry against the run's own
cost report. Exceeding it trips the circuit breaker and logs `BUDGET_REACHED`, so
remaining stages use heuristics instead of continuing to spend.

This matters more than the cancel button. Cancellation requires somebody to be watching;
a budget does not. It is also the only one of the two that bounds spend during a stage
that is already mid-request.

**Visibility: `GET /runs/active/summary` and the `list_active_runs` MCP tool.** Reports
every run currently spending and what each has consumed. The dashboard warns when more
than one run is active, stating plainly that they share one allowance. The information
that would have prevented this was simply not exposed anywhere.

### Honest limitation

Cancellation **cannot interrupt a provider call already in flight**. A stage waiting on an
HTTP response will finish that request before the check runs. Making it truly immediate
would mean cancelling the request mid-flight and handling a partially-charged operation,
which is a larger change than it appears. This is exactly why the token budget exists
alongside it rather than instead of it.

### Verified

7 new tests: cancellation mid-run preserves completed stages and stops the rest, a
cancelled run rejects a second cancel with 409, a completed run cannot be cancelled, the
budget degrades later stages and bounds spend, a budget of 0 disables the limit, the
active-runs endpoint reports both concurrent runs, and `NodeCancelled` is not retried.

Migration `0002` adds the enum value, verified against real Postgres. The downgrade is a
deliberate no-op — Postgres has no `DROP VALUE`, and recreating the type to remove an
additive value is not worth it.

62 tests, passing on SQLite and real Postgres.

### Test-isolation flaw introduced by the circuit breaker

The breaker is a module-level global by design — it must be visible to every stage within
a run. That also makes it shared between tests, so a test that tripped it starved later
tests of LLM calls. The result was a failure that appeared only in a full-suite run and
vanished in isolation, which is the most annoying possible shape for a bug.

Fixed with an autouse fixture resetting it before and after every test. Verified with six
consecutive full-suite runs, all clean.

Worth noting the pattern: this is the third time in this project that shared mutable state
produced a failure invisible in isolation. Global state that is correct for production can
be wrong for a test suite, and the suite is where it surfaces.

---

## 2026-08-14 — Two rendering bugs found by reading an actual generated document

A clean run produced a real DOCX. Reading it — rather than checking it existed — found two
defects that every test had missed, because the tests asserted the file was produced and
not what a person would see in it.

### Bug 1 — every deep-dive heading carried the editor instruction

Headings read:

```
Excel Export Issue — 4 conversations (New this quarter)'. Its body must contain, in order:
```

Draft sections are phrased as instructions to a document editor. The local renderer's
generic stripper removed the leading `Add a subsection under ... titled` but left the
trailing `'. Its body must contain, in order:` — so 24 headings shipped with editor
phrasing addressed to a machine, in a document written for an executive.

Replaced with a parser that extracts the quoted title into a real heading and returns the
remainder as the body.

### Bug 2 — the theme table was rendered twice, once as a heading

`theme_table` starts with `theme_`, and the deep-dive loop selected keys by that prefix.
So the table appeared correctly under "Top Themes This Quarter" **and** again under "Theme
Deep Dives", with its markdown header row `| Theme | Volume | Share | Change |` promoted to
a Heading 2.

Key matching is now `^theme_(\d+)$`, which also fixes the ordering — the old
`int(k.split("_")[1])` would have thrown on `theme_table` had it not been filtered first,
and sorted `theme_10` before `theme_2` as strings.

### Why the tests missed both

Everything asserted the document was *produced*: correct byte count, correct section count,
provenance banner present. Nothing asserted what the headings actually said.

Eight new tests in `test_local_render.py` assert the opposite — that specific instruction
phrases (`Replace the`, `Its body must contain`, `Add a subsection`, `Use exactly these
rows`, `Do not add commentary`) appear **nowhere** in the output, that no heading begins
with `|`, and that exactly one table exists.

The lesson is narrow and worth stating: a document generator's tests must assert on what a
reader sees, not on whether a file was written. "It rendered" and "it reads correctly" are
different claims, and only the second one matters.

### Not a bug, but visible in the same document

Every theme came back `New this quarter` despite the comparison stage running and spending
732 tokens. The prior digest was parsed and its themes extracted; none matched above
`MATCH_THRESHOLD = 0.55`. That is the hash embedder scoring lower than the MiniLM values the
threshold was tuned for — the same limitation already documented for clustering, showing up
in the comparison. With `sentence-transformers` installed, matches would be found.

Worth noting the failure is in the honest direction: an unmatched theme is reported as NEW
rather than being force-matched to a prior theme it does not correspond to.

70 tests, passing on SQLite and real Postgres.

---

## 2026-08-14 — First live SuperDocs contact: two failures

### Groq retired the pinned model mid-session

`llama-3.3-70b-versatile` returned 404 `model_not_found` — the same model that had been in
the models list and answering requests an hour earlier. Switched to `openai/gpt-oss-120b`
via `GROQ_MODEL`, no code change, which is why that is an env var.

Worth recording a subtlety found while picking a replacement: **"the model exists" and "the
model works for structured output" are different checks.** `qwen/qwen3.6-27b` accepted the
request and returned `json_validate_failed` with an empty `failed_generation` — it exists,
it is listed, and it cannot reliably honour `response_format: json_object`. A model probe
must send a realistic prompt, not a trivial one.

### 409 session_busy blocked every retry, permanently

```
409 {'error_code': 'session_busy', 'active_jobs': 1,
     'message': 'The AI is still working on a previous request in this conversation.'}
```

Session ids are deterministic (`vocdigest-{run_id}`) so a resumed run reconnects rather than
re-uploading. That is the right design — but a run that failed mid-edit leaves an **active
job** in that session, SuperDocs permits only one, and so the retry collided with its own
orphan. The run could never be retried.

Worse, my error message actively misled: every 409 was reported as "likely the wrong resume
endpoint (check metadata.awaiting_kind)", which had nothing to do with it. A wrong diagnosis
in an error message is more expensive than no diagnosis.

Three fixes:

1. **`SuperDocsSessionBusy`**, classified on `error_code`, separate from the
   wrong-endpoint 409. One is recoverable, the other is a caller bug — treating them
   identically is what made this permanent.
2. **`clear_active_jobs()`** — lists a session's jobs and cancels the unfinished ones
   (`pending`, `in_progress`, `awaiting_approval`, `queued`), leaving completed and failed
   ones alone. Called on entry to the SuperDocs stage.
3. **Fresh-session fallback** — if a job proves uncancellable, the run moves to a new
   session id and re-uploads. Costs one extra upload; the alternative is a run that can
   never finish.

The API's own error body suggested exactly this ("cancel it with cancel_job, or use a
different session_id"). I had implemented neither. Reading the remediation the provider
hands you is cheaper than deriving it after the fact.

### A leaked connection pool made the suite intermittently fail

One new test built an `httpx.AsyncClient` for a pure function and never closed it. The
resulting leak surfaced as `test_checkpoints_do_not_cross_contaminate` failing roughly one
run in five — a completely unrelated test, which is the worst possible symptom.

`_classify_error` needs no transport, so the client is now created inside `async with`.
Verified with eight consecutive full-suite runs, all clean.

Fourth time in this project that shared or leaked state produced a failure in a test that
had nothing to do with the cause.

73 tests.

---

## 2026-08-14 — SuperDocs verified live, and a duplication bug it exposed

The full happy path completed against a real key:

```
SuperDocs ops: 24
VERIFIED — Document structure confirms 25 sections
EXPORTED — 41,232 bytes after 24 section edits
```

All four calls exercised for real: upload, per-section edit, per-change approval, export.
The `VERIFIED` entry is the free structure read confirming edits actually landed, rather
than trusting a 200.

### The bug it exposed: theme_table applied twice

The section ordering used `k.startswith("theme_")` to collect deep dives. `theme_table` also
starts with `theme_`, so it was queued twice — confirmed in the live output as a duplicate
"Top Themes This Quarter" heading, and one wasted metered operation.

This is the **same bug I had already fixed in `local_render.py`** and did not think to look
for in the SuperDocs node. Fixed identically: match `^theme_(\d+)$` only, sort numerically so
`theme_10` follows `theme_2`, and dedupe the final list with `dict.fromkeys`.

Two regression tests: one asserts no instruction is sent twice, one asserts numeric ordering.

**The lesson is about my own process, not the code.** When I fix a bug caused by a pattern —
here, prefix matching over a namespace containing both `theme_N` and `theme_table` — I should
grep for the pattern rather than the symptom. Both call sites were written the same day, from
the same mistaken assumption.

### Cost, measured rather than estimated

| Input | SuperDocs ops | Groq tokens | Wall clock |
|---|---|---|---|
| 20 conversations, 16 themes | 24 | 11,809 | 1,052s (982s in SuperDocs) |

Extrapolating to 200 conversations gives **~240 operations — roughly half the monthly free
allowance of 500 in a single run.** The README previously estimated ~34, derived from mocked
calls, and was wrong by an order of magnitude. Section count is driven by theme count, and
the offline embedder inflates theme count, so the two errors compound.

Corrected in the README. Worth stating plainly: an estimate taken from mocked calls is not a
measurement, and I should have labelled it as such at the time.

### Also delivered

`DEMO_SCRIPT.md`, `WRITEUP.md`, `ARCHITECTURE.md`.

The demo script leads with a recording strategy rather than narration, because 982 seconds of
SuperDocs latency does not fit in a four-minute video and pretending otherwise would waste a
take.

78 tests.

---

## 2026-08-25 — Four bugs from one root cause, and a verification step that verified nothing

A live run against Groq failed four different ways in sequence. Chasing each failure
individually was the wrong instinct — three of them turned out to be the same mistake in
different places: **empty or failed output propagating as though it were valid.** In a
system whose stated premise is refusing to present weak output as normal, that is a design
gap rather than three unrelated defects.

### Bug 1 — the token budget fought the provider's ceiling

`llama-3.3-70b-versatile` was decommissioned mid-project (404 `model_not_found`), so the
model became `openai/gpt-oss-120b`. That is a **reasoning** model, and its reasoning is
drawn from the same token budget as its answer. At the original `max_tokens=2048` the
reasoning consumed the whole budget and the model returned an empty completion, surfacing
as:

```
400 json_validate_failed   failed_generation: ""
```

A validation error for output that was never produced — which sends you to inspect the
prompt when the problem is arithmetic.

The obvious fix, tripling the budget, then produced the opposite failure:

```
413 Request too large ... tokens per minute (TPM): Limit 8000, Requested 9904
```

3072 × 3 = 9216 plus ~690 prompt tokens. Groq counts *requested* `max_tokens` toward TPM
before generating anything, so the request was rejected on arrival. Two constraints in
direct tension: too small yields an empty completion, too large yields a 413.

Guessing a number that fits both is not a fix, it is a coincidence that survives until a
limit changes. Resolved with a `token_budget` layer that reads the real ceilings from
Groq's response headers (`x-ratelimit-limit-tokens`, `-remaining-tokens`,
`-reset-tokens`), sizes each request to fit, and **splits an oversized batch rather than
sending it and failing**. A 413 now narrows the batch and retries instead of aborting.

### Bug 2 — a failed stage did not halt the run

```
2. Classify & filter    1.0s  958 tok
3. Extract facts        FAILED (413)
4. Cluster themes       0.0s
5. Anonymize quotes     0.0s
6. Compare to prior    77.6s
7. Draft digest         0.0s
8. Human approval gate  0.1s  ×6
   → AWAITING_APPROVAL, 0 themes, "0 items need a decision"
```

Extract failed and every downstream stage ran anyway on empty input, arriving at an
approval gate containing nothing — a meaningless state presented as a valid one. `compare`
spent 77 seconds retrying a call that could not succeed, having nothing to compare.

A FAILED stage now halts the pipeline, and a node that finds its required input empty
raises rather than quietly producing nothing.

### Bug 3 — the approval gate looped forever on an empty run

The `×6` above was infinite re-entry. `human_gate` decided whether to create items by
checking whether any already existed. With zero themes upstream it created zero items, so
"none exist" stayed true, so it created zero again and paused again — forever. Never
progressing, never failing. The UI showed *"Nothing left to review — 0 approved, 0
rejected"* with no controls, while the run sat at `AWAITING_APPROVAL`: unresolvable through
the interface.

Creating zero approval items is not a valid gate state. If there is nothing to review there
is nothing to publish, so the run now fails with that stated plainly. The node also
distinguishes "not yet created" from "none possible", so re-entry cannot loop regardless of
what upstream did.

### Bug 4 — two processes on one SuperDocs session

Restarting uvicorn while a background task was in flight left two processes driving the
same SuperDocs session, each cancelling the other's jobs. That poisoned the session and
forced eleven rotations. A per-run lock now prevents the in-process case; it cannot prevent
two OS processes, which is stated in the code rather than implied to be handled.

---

## Known issue, unfixed — session rotation drops applied sections

`superdocs.py` re-uploads `TEMPLATE_HTML` on session rotation but resumes from
`ordered_keys[ordered_keys.index(key):]` — the current section onward. The fresh document
has none of the earlier sections, so **every section already applied is silently lost.**
The inline comment claims this "costs one extra upload"; it actually costs all prior work.

Observed on a real run: `SECTION_APPLIED — Section 'what_changed'` succeeded, five
`SESSION_STUCK` rotations followed, and the exported document had "What Changed Since Last
Quarter" back to its placeholder. 25 paragraphs where a comparable clean run produced 113.

**The worse half is that `VERIFIED` did not catch it.** That check reads
`structure["headings"]` — and the blank template *is* all the headings, since that is what
makes it a template. So the check passes on a document containing nothing but placeholders.
It confirms the scaffold, not the content.

This matters beyond the bug. Earlier in this project I cited "24 operations, document
structure confirmed, DOCX exported" as evidence the SuperDocs integration worked. That
evidence would have passed on a hollow file. I built a verification step that could not
distinguish success from failure, and then quoted it as proof of success.

Both fixes are known and small:
- replay the **full** key list against a fresh template, not the tail slice
- have `VERIFIED` assert that no section body still equals the placeholder string

Not applied yet. Every genuine export was checked and all carry zero unexpected
placeholders, so nothing hollow has shipped — but the check that was supposed to guarantee
that could not have told me either way.

The general lesson, which is the third time a version of it has appeared in this log: a
check that cannot fail is not a check. `VERIFIED` passing meant only that a document had
headings, which was true before any edit was applied.

---

## Corrections to previously stated figures

Both measured from live errors rather than assumed:

- **Groq daily cap is 200,000 tokens**, not the 100,000 stated earlier.
- **200 rows completes at `LLM_BATCH_SIZE=24`** — roughly 62,000 tokens and about 8 minutes,
  or 31% of a day's allowance, so two to three full runs daily. For iteration, 50 rows at
  batch size 8 costs ~2.8 minutes and 11%.

106 tests pass (78 original plus 28 new covering the token budget, the failure cascade, and
the empty-gate case).