# Implementation Plan — SuperDocs Agent Review Workspace

Status: Phase 0 (research + planning) complete. This document gates
implementation per the task brief ("do not begin large-scale implementation
until this analysis is complete"). Everything below is grounded in the real
`superdocsapp/superdocs-builds` repository and the real SuperDocs API, both
fetched and read directly — nothing here is assumed or invented.

## 1. Assignment requirements (verbatim capture)

Source: the task brief pasted into this session, self-described as sourced
from "the official SuperDocs Open Task List." I have not seen that list as a
separate artifact — the brief is the only copy of the requirements I've been
given, so it is being treated as authoritative rather than paraphrased from
memory. Requirements, unchanged from the brief:

- VS Code panel, usable next to any coding agent
- Every document change an agent proposes is reviewable
- Before/after presentation
- Grouped by agent turn
- Approve per change, reject per change, revert per change
- A single log of what the agent actually did vs. what it claimed
- The claimed-vs-actual check must catch a turn where the agent claimed an
  edit it did not actually make
- Reverting one change must not disturb other changes
- Support more than one agent client; do not special-case individual agents
- Production-minded, testable, understandable, maintainable, genuinely useful
- No mockup pretending to be an integration; no hard-coded fake events as the
  primary implementation; no fake backend under a nice UI; no claiming
  support that isn't real; no silent data loss; no weakening correctness for
  the demo

## 2. Repository findings

Cloned `https://github.com/superdocsapp/superdocs-builds` directly (public,
no auth needed). Full contents at the time of this plan:

```
CONTRIBUTING.md
LICENSE
README.md
extensions/README.md
use-cases/README.md
```

Three commits, all scaffolding — **no existing extension submissions**, so
there is no prior art to extend or stay consistent with (Phase 0's "don't
create a parallel architecture if one can be extended" doesn't apply; nothing
exists yet). Key facts from the repo's own docs, in my own words:

- The repo is a flat contribution model, not a conventional monorepo with
  shared tooling: each contributor gets exactly one folder
  (`extensions/<github-username>/<project-name>/`) and must not touch
  anything outside it. There is no root-level `package.json`, no shared CI,
  no shared lint config to inherit — each project is self-contained and
  brings its own tooling, its own README, its own test setup.
- This confirms the correct location for this contribution:
  `extensions/<github-username>/<project-name>/`, per `extensions/README.md`
  and `CONTRIBUTING.md`. I do not have the actual GitHub username this will
  be submitted under, so the folder is named `YOUR_GITHUB_USERNAME` as a
  clearly-marked placeholder — **rename this folder to the real GitHub
  handle before forking/opening the PR.**
- `CONTRIBUTING.md` explicitly states this repo is also used for **SuperDocs
  hiring-round submissions** (email + GitHub handle collected by the round's
  own form, not the PR). That materially changes what "done" means here: the
  reviewer is a SuperDocs engineer assessing real engineering judgment, not
  a bot checking a box, which is one more reason not to fake any part of
  this.
- Project README requirements per `CONTRIBUTING.md`: what it does in plain
  language, how to run it (setup, env vars as placeholders, commands), which
  SuperDocs features it uses, and a demo link if one exists. Never commit
  secrets — use placeholders like `SUPERDOCS_API_KEY=your-key-here`.
- There is no existing MCP integration, API client, document/review
  primitive, or test harness anywhere in this repository to reuse. Every
  primitive this project needs either comes from the SuperDocs platform
  itself (section 3) or has to be built from scratch inside the project
  folder (section 4/5).

## 3. The actual SuperDocs platform: API and MCP surface

This is the single most consequential research finding, so it gets its own
section. SuperDocs (superdocs.app / docs.superdocs.app) is **not** the
similarly-named open-source `SuperDoc` DOCX editor at superdoc.dev — the
SuperDocs docs explicitly call that out as a separate, unaffiliated product.
This project is built against SuperDocs (plural): a hosted, HTML-in/HTML-out
document-editing service reached over a REST API (50+ endpoints) and an MCP
server (38 tools) that expose the *same* underlying operations either way.

Facts below are paraphrased from `docs.superdocs.app` (fetched directly:
the overview page, the full API/MCP reference, the human-in-the-loop guide,
and the SSE streaming guide) — not copied verbatim, since the prose belongs
to SuperDocs. I'm reproducing the technical contract (endpoint names, field
names, semantics) because that's exactly what an integration boundary has to
be built against.

