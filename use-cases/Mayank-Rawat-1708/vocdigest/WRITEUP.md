# VocDigest

**Voice-of-Customer digest generation with a human approval gate.**
Built for SuperDocs Round 2 · difficulty S2

---

## What it does, and for whom

Support teams accumulate thousands of conversations a quarter. The signal in them is real,
but nobody has time to read it — so it gets summarised from memory in a meeting, and
"customers are complaining about X" becomes an unfalsifiable claim.

VocDigest is for the person who has to write that summary and stand behind it: a support
lead, a product manager, a founder reading their own inbox. It takes a quarter of support
conversations, clusters them into themes, anonymizes verbatim quotes, computes
quarter-over-quarter change against last quarter's digest, and produces a styled document
through SuperDocs.

The output is traceable rather than asserted. Every theme cites the file and line number of
every conversation supporting it. Every quote shows what was redacted and with what
confidence. Every QoQ figure is computed from the prior digest, not recalled. And the run
**stops and waits for a human** before anything is published — rejecting a theme removes it
from the document without failing the run.

---

## SuperDocs surfaces used

**Chat** — one targeted edit per document section rather than a full-document rewrite, so
each section is independently approvable at the gate. **Export** — DOCX, with the structure
read used to verify edits landed rather than exporting a whole document to check.
**Multi-document** — last quarter's digest is attached as a read-only reference the AI can
cite while editing the current one. **Search** — the attachment is searchable by the editing
AI. **Images** — charts are inserted as inline SVG, with a Unicode block-character fallback
because I could not verify SVG survives a DOCX round-trip.

Human-in-the-loop is used throughout: `approval_mode: ask_every_time`, then explicit
per-change approval.

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

The brief also states that proposed-change content always needs a second JSON parse. That is
true of the **SSE** path, but not of polling, where `metadata.pending_changes` is already an
array — double-parsing it throws. This backend polls, because a headless resumable worker
should not depend on holding an open stream across a process restart.

---

## Trade-offs I made, honestly

**Granularity over speed.** One SuperDocs edit per section means four round trips each —
edit, poll, approve, poll — and 982 seconds for 24 sections. Batching would be much faster
and would defeat the approval gate. I kept the gate.

**Durability over elegance in resume.** Checkpoints live in Postgres, not in LangGraph's own
checkpointer, because an in-process checkpointer does not survive the process being killed —
which is the behaviour being asked for. The cost is that resuming replays through completed
stages, which no-op on their checkpoints. Correct, but eight database round trips to reach a
pause point.

**Reproducibility over cluster quality.** Clustering is single-pass greedy, not k-means,
because identical input must produce identical clusters — otherwise a resumed run silently
diverges from the run it is continuing. Greedy is worse on some distributions. I took that
knowingly.

**Charts shipped twice.** I could not verify SVG survives a DOCX export round-trip, so every
chart is emitted as SVG *and* as Unicode block characters. Redundant, but a chart that
silently vanishes on export is worse than one that is merely plain.

**Under-claiming over over-claiming.** Themes with fewer than three supporting conversations
carry an explicit confidence note instead of being stated as trends. With no prior digest the
document contains no growth figures at all — there is a test asserting the "What Changed"
section contains no `%` character. Unmatched themes are reported as NEW rather than
force-matched to a prior theme they may not correspond to.

**What I cut:** auth (single-tenant local tool), and `sentence-transformers` as a default
dependency — it pulls ~2GB of torch. The fallback embedder is not semantically trained, so
clustering over-fragments: 20 conversations produce ~16 themes where the real model gives
~4. It is one `pip install` and one env var, and it is documented under What Breaks rather
than hidden.

**Anonymization is not guaranteed and is not marketed as such.** Two passes, an explicit
`[POSSIBLE-NAME]` marker for spans the model could not classify confidently, and a human gate
as the actual control. The digest's methodology section says exactly that.

---

## Resilience

Neither external service is a hard dependency. **No Groq** — falls back to keyword heuristics
for classification, extraction, theme naming, prior-digest parsing and the summary; clustering
is unaffected because it is embedding-based. **No SuperDocs** — renders the approved digest
locally to DOCX rather than stranding a completed analysis. **Both unavailable** — the full
pipeline still produces a document.

In every case the methodology section names the degraded stages verbatim. Silent degradation —
output that looks normal but came from word frequency — would be the exact failure this system
exists to avoid.

`MAX_TOKENS_PER_RUN` bounds spend without supervision, `POST /runs/{id}/cancel` stops a run at
the next stage boundary, and `GET /runs/active/summary` shows what is competing for a shared
provider allowance. All three exist because a forgotten background run silently drained a daily
token cap during development and made an unrelated run appear broken.

---

## Verified by execution

78 tests passing on SQLite **and** real PostgreSQL 16 with pgvector, needing no API keys.
Alembic verified against a live database. Full pipeline driven end to end through the REST API
and separately through MCP tools. **SuperDocs verified live**: 24 operations, document structure
confirmed, 41 KB DOCX exported.

Real cost for 20 conversations: 24 SuperDocs operations, 11,809 Groq tokens, ~$0.008.

`PROGRESS.md` documents every assumption and 20 bugs found in my own code across five audit
passes. Four surfaced only against live APIs — Groq requiring the literal word "json" in JSON
mode, a daily token cap that my retry logic turned into three hours of 429s, a 409
`session_busy` whose error code was nested where I was not looking, and two rendering bugs I
found only by opening the generated document and reading it.

That last one is the lesson I would keep: tests asserted the document was *produced*. None
asserted what a reader would see in it. "It rendered" and "it reads correctly" are different
claims, and only the second matters.