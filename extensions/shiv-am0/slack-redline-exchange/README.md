# Slack Redline Exchange

Cross-company contract negotiation inside a shared Slack Connect channel, built on the
SuperDocs API. A vendor and a customer drop a contract into a shared channel; each side
proposes edits, both sides approve their own side of the negotiation, and the app keeps
one authoritative current version with a full audit trail. Internal-only commentary
never crosses into the shared channel. The final export carries the whole negotiation
as OOXML track changes for the lawyers.

Built for the SuperDocs engineering task, assigned card: *Slack Connect cross-company
redline exchange*.

![A proposal card in the shared Slack channel: the proposed edit with its before and
after text, per-side approve and reject buttons, and the committed outcome
below.](docs/screenshot.png)

## What SuperDocs does here

This app is a broker, not a second AI. Every edit is drafted by SuperDocs; this codebase
decides who may ask for one, who must agree before it lands, and what may never be said
in front of the other company.

| SuperDocs surface | Used for |
| --- | --- |
| `POST /v1/documents/upload-base64` | Opening a session when a contract is dropped in the channel; supporting documents are added with `open_mode: background` so they never steal focus |
| `POST /v1/chat/async` | Handing a plain-English instruction to the drafting AI, targeted at one document in a multi-document session |
| `GET /v1/jobs/{job_id}` | Polling to a turnpoint, with progress posted into the Slack thread on slow jobs |
| `POST /v1/chat/{session}/approve` | Submitting the whole batch of per-change decisions once both sides have voted |
| `POST /v1/chat/{session}/continue` | Answering SuperDocs when it pauses mid-run |
| `POST /v1/documents/export` | The clean export — the negotiated document as it now stands |

Review mode (`approval_mode: ask_every_time`) is what makes dual consent possible at all:
changes are held as proposals until a human decides, and this app simply requires *two*
humans from different companies instead of one.

The redline export is deliberately **not** a SuperDocs call. It is rebuilt locally from
the original bytes plus the recorded decisions, so the negotiation trail survives even
if the API is unreachable.

## Quickstart

```bash
uv sync --extra dev
uv run python demo/run_demo.py   # full negotiation, keyless, against the built-in fake
uv run pytest                    # 119 tests, all offline, no live key required
```

That is the one documented command a stranger needs: `uv run python demo/run_demo.py`
prints a complete negotiation — proposal cards, dual approval, a blocked leak attempt,
multi-document attachment, boundary-aware search, exports, audit trail, and a
kill/resume — and writes `.docx` exports to `demo/output/`.

Other entrypoints:

```bash
uv run uvicorn redline.main:app --reload        # machine-drivable REST surface + /docs
uv run python -m redline.slack.run_slack        # the real Slack app (needs .env, see below)
uv run python scripts/make_demo_docs.py         # regenerate the synthetic demo contracts
uv run ruff check src tests --fix
```

### Configuration

`.env.example` is a **template and is never read by the app**. Settings resolve in this
order: real environment variables → `.env` → the defaults in [config.py](src/redline/config.py).
With no `.env` present, the defaults apply — including `FAKE_MODE=true`, which is why the
entire test suite and demo run with no key and no network. To go live:

```bash
cp .env.example .env    # then fill it in; .env is gitignored
```

## Running it live, end to end (real Slack + real SuperDocs)

Everything below is optional — the demo and tests prove the same behavior offline — but
this is how to watch it work for real.

### 1. Get a SuperDocs key