### 3.1 Documents are HTML, addressed by chunk

Every document is HTML. On upload or creation, SuperDocs assigns every
paragraph, heading, table, row, and cell a stable `data-chunk-id`. All
edits — proposed or applied — are expressed against chunk IDs. This chunk
model is the natural unit for this project's `Change.target` and for diffing
(section 7).

### 3.2 Sessions, Files, and turns

- A **session** (`session_id`, caller-chosen) holds one conversation thread
  plus the document state attached to it. Sessions never expire.
- A **File** (`document_id`, server-assigned, durable) is the actual saved
  document, independent of any one session. Opening a File into a session is
  share-attach, not copy — the same File can be live in several sessions at
  once ("multi-document" is native, not something this project has to
  invent).
- `GET /v1/sessions` lists sessions by recent activity.
  `GET /v1/sessions/{id}/history` returns the full message history, with
  each message carrying a `turn_index` and a `checkpoint_id`, plus the
  document HTML at that point. **A "turn" in SuperDocs terms is exactly one
  user message + the assistant's response to it** — this maps directly onto
  the brief's "grouped by agent turn" requirement; no separate turn concept
  needs to be invented.

### 3.3 Two ways a change actually reaches the document

This distinction drives the whole integration design (section 6) and is
easy to get wrong, so it's called out explicitly:

**Auto-apply (the default).** A plain `POST /v1/chat` or `/v1/chat/async`
call edits the document immediately. The response contains the AI's
free-text reply plus `document_changes.updated_html` — the *new whole-document
HTML*, not a structured per-chunk diff. SuperDocs does **not** hand back "here
are the 3 chunks that changed" for a normal single-document auto-apply turn;
a `documents_changed` event only fires for multi-document turns or newly
created documents. For a single document on the default path, the *caller*
has to diff old-chunk-map vs. new-chunk-map itself to know what actually
changed.

**Human-in-the-loop (opt-in).** If the caller sets
`approval_mode: "ask_every_time"` on `/v1/chat/async`, the job pauses with
`status: "awaiting_approval"` and `metadata.pending_changes` — an array of
already-structured per-chunk proposals, each with `change_id`, `operation`
(`edit` / `create` / `delete`), `chunk_id`, `old_html`, `new_html`, and
`ai_explanation`. The caller responds via
`POST /v1/chat/{session_id}/approve` (single or batched, with optional
feedback text SuperDocs feeds back to the AI). This is SuperDocs's *own*
built-in review gate — but it only exists if whoever is driving the chat
turn (the coding agent, or a human) explicitly opted into it.

