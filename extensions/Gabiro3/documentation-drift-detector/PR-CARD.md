# Build card — Documentation Drift Detector

**Builder:** Gabiro Arnaud (GitHub `@Gabiro3`)
**Surfaces touched:** Search · Multi-document · Review · API · Export
**Where the finished work goes:** `extensions/Gabiro3/documentation-drift-detector/`
**Built against:** SuperDocs REST API (`https://api.superdocs.app`, Universal
Document AI API 2.0.0). Every capability used here is also reachable over MCP;
nothing in the design depends on which of the two surfaces carries it.

---

## In one sentence

Given a documentation set and a change feed, it finds every section that is now
factually wrong, proves why with a cited quote, proposes a scoped fix, lets a
human approve item by item, applies the approved edit through SuperDocs to that
one chunk, and proves by hash that no other chunk changed.

---

## Who it serves

**The person who owns a documentation set that keeps quietly going stale.**
Concretely: a developer-experience or technical-writing owner with dozens to
hundreds of pages, shipping a product whose defaults, flags and command names
change faster than the prose describing them.

Their real problem is not "find text that mentions port 3000". It is:

- Nobody notices docs are wrong until a user is burned by them.
- A full re-read after every release is unaffordable, so it never happens.
- A find-and-replace across a docs repo is terrifying, because the blast radius
  is invisible until review — and reviewing a 400-file diff is its own job.
- An LLM turned loose on a docs folder will confidently rewrite paragraphs
  nobody asked it to touch, and the diff cannot prove otherwise.

What they need is not more automation. It is automation they can **audit**:
something that shows its evidence, changes exactly what it said it would change,
and admits when it does not know.

A second, smaller audience: **anyone auditing an AI editing pipeline.** The
byte-identity proof and the append-only trace are the parts worth stealing
regardless of the drift use case.

---

## What a strong build looks like