Sign up at [use.superdocs.app](https://use.superdocs.app), then create an API key. Your
agent can also self-enroll via `POST /v1/agents/signup` and check itself with
`GET /v1/agents/whoami` (see [docs.superdocs.app](https://docs.superdocs.app)). Put the
key in `.env` as `SUPERDOCS_API_KEY` and set `FAKE_MODE=false`.

Once live, every deal creates a SuperDocs **session** holding the authoritative document,
so you can open [use.superdocs.app](https://use.superdocs.app) and watch the document,
its version history, and pending review-mode changes update as the negotiation runs. In
`FAKE_MODE=true` nothing leaves your machine and the UI stays empty — that is expected.

### 2. Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → *From scratch*.
2. **Socket Mode** → toggle **Enable Socket Mode** on. This is why no public URL or
   ngrok tunnel is needed: the app dials out over a WebSocket.
3. **Basic Information → App-Level Tokens** → *Generate Token* with the
   `connections:write` scope → copy the `xapp-…` value into `SLACK_APP_TOKEN`.
4. **OAuth & Permissions → Bot Token Scopes**, add:
   `commands`, `chat:write`, `files:read`, `files:write`, `channels:history`,
   `groups:history`, `channels:read`, `groups:read`.
5. **Slash Commands** → *Create New Command* → `/redline`, any description. (With Socket
   Mode on, the Request URL field is not used.)
6. **Event Subscriptions** → enable → **Subscribe to bot events**: `file_shared`, `message.channels`.
7. **Install to Workspace**, then copy the **Bot User OAuth Token** (`xoxb-…`) into
   `SLACK_BOT_TOKEN`.

### 3. Create the channels

Create three channels and invite the bot to each (`/invite @your-app`):

| Channel | `.env` variable | Purpose |
| --- | --- | --- |
| `#deal-acme-globex` | `SHARED_CHANNEL` | both companies; cards and versions land here |
| `#vendor-internal` | `VENDOR_INTERNAL_CHANNEL` | vendor-only commentary |
| `#customer-internal` | `CUSTOMER_INTERNAL_CHANNEL` | customer-only commentary |

Put the **channel IDs**, not names, in `.env` — open a channel, click its name, and copy
the ID from the bottom of the About tab (starts with `C`).

**Two workspaces vs one.** Real Slack Connect means two separate workspaces, one per
company, and the app decides your side from your workspace (`team_id`). If you only have
one workspace, set `VENDOR_TEAM_ID` and `CUSTOMER_TEAM_ID` to that same team ID and use
`SIDE_OVERRIDE_USERS` to pin specific users to each side:

```
SIDE_OVERRIDE_USERS=U01ALICE:vendor,U02BOB:customer
```

This is a testing affordance only; the workspace mapping remains the real mechanism.

### 4. Run it and watch

```bash
uv run python -m redline.slack.run_slack
```

It validates the configuration first and refuses to start with an exact list of what is
missing and where to find it. On start it logs the resolved channels, policy, and
database path, and resumes any job left in flight by a previous run.

Then, in Slack:

1. Drag a `.docx` contract into the shared channel → the bot opens a deal and posts the
   deal ID. (A second file dropped later attaches as a supporting document rather than
   replacing the contract.)
2. `/redline propose <deal_id> Cap liability at $50k in the liability section`
3. Watch the proposal cards appear with per-side Approve/Reject buttons. Slow jobs post
   a "still working" note rather than going silent.
4. Click **Approve (Vendor)** then **Approve (Customer)** → the change commits and the
   version bumps. Under `dual_consent`, one approval alone is not enough.
5. `/redline note <deal_id> our real walkaway is $250k` **from your internal channel** —
   it stays there. Try `/redline propose` from the internal channel and watch it get
   refused.
6. `/redline search <deal_id> liability`, `/redline docs <deal_id>`,
   `/redline history <deal_id>`, `/redline export <deal_id> redline`.

**Monitoring while it runs.** The process logs every command, decision, and error at
INFO. For state, the SQLite database is directly inspectable at any time:

```bash
sqlite3 redline.db "SELECT ts, side, actor, action FROM audit_log ORDER BY seq;"
sqlite3 redline.db "SELECT id, state, vendor_decision, customer_decision FROM proposals;"
sqlite3 redline.db "SELECT job_id, state, instruction FROM jobs;"
```

The REST surface can be run at the same time against the same `DATABASE_PATH` to read
status/history while Slack drives the negotiation.

## What it does

1. **One authoritative document per deal.** A single SuperDocs session backs the whole
   negotiation. Middleware (this app) mediates every read and write; neither side talks
   to SuperDocs directly.
2. **Cards visible to both sides.** Each proposed change becomes a Block Kit card in the
   shared channel with per-side Approve/Reject buttons. Both workspaces see the exact
   same card, the exact same version number, at all times.
3. **Configurable approval policy.** `dual_consent` (default) commits a change only when
   both sides approve it; any rejection is sent to SuperDocs with the rejecting side's
   feedback attached. `proposer_only` commits on the proposing side's approval alone —
   the counterparty's decision is recorded for the audit trail but doesn't gate.
4. **Internal notes stay internal.** `/redline note` (or `add_internal_note`) posts only
   to the author's own internal channel and is stored separately from anything ever sent
   to the shared channel or to SuperDocs.
5. **Runtime boundary enforcement.** Every outbound message to the shared channel is
   checked against every stored internal note before it is sent (`core/boundary.py`).
   Every edit instruction must provably originate from the shared channel; anything from
   an internal channel is refused before it ever reaches SuperDocs, and the refusal is
   reported back to the acting side's own internal channel only.
6. **Survives being killed.** All negotiation state (jobs, proposals, decisions, audit
   log) lives in SQLite. `NegotiationService.recover_pending()` re-drives any job that
   was mid-flight and re-posts only the Slack cards that are missing (`card_ts IS NULL`)
   — nothing is duplicated, nothing already-finished is lost. See
   `tests/test_kill_resume.py`.
7. **Machine-drivable end to end.** The FastAPI surface in `api/routes.py` exposes the
   same four SuperDocs-shaped primitives — start a deal, propose, decide (approve),
   export — plus status/history/notes, so a script can run the whole negotiation with no
   human clicking through Slack. See `tests/test_rest_surface.py`.
8. **Lawyer-facing export.** `export/track_changes.py` builds a docx locally from the
   original source file plus the recorded negotiation trail: committed changes become
   real OOXML `w:ins`/`w:del` runs attributed to "Vendor" or "Customer"; rejected
   proposals go into an honest appendix table with the feedback that killed them;
   anything we can't confidently place gets its own "Unmatched Changes" section instead
   of a guess. Additions are positioned with the `insert_after_chunk_id` anchor SuperDocs
   returns, so a new clause lands where it belongs rather than at the end of the file.
   See `tests/test_export_anchors.py`.
9. **Multi-document deals.** A deal holds one authoritative contract plus any number of
   supporting documents (amendments, SOWs, counterparty markups). Supporting files join
   the same SuperDocs session using `open_mode=background`, so they are editable and
   searchable while the contract stays focused — an untargeted `/redline propose` always
   edits the contract, never whatever was uploaded most recently. Target another document
   explicitly with `--doc <name>`. See `tests/test_multidocument.py`.
10. **Boundary-aware search.** `/redline search <deal_id> <query>` searches document text,
    proposals, and the audit trail. The same boundary rule applies to reads as to writes:
    a search from the shared channel can only ever return shared material, and internal
    notes are reachable only from an internal channel — and then only that side's own
    notes. One side can never search the other's commentary. See `tests/test_search.py`.
11. **Progress reporting on slow jobs.** SuperDocs documents that large documents can take
    thirty seconds to several minutes with no visible progress. Rather than let the
    channel go silent (and look crashed), the app posts a "still working, this is not a
    failure" note. A failed progress ping is recorded in the audit trail and never aborts
    an otherwise healthy job. See `tests/test_progress.py`.
12. **Proposing twice does not pay twice.** `propose` is the call that spends a SuperDocs
    operation, so it is guarded by an idempotency key derived from
    `(deal_id, document_id, instruction)` — normalised for whitespace and case — or
    supplied by the caller. A repeat folds into the in-flight job instead of starting a
    second one, and the fold is written to the audit trail as `propose_deduplicated`
    rather than hidden. Jobs still awaiting review dedupe regardless of age; finished
    ones only inside `IDEMPOTENCY_WINDOW_SECONDS` (default 120), because re-proposing the
    same clause later in a negotiation is legitimate work. See `tests/test_idempotency.py`.

## Architecture

```
Slack (real)                     Simulator (tests/demo)
     |                                  |
     v                                  v
 bolt_app.py  ─┐                ┌─ simulator.py
 (thin Bolt    │                │  (in-memory two-workspace
  adapter)     │                │   fake Slack)
               │                │
               └──────┬─────────┘
                      v
                handlers.py           (framework-free: plain dicts in, plain dicts out)
                      |
                      v
             core/negotiation.py      (NegotiationService — all business logic)
              /        |        \
             v         v         v
     core/store.py  core/boundary.py  slack/cards.py
     (SQLite:       (runtime leak &   (Block Kit builders,
      deals, jobs,   provenance       used both for posting
      proposals,     guards)          and for the leak check)
      audit log,
      internal notes)
                      |
                      v
           superdocs/client.py  ──►  FakeSuperDocs (tests/demo)
           (SuperDocsClient)    ──►  real SuperDocs REST API (production)

  api/routes.py + main.py: FastAPI wrapping NegotiationService for machine-driven use
  export/track_changes.py: original docx + resolved proposals -> lawyer-facing redline
```

`NegotiationService` is framework-free: it depends only on `Store`, `SuperDocsClient`,
and a `MessengerPort` protocol (`post_message` / `update_message` / `upload_file`).
Three things implement `MessengerPort`: `SlackMessenger` (real Bolt client, thin),
`InMemoryMessenger` (tests, demo, and the REST server), and nothing else — the whole
negotiation state machine, boundary guard, and approval logic is exercised identically
whether it's driven by real Slack, the simulator, or the REST API.

## Locked design decisions (and the reasoning)

These were fixed before implementation and are echoed here so the reasoning survives
in one place, not just in commit history.

- **One SuperDocs session per deal, one middleware.** Neither side ever calls SuperDocs
  directly; this app is the only client of the SuperDocs session for a given deal, which
  is what makes "both sides always see the same version" a property of the architecture
  rather than something we have to reconcile after the fact.
- **`dual_consent` reading of "each side approves its own positions."** The brief says
  "each side's proposed changes appear as cards visible to both, each side approves its
  own positions." We read this as: by default, a change only takes effect once *both*
  sides have signed off on it (`dual_consent`); `proposer_only` is offered as the more
  literal reading (a side only ever needs to approve what it itself proposed) for
  negotiations where the parties want unilateral commit rights. This is a
  policy field on the deal, not a hardcoded assumption — configurable per-deal.
- **REST only, MCP deliberately skipped.** The assigned card names both REST and MCP as
  acceptable surfaces ("anything specified against the REST API may be built on MCP, and
  the other way around"). We built the SuperDocs-facing client (`superdocs/client.py`)
  once, against the documented REST endpoints, and exposed our *own* machine interface
  as REST (`api/routes.py`) rather than as an MCP server, because the task's minimum
  contract is four calls (upload, chat, approve, export) and REST gets us there with far
  less scaffolding than standing up an MCP server for a single-deal negotiation flow.
  Given the time budget, we judged the boundary/approval/resume correctness work more
  valuable than a second protocol adapter around the same four calls.
- **Simulator-first.** All business logic in `core/negotiation.py` is plumbing-free: it
  never imports `slack_bolt`. `slack/simulator.py` drives the exact same
  `slack/handlers.py` functions the real Bolt adapter uses, through an in-memory
  two-workspace fake Slack. Every test in this repo — including the ones that exercise
  Slack Connect's two-sided visibility — runs with `FAKE_MODE=true` and no real Slack
  connection, which is also what makes the whole suite keyless.
- **Boundary guard is runtime enforcement, not a lint pass.** `core/boundary.py` is
  called on the hot path of every outbound shared-channel message and every incoming
  edit instruction. It is not a code-review checklist; a violation raises, is logged to
  the audit trail as `boundary_violation_blocked` / `propose_refused`, and is reported
  to the acting side's own internal channel — never to the shared channel, and never
  silently swallowed.
- **The idempotency key is derived, not demanded.** The obvious design is to require
  callers to send a key. That protects a disciplined script and does nothing for the
  double-clicked slash command, which is where the money actually leaks. So the key is
  computed from the deal, the target document and the normalised instruction, and a
  caller-supplied key overrides it when the caller wants to define sameness itself. The
  cost of deriving it is that two genuinely-intended identical proposals inside the
  window collapse into one; the window is deliberately short, and jobs already in review
  dedupe regardless of age because the humans still owe a decision on that exact change.

- **Track-changes export is generated locally.** SuperDocs's own `/documents/export`
  gives us the current clean version. The lawyer-facing redline is built by this app,
  locally, from the original uploaded bytes plus the locally-recorded proposal/decision
  trail — nothing about the redline export depends on a SuperDocs feature that doesn't
  exist yet.

## Approval policy, precisely

For a single proposal:

- `dual_consent`: the proposal is "ready" once *both* `vendor_decision` and
  `customer_decision` are recorded. It commits only if both are `approved`. If either
  side rejects, the rejecting side's feedback (if any) is sent to SuperDocs alongside the
  decision. If every proposal in that job's batch is rejected and at least one carries
  feedback, SuperDocs runs its own revision round and we re-post new cards for the
  revised proposals; if at least one proposal in the batch was approved, the rejected
  ones are simply discarded and marked `rejected` (no revision). **The revision round is
  only reachable over REST today**: the Slack buttons record approve/reject but never
  collect a reason, so a rejection driven from Slack carries no feedback and SuperDocs
  has nothing to revise against. See the cut below.
- `proposer_only`: the proposal is "ready" once the *proposing* side has decided.
  Only that side's decision determines commit/reject. The counterparty may still click
  Approve/Reject — it's recorded in the audit trail and shown on the card — but it does
  not gate.

## What formats and domains this accepts

Source documents: `.docx`, `.md`, `.txt`, `.html`/`.htm` (via `FakeSuperDocs`'s parser in
tests/demo; the real SuperDocs API's own format support applies in production).
**Inline OOXML track-changes in the redline export require a `.docx` original** — for any
other format the export still succeeds, but the negotiation trail is rendered as an
appendix rather than as inline `w:ins`/`w:del` marks on the original prose (see
`export/track_changes.py`; covered by `tests/test_export_trail.py`).

Domain: this build is deliberately domain-agnostic (any contract/agreement-shaped
document); the demo uses a synthetic Master Services Agreement between two fictional
companies, Acme Corp and Globex Ltd. A second run with different documents just means
uploading a different `.docx`/`.md`/`.txt`/`.html` file to `/redline` or `POST /deals` —
nothing in the negotiation logic is specific to the demo contract's clauses.

## What we cut, and why

- **The Slack upload path reads the whole file into memory.** `POST /deals/upload` on the
  REST surface streams in chunks with an explicit size cap, but the Slack `file_shared`
  handler downloads the document whole before uploading it. Fine for contracts, which are
  small; not what you would want for genuinely large files, and named here rather than
  implied by the presence of the streaming path next to it.
- **No stage-by-stage cost/latency reporting.** This build's assigned card didn't ask
  for it, and SuperDocs already meters usage via its own operations budget
  (`usage.monthly_used` / `monthly_remaining` on every job). Adding a second cost ledger
  on top would have been scope creep against the S3 card; noted here as an honest cut,
  not an oversight.
- **Rejection feedback cannot be given from Slack.** `decide` takes a `feedback`
  argument, it is stored on the proposal, and it is sent to SuperDocs with the rejection
  -- and the REST surface exposes it. The Slack cards do not: the buttons submit a
  decision with no reason attached. Because SuperDocs uses that reason to decide whether
  to draft a revision, the revision round is in practice unreachable from the Slack
  surface, which is the one most people will use. A modal on reject is the fix; it is
  named here rather than left for a reader to discover, because a capability that works
  on one surface and silently not on another is worse than one that is honestly absent.
- **No revision-round UI beyond what SuperDocs itself drives.** When `dual_consent`
  triggers SuperDocs' automatic revision round (every change in a batch rejected, with
  feedback), we re-post the new proposal cards SuperDocs drafts; we don't build a second,
  separate "counter-proposal" negotiation UI on top of that.
- **The REST server posts to an in-memory messenger, not real Slack.** `main.py` is the
  machine-drivable surface; it does not require a live Slack connection to run or to be
  tested. A real deployment runs `redline.slack.run_slack` as a separate process against
  the same `DATABASE_PATH` and the same SuperDocs session per deal, so both surfaces stay
  consistent — but the REST server, by itself, never posts into real Slack. This is a
  deliberate assumption, not a bug: the REST/MCP surface's job is to be drivable by a
  machine with no human in Slack at all.
- **Search is lexical (substring), not semantic.** It matches case-insensitive substrings
  across document text, proposals, and the audit trail. It will not find "indemnity" when
  you search "who pays if we get sued". SuperDocs exposes a `cross_session_search` flag on
  chat that our client passes through, and Postgres + pgvector is the natural upgrade if
  semantic recall is needed — but a lexical index is honest about what it does, needs no
  embedding budget, and is fully testable offline. Documented as a limitation rather than
  dressed up as semantic search.
- **Search reads original uploaded bytes, not the current version.** Document hits come
  from the file as uploaded; if a clause was later edited, the *proposal* records show the
  change but the document snippet shows the original text. Proposal and audit hits close
  most of that gap, and every hit is labelled by kind so the reader can tell which is
  which.
- **`SIDE_OVERRIDE_USERS` is a testing affordance.** In production the workspace a person
  belongs to (`team_id`) decides their side. The override exists so both roles can be
  exercised from a single Slack workspace during development; it is validated (an unknown
  side is rejected loudly) and covered by `tests/test_identity.py`.

## Assumptions

Logged as the brief asks, rather than waiting for clarification:

- **"Each side approves its own positions"** is read as `dual_consent` by default (both
  sides must approve before a change commits), with `proposer_only` available as the more
  literal reading. Configurable per deal.
- **A second file shared into the channel attaches to the open deal** as a supporting
  document rather than starting a new deal or replacing the contract. Replacing the
  authoritative contract mid-negotiation would silently invalidate every recorded
  decision, so it is not something a drag-and-drop should be able to do by accident.
- **An untargeted `propose` always edits the contract**, never the most recently uploaded
  file, even though SuperDocs' own focus would follow the newest upload. This is enforced
  by `open_mode=background` plus explicit document resolution, and tested.
- **Errors from Slack interactions reply ephemerally to the actor**, never into the shared
  channel — broadcasting one side's operational errors to the counterparty leaks how that
  side is driving the negotiation.
- **Deal identity is the SuperDocs session id.** One deal = one session = one
  authoritative document plus its supporting files.

## Testing

```bash
uv run pytest          # 119 tests
uv run ruff check src tests --fix
```

All tests run offline against `FakeSuperDocs` and `InMemoryMessenger` — no network, no
API key, no real Slack. Coverage by requirement:

| Requirement | Test |
| --- | --- |
| Boundary never leaks internal notes | `tests/test_boundary.py` |
| Documents can't give the system orders | `tests/test_boundary.py::test_document_content_never_treated_as_a_command` |
| Approval policy matrix (`dual_consent` / `proposer_only`) | `tests/test_approval.py` |
| Both sides see one identical, monotonic version | `tests/test_versioning.py` |
| Kill mid-run, resume, exactly-once completion | `tests/test_kill_resume.py` |
| Track-changes export, authors, rejected appendix, unmatched | `tests/test_export_trail.py` |
| Append-only, attributable audit trail | `tests/test_history_audit.py` |
| Full negotiation drivable end-to-end via REST, multipart upload | `tests/test_rest_surface.py` |
| Multi-document deals, targeting, contract stays untouched | `tests/test_multidocument.py` |
| Search respects the internal/external boundary both ways | `tests/test_search.py` |
| Slow jobs report progress; a failed ping never breaks a job | `tests/test_progress.py` |
| Side identity, overrides, and forged cross-side decisions | `tests/test_identity.py` |
| Real HTTP transport: auth, payload shapes, error mapping | `tests/test_live_transport.py` |
| SuperDocs client / fake behavior (from the prior phase) | `tests/test_superdocs_client.py` |
| Proposing twice bills one operation, and the fold is audited | `tests/test_idempotency.py` |
| Added clauses land at their anchor; unanchored ones are reported | `tests/test_export_anchors.py` |
| Deal lifecycle: second document joins, close, promote the authoritative contract | `tests/test_deal_lifecycle.py` |
| Two real workspaces: per-side tokens, per-workspace file ingest | `tests/test_two_workspace.py` |
| Decision outcomes reach both sides; a failed notification never undoes a decision | `tests/test_notifications.py` |
| Block Kit buttons match their listeners; a wrong-side click warns without destroying the card | `tests/test_bolt_wiring.py` |
| Readable deal names, countable version numbers, older databases migrate | `tests/test_display.py` |

Two artifacts in `docs/` are generated rather than written, so you can regenerate them
instead of trusting mine:

```bash
uv run pytest -v > docs/test-log.txt                          # 119 tests, offline
uv run python scripts/capture_rest_transcript.py > docs/rest-transcript.md
```

`docs/rest-transcript.md` drives a whole negotiation over the REST surface against the
built-in fake — upload, propose, the same propose again (folded by the idempotency key
into one billed operation), both approvals, status, audit trail — and prints every
request and response body verbatim. No key, no network, no human in Slack.

`tests/test_live_transport.py` is worth calling out: `FakeSuperDocs` replaces the
transport entirely, so it can never catch a bug in how we actually speak HTTP. That file
drives the real `HTTPTransport` against a mock server to check bearer auth, request
shapes, and error mapping — still with no key and no network.

## Repo layout

```
src/redline/
  config.py             Settings (pydantic-settings), side/channel resolution, overrides
  core/
    store.py             SQLite persistence + idempotent column migrations
    boundary.py          runtime leak & provenance guards
    search.py            boundary-aware search over documents/proposals/audit
    documents.py         best-effort text extraction for the search index
    negotiation.py       NegotiationService: all business logic, framework-free
  slack/
    cards.py             pure Block Kit builders + flatten_blocks_text for the guard
    handlers.py          framework-free handlers: plain dicts in, plain dicts out
    simulator.py         in-memory two-workspace fake Slack, drives handlers.py
    bolt_app.py          real-Slack adapter (Bolt AsyncApp) + SlackMessenger
    run_slack.py         Socket Mode entrypoint with config validation
  export/
    track_changes.py     original docx + resolved proposals -> OOXML redline docx
  superdocs/             SuperDocsClient, FakeSuperDocs (multi-document), transport
  api/routes.py          FastAPI machine surface (JSON + multipart, search, documents)
  main.py                FastAPI app wiring + lifespan recovery
scripts/make_demo_docs.py  generates the synthetic demo contracts (committed)
demo/
  Acme_Globex_MSA.docx            synthetic source contract (committed)
  Acme_Globex_Amendment_1.docx    synthetic supporting document (committed)
  run_demo.py                     full walkthrough incl. leak attempt, search, resume
  output/                         generated exports (gitignored except .gitkeep)
tests/                   119 tests, all offline
```