**Consequence for this project:** I cannot assume every coding agent will
opt into `ask_every_time` — most won't even know the flag exists, and the
brief forbids special-casing agents anyway. So this project's review layer
has to work primarily on **already-applied, auto-apply changes**, discovered
by diffing consecutive document snapshots — with HITL support layered on
top as a strictly-better path when a session happens to be `awaiting_approval`
(in which case this extension can also act as the approval surface, calling
SuperDocs's own `/approve` before the change ever lands). Both paths funnel
into the same internal `Change` model (section 7); the workspace's own
approve/reject/revert semantics are a separate control plane from SuperDocs's
optional HITL gate, not a re-implementation of it.

### 3.4 Revert is coarser-grained than this project needs

`POST /v1/sessions/{id}/revert` rewinds a session to the state *before a
given user message* — chat and document together, using `turn_index`. It is
message/turn-grained, all-or-nothing for everything in that turn. The
brief's acceptance test 3 requires reverting exactly one of two changes
**from the same turn** while leaving the other intact — SuperDocs's revert
cannot do that (reverting the turn would take both). So this project cannot
lean on SuperDocs's revert for sub-turn granularity; section 6.3 covers the
chunk-level revert this project builds instead. SuperDocs's revert *is* the
right tool for a coarser case this project also needs: discarding an entire
turn cleanly, and for the "extension restart" persistence test, since revert
state lives server-side, not in the extension.

### 3.5 Everything relevant, addressed by REST path

Endpoints this project actually calls, restated in my own words (method,
path, why it matters here):

| Purpose | Endpoint |
|---|---|
| Edit synchronously (auto-apply) | `POST /v1/chat` |
| Edit asynchronously / HITL / long edits | `POST /v1/chat/async` |
| Poll a job (status, pending changes, result) | `GET /v1/jobs/{job_id}` |
| Approve/deny a proposed change | `POST /v1/chat/{session_id}/approve` |
| Cancel an in-flight job | `POST /v1/jobs/{job_id}/cancel` |
| Resume/stop a large-edit continue prompt | `POST /v1/chat/{session_id}/continue` |
| Stream progress for one job (SSE) | `GET /v1/chat/{session_id}/stream` |
| List sessions | `GET /v1/sessions` |
| Full history for one session | `GET /v1/sessions/{id}/history` |
| Job history for one session (audit) | `GET /v1/sessions/{id}/jobs` |
| Cross-session document-changed poll | `GET /v1/sessions/{id}/doc-events` |
| Rewind a session to before a message | `POST /v1/sessions/{id}/revert` |
| Undo a revert | `POST /v1/sessions/{id}/redo` |
| Resolve a concurrent-edit conflict on one chunk | `POST /v1/sessions/{id}/chunks/{chunk_id}/re-edit` |
| List saved Files | `GET /v1/documents` |
| One File's detail (+structure outline) | `GET /v1/documents/{id}` |
| Health check | `GET /health` |
| Confirm an API key cheaply | `GET /v1/sessions` |

Auth: `Authorization: Bearer sk_...` (personal) or `lce_...` (org), identical
header for REST and MCP; MCP endpoint is `https://api.superdocs.app/mcp/`.
Rate limiting/quota surfaces as `429` with `Retry-After` plus
`X-Usage-Limit` / `X-Usage-Used` / `X-Usage-Remaining` headers, and every
chat response carries a `usage` block (`ops_charged`, `was_billable`,
`quota_exhausted`). `was_billable: false` on a turn is a meaningful, honest
signal used in section 6.2's claimed-vs-actual check.

## 4. Existing reusable primitives (what SuperDocs already gives us)

Being explicit about what does *not* need to be built, because reusing a
real primitive beats reimplementing it badly:

- Turn grouping — free, it's just `turn_index` in session history.
- Chunk-addressable before/after content for HITL turns — free, it's
  `old_html`/`new_html` on `pending_changes`.
- Server-side persistence of conversation + document state, across restarts
  and indefinitely — free; this project does not need to persist document
  content itself, only its own review/audit layer (section 7).
- A concurrent-edit conflict primitive (`chunks/{id}/re-edit`, `redo`,
  `redo`/`revert`) already exists for the multi-writer case.
- Multi-document sessions are native (tabs, focus, open/close), not
  something this project has to model itself.

## 5. Gap analysis (what actually has to be built)

Nothing above gives us, out of the box:

1. A **VS Code panel** — SuperDocs has a web app and a hosted API/MCP
   server, nothing that runs inside an editor.
2. **Agent-agnostic turn discovery** that doesn't require the calling agent
   to opt into anything — SuperDocs's HITL flow requires the *caller* to set
   `approval_mode`; most coding agents won't.
3. **Chunk-level diffing for the auto-apply path** — SuperDocs gives whole
   updated HTML, not a structured diff, outside HITL mode.
4. **Claimed-vs-actual reconciliation** — SuperDocs has no concept of
   "the AI's text claim vs. what really changed"; this project has to define
   and compute that itself from real signals (chunk diff + billing/`usage`
   fields), never from asking an LLM to grade itself.
5. **A `Change` object with its own status state machine**
   (`proposed → approved/rejected → reverted`, `conflicted`, `superseded`) —
   SuperDocs's own state (job status, chunk content) is not this; ours is a
   layer on top, owned entirely by this project, and persisted independently
   of SuperDocs (section 11).
6. **Chunk-level independent revert** — SuperDocs's revert is turn-grained;
   reverting one change without touching a sibling change from the same turn
   is this project's own patch logic (section 6.3).
7. **The audit trail itself** — SuperDocs has job history, but not a
   unified WHO/WHAT/WHEN/CLAIM/ACTUAL/DECISION/BY-WHOM record; that's a
   project-owned, persisted log (section 12).

## 6. Proposed architecture

```
                     ┌─────────────────────────────┐
Coding agent(s) ───▶ │   SuperDocs (hosted API)     │ ◀── any MCP/REST caller,
(any external          │   sessions / jobs / chunks   │     never special-cased
coding tool)          └──────────────┬──────────────┘
                                     │ polled (REST) + streamed (SSE, best-effort)
                                     ▼
                     ┌─────────────────────────────┐
                     │  Session Watcher              │  discovers new turns per
                     │  (integration boundary)       │  known session, agent-agnostic
                     └──────────────┬──────────────┘
                                     │ raw turn + before/after HTML
                                     ▼
                     ┌─────────────────────────────┐
                     │  Chunk Differ                 │  structural diff over
                     │                                │  data-chunk-id maps
                     └──────────────┬──────────────┘
                                     │ normalized Change[] (proposed)
                                     ▼
                     ┌─────────────────────────────┐
                     │  Claim Reconciler              │  claimed text vs. actual
                     │                                 │  diff + usage signals
                     └──────────────┬──────────────┘
                                     │ Change[] with reconciliation verdict
                                     ▼
                     ┌─────────────────────────────┐
                     │  Change Store (state machine)  │  proposed/approved/
                     │  + Audit Log (SQLite, on-disk) │  rejected/reverted/conflicted
                     └──────────────┬──────────────┘
                                     │
                       ┌─────────────┼─────────────┐
                       ▼             ▼             ▼
                 VS Code Tree   Review Webview   Revert Engine
                 (turns/docs)   (before/after,    (chunk patch,
                                 claim vs actual,  independence-
                                 approve/reject)   preserving)
```

### 6.1 Integration boundary (agent-agnostic by construction)

The adapter is not "one adapter per coding agent." It is one component — the
Session Watcher — that talks only to the SuperDocs REST API using the
user's own SuperDocs API key. It does not know or care whether one coding
tool, another, or a bare script issued the request that produced a turn;
it only knows a session it's watching now has a new `turn_index` it hasn't
seen. This is what actually satisfies "support more than one agent client,
do not special-case individual agents" — the special-casing is architecturally
impossible because there is nothing agent-specific to special-case against.
The one identity signal available per turn is whatever `clientType`-ish
metadata SuperDocs surfaces on the message/job (to be confirmed empirically
in Phase 2 against a real account — the docs read so far don't show a field
that names the calling client, only session/job/user identity); if none
exists, the normalized event's `clientType` is honestly recorded as
`"unknown"` rather than guessed, per the brief's own honesty rules.

Discovery loop: poll `GET /v1/sessions` for sessions with an activity
timestamp newer than what's already synced (configurable interval, default
a few seconds — matching the SSE guide's own observation that intermediate
progress arrives every 1–5s during active processing); for a moved session,
pull `GET /v1/sessions/{id}/history` and `GET /v1/sessions/{id}/jobs`; diff
against the last-seen `turn_index`/`checkpoint_id` per session (persisted,
section 11) to find genuinely new turns, so a restart or a duplicate poll
never re-ingests the same turn twice (`turn_index` is monotonic and
therefore a natural idempotency key — see 12.1). Where a session is
currently `awaiting_approval`, the watcher also surfaces the SuperDocs-native
`pending_changes` directly (better data, no diffing needed) and offers
approve/deny through SuperDocs's own endpoint as an *additional*, not
alternative, control.