These are the bars I held this to. Where it falls short, that is stated in
[Caveats](#caveats-stated-up-front) rather than omitted.

**1. It cannot claim drift without evidence.**
A `CONFIRMED_DRIFT` finding must carry `evidence_chunk_id`, `evidence_quote`
and `change_fact_id`. This is enforced by schema validation in code, not by
asking a model nicely. A finding that cannot populate those fields cannot be
emitted — it falls to `UNKNOWN`. A verdict citing a chunk that was never
offered to the model is discarded as fabrication.

**2. "Nothing else changed" is measured, never asserted.**
The Judge is two phases of pure code with zero LLM involvement:

- **Phase A (pre-commit):** every pending change must target an approved chunk,
  or the batch is actively *denied* and nothing is applied.
- **Phase B (post-apply):** the document is re-fetched and every non-target
  chunk must hash identically to its pre-edit snapshot, or the commit is
  blocked and alarmed.

An LLM is never asked whether a document is unchanged. That is a hash
comparison, and treating it as a judgement call is how these systems lie.

**3. Uncertainty is a first-class output.**
Three states — `CONFIRMED_DRIFT`, `NO_DRIFT`, `UNKNOWN` — never a raw
confidence threshold. `UNKNOWN` (an abstention) and `FAILED` (a retryable
error) are different queues: `UNKNOWN` items are never silently retried into
existence.

**4. The human gate is real, and approval means something happened.**
Per-finding approve/reject with feedback. Critically, *approval and application
are separate facts*: `review_decisions.decision` is what a person decided,
`findings.apply_status` is what happened to the document. A build where
"Approved" is displayed while the document is untouched is a build that lies to
its reviewer — this one distinguishes `applied`, `blocked`, `failed` and
`document_missing`, and says which.

**5. Quality is measured, not claimed.**
`GET /run/{id}/metrics` returns precision, recall, F1, accuracy and UNKNOWN
rate against the seeded corpus. Partial detection is counted as a false
negative rather than excused by a footnote.

**6. It survives being killed.**
Every pipeline node checkpoints to `run_steps` keyed by input hash. `kill -9`
mid-run and resume replays only the incomplete nodes, without duplicating
findings.

**7. Its cost is counted.**
Every SuperDocs operation and token is written to an append-only trace and
aggregated per stage in a cost panel. "Cheap" is a number here, not an
adjective.

---

## The five surfaces, and exactly what was built on each

### Search

Global search across every document in every run, from the sidebar or
`Ctrl`/`Cmd`+`K`. Chunks containing the typed phrase rank first with the match
highlighted; chunks related only by meaning appear below, labelled as such.
Selecting a result opens the document viewer scrolled to that exact chunk.

`GET /search?q=&limit=&run_id=&semantic=` → ranked hits carrying document,
filename, run, chunk id, snippet offsets and match type.

**This is built on our own embeddings — SuperDocs has no search endpoint.**
See caveat 1; this is the single largest deviation in the build.

### Multi-document

Ingest of a whole corpus: upload, hash-diff so an update costs like an update,
per-document durable identity, and a documents view with per-document content,
edit history and re-ingest.

Uses `POST /v1/documents/upload-base64`,
`GET /v1/sessions/{id}/documents`, `POST /v1/sessions/{id}/documents/open`,
`POST /v1/sessions/{id}/documents/{doc}/focus`.

**One SuperDocs session holds one document**, so "multi-document" here means
many sessions presented as one workspace. See caveat 2.

### Review

The human gate. Findings grouped by document with evidence quote, before/after,
and a side-by-side diff panel. Per-item approve/reject with feedback, persisted
across reloads. Approving schedules the apply in the background — the Review
page polls and each card reports the true outcome, including `Blocked —
document unchanged` when the byte Judge refused the edit.

Uses `POST /v1/chat/async` (`approval_mode=ask_every_time`, `model_tier=max`),
`GET /v1/jobs/{id}`, `POST /v1/chat/{id}/approve` (including *denials*),
`POST /v1/chat/{id}/continue`.

### API

Three FastAPI services, each owning one concern, communicating through a
Postgres `jobs` table rather than a message queue:

| Service | Port | Owns |
|---|---|---|
| Ingestor | 8001 | watch, upload, documents, history, re-ingest |
| Analyzer | 8002 | findings, search, metrics, cost, run logs, stop/resume |
| Editor / Review | 8003 | review, approve/reject, apply, export |

All SuperDocs traffic goes through one `SuperDocsClient` wrapper, so the REST
surface could be swapped for MCP in a single module.

### Export

`GET /export/{run_id}` → `POST /v1/downloads` returns a signed download URL for
the corrected document. Because each document occupies its own session, a
session-scoped export is per-document by construction. Locally stored copies
are also downloadable as HTML or plain text.

---

## Caveats, stated up front

Full detail in [`README.md`](./README.md#caveats-and-honest-limits).

**1. Search is not SuperDocs-native.** The live OpenAPI document has no search
path and no mention of semantic search, vector search or similarity across 77
endpoints. Search here runs on the pgvector index this project already
maintains, over a plain-text projection of chunk HTML (matching raw markup
would make `class` or `href` hit every chunk). Literal and semantic hits are
scored in **disjoint bands**, so no similarity score can outrank a chunk that
actually contains the query, and a similarity floor keeps a nonsense query from
returning a confident-looking page of noise. Driving search through
`chat_async` was considered and rejected: an LLM job per query, seconds of
latency, billed as operations, and blind to documents not open in the session.
*If SuperDocs ships native search, the right move is to delete our module and
call it — the `GET /search` interface would not need to change.*

**2. One document = one session, even though users see a single workspace.**
Verified against the live API: uploading into a session that already holds a
document does not add a tab, it **overwrites** the existing document — the
upload created no new document and bumped `updated_at` on the old one. An
earlier version of this build used one sticky session for the whole corpus and
was therefore destroying a document on every upload. Now each document is
ingested into its own session (keyed by content hash), that session is stored
with the document because open/focus/chat/approve are all session-scoped, and
the durable id is read from that session's single-entry roster — never matched
by title, since titles are filename stems, are shared between documents, and
survive an overwrite while the content underneath changes.

The user never sees a session id. The cost is that **documents ingested under
the old model hold an id that names nothing**, so
`POST /documents/{id}/reingest` rebuilds a document from its source file into a
fresh session. It rebuilds from the source rather than from stored chunks
because **SuperDocs mints new random chunk ids on every upload** — so a
re-ingest necessarily invalidates that document's existing findings. They are
cleared; applied-edit history is preserved, because it records something that
really happened.

**3. Chunk ids are not stable and chunk order is not inherent.** Ids are random
UUIDs that do not sort, so document order is captured as `chunks.ordinal` at
ingest. Rows written before that column existed cannot be repaired by any query
and sort last until re-ingested.

**4. The byte proof is about chunk content, not file bytes.** Phase B proves
every non-target chunk hashes identically. It does not claim binary equality of
an exported `.docx`.

**5. Scale is untested beyond a small corpus.** Search does a sequential scan
over `text_content` for the literal half; it is correct but not tuned, and no
trigram or full-text index is required yet at this size.

---

## Running it

Setup, environment variables (as placeholders) and commands are in
[`README.md`](./README.md#quick-start).

**246 backend tests pass with no live API keys** — the LLM provider and the
SuperDocs client both have mock implementations, so the whole pipeline is
exercised offline:

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -v
```

No hosted demo. The quick start brings the full stack up locally against the
seeded corpus in `backend/tests/fixtures/corpus/`.