### 6.2 Claimed vs. actual

For every ingested turn: "claimed" = the assistant's free-text reply for
that turn, taken verbatim from session history — never summarized or
reinterpreted by another LLM call. "Actual" = the chunk-level diff between
the document snapshot immediately before the turn and immediately after
(computed by the Chunk Differ, section 7), cross-checked against the turn's
`usage.was_billable` / `ops_charged` fields from the SuperDocs response.
Verdict is a plain rule, not a model call:

- diff non-empty AND `was_billable: true` → **match**
- diff non-empty but touches materially fewer/different chunks than the
  claim's own chunk references (when SuperDocs supplies them, e.g. via HITL
  `chunk_id`s) → **partial** / **conflicting**
- diff empty AND `was_billable: false`, on a turn whose text reads as an
  applied edit rather than a question/no-op explanation → **claimed but not
  observed** (surfaced as a warning, never silently dropped — this is
  acceptance test 2)
- diff empty AND `was_billable: false`, on a turn that is a question,
  analysis, or an honest "nothing needed changing" reply → **no actual
  change claimed**, not flagged as a discrepancy (SuperDocs explicitly
  supports this legitimate zero-op case per its own billing rules, and a
  workspace that flagged every question as a false claim would train users
  to ignore the real warnings)

The last distinction (legitimate no-op vs. false claim) is inherently fuzzy
in free text, so the UI always shows the claim text and the objective diff
side by side and lets the human make the final call for borderline cases —
this project computes the objective signal honestly and never pretends
false precision it doesn't have.

### 6.3 Chunk-level independent revert

A `Change` is reverted by re-applying its own recorded `old_html` to its
`chunk_id` via a normal `/v1/chat` edit instruction scoped to that chunk (or,
if the document hasn't changed since, by direct chunk substitution before
the next edit) — **not** by calling SuperDocs's session-level `/revert`,
which is deliberately never used for single-change undo because of 3.4.
Before applying: re-fetch the document's current chunk map and check the
target chunk's live content against what this Change last recorded as its
`resultingVersion`. Three cases:

- Live content still matches what this Change produced → safe, apply the
  revert.
- Live content has moved on (a later, different change touched the same
  chunk) → do not blindly overwrite; mark `conflicted`, show the reviewer
  what changed since, and require an explicit decision.
- Chunk no longer exists (deleted by a later change) → `conflicted`,
  same handling.

Reverting change B never touches change A's or C's chunks, because the
patch is scoped to B's own `chunk_id` — independence is structural, not
best-effort.

## 7. Data model

```ts
interface NormalizedTurnEvent {
  turnId: string;            // `${sessionId}:${turn_index}`
  sessionId: string;
  documentId: string;        // SuperDocs durable File id when known
  clientType: string;        // "unknown" unless SuperDocs exposes caller identity
  claimedIntentText: string; // the user-role message that started the turn
  claimedResultText: string; // the assistant's free-text reply
  beforeHtml: string;
  afterHtml: string;
  wasBillable: boolean;
  opsCharged: number;
  timestamp: string;
  correlationId: string;     // job_id when available, else turnId
}

interface Change {
  id: string;
  turnId: string;
  documentId: string;
  chunkId: string | null;         // null only for a `create` awaiting a chunk id
  operation: "edit" | "create" | "delete";
  beforeHtml: string | null;
  afterHtml: string | null;
  status: "proposed" | "approved" | "rejected" | "reverted" | "conflicted" | "failed" | "superseded";
  reconciliation: "match" | "partial" | "conflicting" | "claimed_not_observed" | "no_claim";
  aiExplanation: string | null;   // present for HITL-sourced changes
  createdAt: string;
  updatedAt: string;
  decidedBy: string | null;       // reviewer identity, once decided
  decidedAt: string | null;
}

interface AuditRecord {
  id: string;
  changeId: string;
  turnId: string;
  who: string;         // clientType + session owner
  what: string;         // operation + chunk summary
  when: string;
  where: { documentId: string; chunkId: string | null };
  claim: string;
  actual: string;       // objective diff description
  decision: "approved" | "rejected" | "reverted" | null;
  decidedBy: string | null;
  decidedAt: string | null;
  fromVersion: string | null;
  toVersion: string | null;
}
```

`Change.status` is a strict state machine (section 9); nothing in the UI
computes or infers status ad hoc — every transition goes through one
function, so status logic is never scattered across UI components (an
explicit brief requirement).

## 8. Event model

Internally, everything downstream of the Session Watcher consumes one
normalized shape (`NormalizedTurnEvent` above), regardless of whether it
originated from SSE streaming, REST polling, or a HITL `pending_changes`
payload. This is what makes the rest of the system — Chunk Differ, Claim
Reconciler, Change Store — genuinely agent- and transport-agnostic, rather
than agent-agnostic in name only while secretly branching on transport.

## 9. State transitions

```
        ┌─────────┐
        │proposed │
        └────┬────┘
    ┌─────────┼─────────┐
    ▼         ▼         ▼
approved   rejected   (superseded — a later change
    │                  on the same chunk arrives
    ▼                  before this one is decided)
reverted
    │
    ▼
(re-proposable only as a brand new Change,
 never by mutating a reverted record)

any state ──(revert-time conflict)──▶ conflicted ──(human resolves)──▶ approved | rejected
```

Rejected and reverted Changes are terminal and immutable; the audit log
entry is written once and never edited, only appended to (new
AuditRecord rows for later actions on the same Change).

## 10. Integration boundary — summary

One real integration: the SuperDocs REST API, over HTTPS, using a
user-supplied `sk_`/`lce_` key stored in VS Code's `SecretStorage` (never in
settings.json, never in source control — the repo's own `CONTRIBUTING.md`
ground rule, echoed in section 11). No coding-agent-specific code exists
anywhere in the codebase; the only "clients" this project knows about are
SuperDocs sessions.

## 11. Security model

- API key lives in VS Code `SecretStorage`, entered once via a command; never
  logged, never written to workspace settings, never included in the audit
  log or telemetry.
- Document HTML is treated as untrusted content for rendering: the review
  webview renders before/after HTML through the webview's sandboxed content
  security policy, never `eval`'d, never used to build shell commands.
- `ai_explanation` and claim text are displayed, never executed or
  interpolated into requests unescaped.
- No path traversal risk: this project does not read/write arbitrary
  workspace files as part of its core loop (documents live in SuperDocs);
  any optional local-file features (e.g., exporting a before/after diff to a
  temp file for VS Code's native diff view) write only inside the
  extension's own temp/storage directory, never an arbitrary path.
- Full detail deferred to `docs/SECURITY.md` (Phase 16), not yet written —
  named here so it isn't silently skipped later.

## 12. Failure model

Mapped against the brief's required failure list, grounded in section 3.5's
real error codes rather than invented ones:

- **Duplicate/out-of-order/delayed events** — irrelevant in the form the
  brief describes, because this project does not consume a push feed as
  primary source of truth; it polls authoritative, monotonic `turn_index`
  state and de-dupes against what's already persisted (12.1).
- **Stale document version / concurrent modification** — handled by the
  live-content check in 6.3, and by SuperDocs's own `chunks/{id}/re-edit`
  conflict primitive where applicable to the underlying document itself.
- **429 (quota/rate limit)** — honor `Retry-After`; surface remaining quota
  from the `usage` block already present on every chat response, no extra
  call needed; never silently retry a state-changing call (approve/revert)
  without an idempotency check first.
- **409 on revert** (a job is mid-flight or awaiting approval on that
  session) — surfaced as "resolve the pending job first," not retried
  blindly.
- **504 timeout on long edits** — expected on `/v1/chat`; this project
  always uses `/v1/chat/async` for anything it initiates itself (revert
  patches included) precisely to avoid this class of failure.
- **Extension/VS Code restart** — pending review state is not
  reconstructed from memory; it's read back from the persisted Change Store
  (section 11) and, for genuinely in-flight SuperDocs jobs, re-discovered via
  `GET /v1/sessions/{id}/jobs` on startup (documented as recoverable by
  SuperDocs itself for `awaiting_approval` jobs).
- **Review decision submitted twice** — Change transitions are guarded by
  current-status checks (9); a second approve on an already-approved Change
  is a no-op, not a duplicate audit entry.
- **Authentication failure** — a 401 surfaces as an explicit "reconnect your
  SuperDocs account" state in the VS Code UI, never a silent stall.

### 12.1 Idempotency

`turnId` (`sessionId:turn_index`) is the natural idempotency key for turn
ingestion; `Change.id` is derived deterministically from `turnId + chunkId +
operation` so re-processing the same turn (e.g. after a restart) upserts
rather than duplicates.

## 13. Testing strategy

Unit tests for: chunk-map diffing (edit/create/delete, adjacent and
overlapping chunk edits), claim reconciliation verdicts (all five cases in
6.2), the Change state machine (every legal and illegal transition), and
revert conflict detection. Integration tests against a recorded/mocked
SuperDocs API surface (fixtures captured from the real response shapes
documented in section 3, not invented shapes) for: session discovery,
HITL pending-change ingestion, approve/reject round-trips, and the
independent-revert scenario end to end. The ten mandatory acceptance tests
from the brief map directly onto this suite; each is implemented as a named
test, not just implied by smaller units, so "tests pass" is checkable per
acceptance criterion.

## 14. Demo strategy

Follows the brief's 15-step script directly (section 3 gives every piece it
needs: a real SuperDocs account, a real document, real auto-apply and real
HITL turns, a real claimed-but-not-observed case manufactured by asking the
AI to edit a chunk that doesn't exist so the reply necessarily claims work
with zero diff, real independent revert). Deferred to `docs/DEMO.md` with a
recorded script once the implementation exists to script against.

## 15. Known limitations / open questions

Stated honestly, to be resolved empirically in Phase 2 against a real
SuperDocs account rather than guessed here:

- Whether SuperDocs's turn/job metadata exposes any caller-identity field
  (MCP client name, user agent, etc.) is not confirmed from the docs read so
  far. If it doesn't, `clientType` is honestly `"unknown"` — still fully
  agent-agnostic, just without a friendly label.
- The exact shape of `document_changes` on a plain synchronous `/v1/chat`
  response (whether it's whole-document HTML only, or also carries some
  chunk-level hint) needs confirming against a live call; section 3.3's
  design assumes the conservative case (whole HTML only) and builds its own
  differ so it isn't blocked either way.
- Free-tier quota (500 ops/month) is small relative to a full test +
  demo run against a live account; the test suite is designed to run
  primarily against recorded fixtures for that reason, with a small number
  of live smoke tests.
- No webhook/push mechanism is documented for SuperDocs; the polling
  interval is a real trade-off between responsiveness and both API quota
  and VS Code extension-host resource use, tuned empirically rather than
  guessed at a single "correct" number here.
