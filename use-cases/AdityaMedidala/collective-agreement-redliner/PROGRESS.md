# PROGRESS.md

## Current phase

**Phase 4 done — minimal review UI, manually verified against the live
API.** `frontend/` is a new Vite + React app reusing Task 1's `App.css`
verbatim (coral accent, card treatment, diff-chip pattern) plus a small
set of additions for elements Task 1 never needed (upload form, decision-
toggle active state, tracker status badges with REOPENED visually
distinct). Zero backend changes. Walked the full flow against the real
SuperDocs API in a real browser and found three more real bugs (see
"Phase 4 UI bugs found live" below) — none in the backend, all in how the
UI handled states the backend can legitimately return.

## Phase plan

- [x] **Phase 0 — Scaffold.** Done.
- [x] **Phase 1 — SuperDocs client.** `superdocs_client.py` was already
      fully implemented entering the Phase 1 session (upload document,
      upload attachments, start_round, get_job, approve_changes,
      get_session_jobs, export, parse_pending_changes). That session:
      implemented `negotiation_service.start_negotiation` (generates a
      session_id, uploads CBA as document + union/employer as attachments,
      polls attachment jobs to completion, persists a `Negotiation` row)
      and `round_service.start_round` / `list_pending_changes` (persists a
      `Round` row at status=pending, polls the chat/async job until it
      leaves pending/processing, updates status to match). Wired
      `POST /negotiations`, `POST /negotiations/{id}/rounds`, and
      `GET /rounds/{id}/pending-changes` to call them.
- [x] **Phase 2 — Round decisions.** `round_service.decide` looks up the
      round's negotiation for `superdocs_session_id`, calls
      `client.approve_changes(session_id, decisions)`, then polls the
      round's existing `superdocs_job_id` (not a new one — the approve
      call doesn't return its own job_id per the API reference) until
      status leaves pending/processing/awaiting_approval, and updates the
      `Round` row. Wired `POST /rounds/{id}/decisions` (404s on unknown
      round via `ValueError` → `HTTPException`). Also wired
      `GET /negotiations/{id}/export`: looks up the `Negotiation`, calls
      `client.export(session_id, format)`, returns a real `Response` with
      format-specific `Content-Type` (docx/pdf/html/txt, else
      `application/octet-stream`) and a `Content-Disposition` header.
      Extracted the polling loop (previously duplicated in
      `negotiation_service.py` and `round_service.py`) into
      `app/services/polling.py::poll_job` — both existing call sites and
      `decide`'s new one now share it. 15/15 tests pass, respx-mocked,
      zero live calls — see test run below.
- [x] **Phase 3 — Open-items tracker.** The graded part.
      `round_service.upsert_proposed_item` (hooked into
      `list_pending_changes`) creates an `OpenItem` per new chunk_id at
      `OPEN`, or flips it to `REOPENED` (updating `last_round_id`, keeping
      `first_round_id`) if it was previously `APPROVED`/`REJECTED` — the
      core contract this card grades. `round_service.upsert_decided_item`
      (hooked into `decide`) sets `APPROVED`/`REJECTED` and
      `last_round_id` after a successful `approve_changes` call.
      `tracker_service.reconcile`: primary path reads local `OpenItem`
      rows directly (fast, idempotent — no API call, no writes if rows
      already exist); if a negotiation has `Round` rows but zero local
      `OpenItem` rows (DB-loss scenario), it rebuilds by replaying
      `get_session_jobs` chronologically through the *same* upsert
      helpers, so the reopen logic isn't duplicated. 24/24 tests pass,
      respx-mocked, zero live calls (see test run below) — including the
      multi-round reopen scenario, idempotency, and the local-wipe
      rebuild. See "raised_by limitation" and "get_session_jobs shape"
      entries below.
- [x] **Phase 4 — Review UI.** `frontend/` — Vite + React, `App.css`
      copied verbatim from `doctask-medidala/frontend/src/App.css` per
      the brief, then extended (not redesigned) with a handful of new
      rules for elements Task 1 never had: a file-upload form, a
      decision-toggle "active" state, and tracker status badges. Three
      tabs (Negotiations / Round / Open Items) instead of Task 1's
      sidebar+tabs layout, since the brief asked for tabs specifically
      and there's no negotiations-listing backend endpoint to page a
      sidebar against (see "no negotiations list endpoint" below).
      Pending-change cards reuse the diff-chip pattern
      (`old_html`/`new_html` stripped to plain text via `DOMParser`,
      since Phase 3 found those are real HTML fragments, not the
      JSON-string `content` field the pattern was written against).
      Decisions are staged client-side per item (approve/reject toggle)
      and submitted as one batch — not one-shot per click like Task 1 —
      because `decide()` polls to `completed` every call, and a partial
      batch never reaches `completed` (this is real backend behavior,
      confirmed live in the earlier session, not a guess). REOPENED
      items get a tinted card + stronger shadow, not just a badge color,
      per the explicit "don't bury it" requirement. Export button
      fetches the blob and triggers a real browser download. Manually
      verified against the live API end to end — see "Phase 4 manual
      verification" below for what was actually observed, including
      three real UI bugs found and fixed during the walkthrough.
- [x] **Phase 5 — Live verification (pulled forward from after Phase 4).**
      A real key was added to `.env` mid-build, so this ran now instead of
      waiting. Confirmed a real negotiation, round, and decision batch
      end-to-end against the live platform, and the tracker rebuild
      (`tracker_service.reconcile`) against real `get_session_jobs` data.
      Found and fixed three real bugs — see "Live verification" entry
      below. 24/24 offline tests still pass (zero live calls by default);
      `tests/live/test_tracker_resilience_live.py` passes when run with
      `REDLINER_LIVE_CALLS=1`.
- [ ] **Phase 6 — README polish, PR into superdocs-builds/use-cases/.**

## Assumptions & decisions log

### 2026-08-12 — Domain: synthetic manufacturing-sector CBA
Picked over other industries because it's easy to write two genuinely
disagreeing position papers (wage scale, grievance timeline, overtime
rules) without needing real labour-law expertise to make them plausible.

### 2026-08-12 — Positions as attachments, not documents
The CBA draft is the one editable working document; union/employer
positions are read-only attachments the AI references but never edits.
This matches the platform's own attachment-vs-document distinction exactly
and avoids any ambiguity about which document a "redline" targets.

### 2026-08-12 — SQLite + sync SQLAlchemy, deliberately
Task 1's single biggest recurring bug class was async engines binding to
the wrong event loop across pytest-asyncio's per-test loops. This build is
small enough that sync SQLAlchemy avoids the whole bug class rather than
managing it carefully. Revisit only if a real performance need appears.

### 2026-08-12 — Attachment job result shape assumed, not documented
`docs/superdocs-api-reference.md` says attachment upload is async, poll
`get_job` until `status=completed`, but doesn't specify where the resulting
attachment id lives in the completed job response. Assumed
`result.attachment_id`, falling back to `result.id`, then a top-level
`attachment_id` (`negotiation_service._extract_attachment_id`). Revisit
once Phase 5's live call shows the real shape.

### 2026-08-12 — Round terminal statuses: awaiting_approval/completed/failed
`round_service` treats `pending`/`processing` as non-terminal and
everything else as terminal, matching the existing `RoundStatus` enum. A
poll that never leaves pending/processing is capped at 30 attempts and the
round is marked `failed` rather than looping forever — guards against the
exact stuck-polling bug Task 1 hit.

### 2026-08-12 — decide() polls the round's original job_id, not a new one
The API reference says "Poll GET /v1/jobs/{job_id} *again*" after approving
— read that as: the approve endpoint doesn't hand back a fresh job_id, the
original chat/async job from `start_round` keeps moving through statuses
after decisions are applied. `decide()` reuses `round.superdocs_job_id`
rather than trying to parse one out of `approve_changes`'s response.
**Confirmed correct live** — see "Live verification" entry below.

### 2026-08-12 — Polling factored into app/services/polling.py
`negotiation_service` (attachment uploads) and `round_service.start_round`
each had their own copy of the same bounded poll loop; `decide()` needed
the identical pattern a third time. Pulled it into one
`poll_job(client, job_id, is_terminal, max_attempts, poll_interval)`
helper — callers just supply their own terminal-status predicate. Per
CLAUDE.md ground rule 6 (small, verifiable changes) this was a pure
refactor alongside Phase 2, not a scope expansion.

### 2026-08-12 — TestClient + SQLite :memory: needs StaticPool
`tests/unit/test_export.py` drives the export route through the real
FastAPI app via `TestClient`, which runs the endpoint on a different
thread than the test fixture. Plain `sqlite:///:memory:` ties its
table-having connection to a single thread (`SingletonThreadPool`),
so the endpoint's thread saw an empty database ("no such table:
negotiations") until the engine was built with
`poolclass=StaticPool, connect_args={"check_same_thread": False}`.

### 2026-08-12 — raised_by is best-effort text-sniffing, a named limitation
`round_service._infer_raised_by` scans whatever string fields are present
on the job/change dict (message, summary, explanation, rationale,
reasoning, and any string values inside a dict `content`) for the literal
words "union" / "employer", and returns whichever side is unambiguously
mentioned, else `"unknown"`. This is deliberately not smarter than that —
no NLP, no LLM-judge call, no per-clause attribution model. It works for
the seeded corpus's synthetic AI phrasing but will legitimately say
"unknown" whenever SuperDocs' actual redline explanation doesn't name a
side by name. That's treated as acceptable per this phase's brief, not as
something to fix later. `raised_by` is only ever overwritten when a
non-"unknown" value is inferred (`upsert_proposed_item`), so a chunk that
once got attributed doesn't get quietly reset to "unknown" by a later,
less-informative round.

### 2026-08-12 — Live verification: get_session_jobs shape, VERIFIED (with corrections)
A real key landed in `.env` mid-session (previously the literal
`.env.example` placeholder, which 401'd — see the superseded note this
replaces). Ran a real negotiation end-to-end: `upload_document` +
`upload_attachment` x2 → `start_round` → `list_pending_changes` →
`decide` (approve all) → `get_session_jobs`, via both a throwaway script
and, once fixed, the actual `negotiation_service`/`round_service`/
`tracker_service` code paths. The inferred shape from before this session
was **wrong on several points** — all fixed, all covered by the offline
respx-mocked suite now (24/24), and the corrected assumptions
re-confirmed by a genuinely live pytest run
(`tests/live/test_tracker_resilience_live.py`, `REDLINER_LIVE_CALLS=1`).

**1. `get_session_jobs` returns `{"jobs": [...], "total": N}`, not a bare
list.** `SuperDocsClient.get_session_jobs` now unwraps this so its return
type (`list[dict]`) is honest; `tracker_service`'s `isinstance(jobs,
list)` guard was previously a silent no-op against the real shape (it
always failed, so the rebuild path never ran) — now it actually runs.

**2. `approve_changes`'s documented batch shape 422s.**
`docs/superdocs-api-reference.md` describes `POST .../approve` taking
`{"changes": [{"chunk_id", "approved", "feedback"}, ...]}`. Live, that
422s with `job_id` and `approved` reported as missing required top-level
fields. The real shape is **one decision per call**: `{"job_id",
"change_id", "approved", "feedback"?}` — keyed by `change_id` (the
per-proposal id from `pending_changes`), not `chunk_id`; a chunk_id-keyed
call is silently accepted (200) but ignored (confirmed by probing — it
never appears in `metadata.pending_batch_decisions` and never moves
`batch_complete`). Renamed `SuperDocsClient.approve_changes` →
`approve_change` (singular) to match. `round_service.decide` now
re-fetches the round's current pending changes to build a `chunk_id ->
change_id` map before submitting — our domain API stays chunk_id-keyed
(chunk_id is what `OpenItem` tracks across rounds; change_id is
round-proposal-scoped, per README's own chunk_id-stability rationale),
only the wire call changed.

**3. Real `pending_changes` entries use `old_html`/`new_html`/
`ai_explanation`/`change_id`, not a JSON-encoded `content` string.** The
brief's documented "double-parse" gotcha didn't reproduce in this sample
— `SuperDocsClient.parse_pending_changes` still runs (harmlessly returns
`content: null` for these entries, since no `content`/`diff`/`html` key
exists) and is left as-is since the gotcha may still apply to other
change types docs describe; not removing defensive code that didn't
prove wrong, just noting the observed real shape here.
`round_service._infer_raised_by` was extended to also scan
`ai_explanation`/`old_html`/`new_html` (live-confirmed field names).

**4. Decision history lives on the SAME job, not a separate history
entry.** There's no distinct "approve" entry in `get_session_jobs` — a
decided chunk's outcome appears at `result.document_changes.changes:
[{"status": "approved"|..., "chunk_id", "new_html"}, ...]` on the
originating chat job, once it reaches `status: "completed"`. My original
guess (`job.get("decisions")`/`"changes"`/`metadata.decisions`) was
wrong on every key; `_rebuild_from_job_history` now reads the real
location.

**5. Real job status includes `in_progress`**, not just
`pending`/`processing`/`awaiting_approval`/`completed`/`failed`.
`round_service`'s poll-terminal checks were exclusion-based ("not
pending/processing" = terminal), which wrongly treated `in_progress` as
terminal and then crashed downstream (`parse_pending_changes` iterating
`None`, since `metadata.pending_changes` is `null`, not missing, while
in progress — also fixed, in `superdocs_client.py`). Switched to
inclusion-based checks against the known terminal-status sets; an
unrecognized in-flight status now just polls until the 30-attempt bound
and fails safe (`RoundStatus.FAILED`) instead of mis-firing.

**6. Filenames must match actual content.** `negotiation_service`
hardcoded `.docx` filenames for the plain-text seed corpus; the real API
400s on that mismatch. Changed to `.txt`, matching what's actually
uploaded.

**7. `negotiation.rounds` is a stale ORM relationship collection —
found via the live resilience test, not mock-derived.** With
`expire_on_commit=False` (the "SQLite + sync SQLAlchemy, deliberately"
design choice from Phase 0, above), a relationship collection caches
whatever it saw on first access and
does not refresh after a later commit in the same session.
`round_service.start_round` read `negotiation.rounds` (for
`round_number`) *before* the new `Round` existed; `tracker_service.
reconcile`, called later in the same live-test session on the same
identity-mapped `Negotiation` object, then saw the same stale empty
collection and returned `[]` immediately — before ever calling
`get_session_jobs`. This is a real bug, not a live-shape assumption:
it would bite any code path that reuses one session across multiple
service calls (a script, a batch job), just not a fresh-session-per-
request path like normal FastAPI usage. Fixed by querying `Round`
directly (`db.query(Round).filter_by(negotiation_id=...)`) in both
`start_round`'s `round_number` calc and `tracker_service.reconcile`/
`_rebuild_from_job_history`, instead of trusting the relationship
attribute.

**Non-determinism observed, not a bug:** despite `approval_mode:
"ask_every_time"`, a round against the identical seeded documents
sometimes completed with zero pending changes instead of flagging any
for review (happened twice out of five round-starts this session). The
live resilience test now handles both outcomes rather than assuming a
round always proposes something.

**API usage cost this session:** roughly 5 negotiations' worth of setup
(document + 2 attachment uploads each) while iterating on the
`approve`/`get_session_jobs` shape, ~9 `start_round` calls total across
throwaway scripts and test retries, ~7 `approve` calls, and a handful of
`get_job`/`get_session_jobs` reads. Small relative to the 10,000-op
monthly grant the brief mentions, but not the "one round, one decision"
minimum — the extra cost came from the `approve` payload shape needing
several rounds of live probing (422 → discovering `job_id`+`approved` are
required → discovering `change_id` not `chunk_id` is the real key) and
from the AI's non-deterministic HITL behavior needing a couple of
restarted rounds before landing a clean success case. Each throwaway
negotiation is orphaned in SuperDocs afterward (sessions never expire per
the docs) but harmless — nothing in the local DB references them beyond
this session's now-discarded in-memory SQLite instances.

## Test run — 2026-08-12, end of Phase 3 + live verification

```
pytest tests/ -v
24 passed, 1 skipped in 0.51s   # offline default, live test skipped

REDLINER_LIVE_CALLS=1 pytest tests/live/test_tracker_resilience_live.py -v -s
1 passed in 38.73s   # genuinely live, real API
```

## Bugs / rough edges hit while using SuperDocs

(Task 4, Question 1 wants this — log as encountered.)

- `POST /v1/chat/{session_id}/approve` does not match
  `docs/superdocs-api-reference.md`'s documented `{"changes": [...]}`
  batch shape — 422s, requiring `job_id` + `approved` as top-level
  fields, and is keyed by `change_id` per decision (one call per
  decision), not `chunk_id`. A `chunk_id`-keyed call is accepted (200)
  but silently has no effect.
- `GET /v1/sessions/{id}/jobs` returns `{"jobs": [...], "total": N}`,
  not the bare list the docs' prose implies.
- Job status includes at least one value not in the API reference's
  vocabulary: `in_progress` (distinct from `pending`/`processing`).
- `metadata.pending_changes` is `null` (not simply absent) while a round
  is `in_progress`, which breaks naive `.get(key, [])` handling.
- Proposed-change entries in this sample carried the redline directly as
  `old_html`/`new_html` strings plus `change_id`/`chunk_id`/
  `ai_explanation` — not the `content`-as-JSON-encoded-string shape the
  brief specifically warns about. That gotcha may still be real for other
  operation types; just didn't reproduce here.
- `approval_mode: "ask_every_time"` did not reliably force HITL review —
  identical input documents sometimes produced a round that completed
  with zero pending changes. Reconfirmed repeatedly in the Phase 4
  frontend walkthrough: 4 of 6 fresh rounds across two negotiations came
  back completed-with-nothing-to-review on the first try.

### 2026-08-12 — No negotiations-list backend endpoint (deliberate, per brief)
The brief for this phase says "zero backend logic changes." There's no
`GET /negotiations` — `negotiations.py` only has `POST ""`. So the
Negotiations tab lists negotiations created *this browser session*
(plain React state), not a persisted list from the DB. Reloading the
page loses the list (though the negotiations themselves, and everything
SuperDocs did with them, are untouched — only the frontend's in-memory
pointer to them is gone). This is a real, user-visible limitation, not
hidden: flagging it here rather than quietly building around it.
Fixing it properly means either accepting a small backend change
(`GET /negotiations` reading the `Negotiation` table) or persisting the
list in `localStorage` — neither happened this phase since the brief was
explicit about scope.

### 2026-08-12 — Phase 4 UI bugs found live (none in the backend)
Manually verifying the UI against the real API (not just eyeballing the
JSX) surfaced three real bugs, all in `frontend/src/App.jsx`, all fixed
before finishing:

1. **A `failed` round showed two contradictory messages at once.**
   `nothingToReview` was `status !== "awaiting_approval" &&
   pendingChanges.length === 0`, which is also true for `failed` — so a
   failed round showed both "Nothing needed review this round" (with a
   cheerful "Start another round" button) *and* the failure banner
   underneath it. Only reproduced by actually getting a live `failed`
   round (not something a mock would have shown, since I'd only mocked
   the happy paths). Fixed: `nothingToReview` now requires
   `status === "completed"` specifically.
2. **"Nothing to review" and "you just finished deciding everything"
   collapsed into the same UI state.** Both are `status === "completed"`
   with an empty `pendingChanges` array after submission clears it — so
   submitting decisions and having them all land showed the misleading
   "Nothing needed review this round" message instead of a completion
   message. Added a `decisionsSubmitted` flag, set only by a successful
   `submitDecisions()` call, to tell the two apart.
3. **No way to start a second round after the first one's decisions were
   submitted.** The post-decision "Round complete" state had no button —
   only the "nothing to review" state did. Found while trying to run
   enough rounds on one negotiation to observe a REOPENED item live.
   Added the same "Start another round" button to that state.

None of these are backend bugs — `round_service`/`tracker_service`
behaved exactly as Phase 2/3 built and tested them. They're proof that
"write the JSX for the states you expect" and "watch the states the real
API actually returns" are different exercises, and only the second one
catches this class of bug.

## Phase 4 manual verification — 2026-08-12, real browser, real API

Ran `backend` on port 8001 (port 8000 was occupied by a stale
`doctask-medidala` server from another project — left it alone, pointed
`vite.config.js`'s proxy at 8001 instead) and `frontend` via `npm run
dev` (landed on port 5174; 5173 was also occupied by the same stale
process). Walked the UI in a real Chrome tab via browser automation,
using the actual seeded synthetic documents
(`backend/data/seed/*.txt`).

**Negotiations tab:** filled the form (name + 3 file uploads), submitted.
Real `POST /negotiations` call — real `upload_document` +
`upload_attachment` x2 against SuperDocs. Succeeded, auto-jumped to the
Round tab. Card styling, coral accent, form layout all rendered as
designed.

**Round tab, "nothing to review" case:** hit this 4 times out of 6
fresh-round attempts across two negotiations — the round completed
immediately with zero pending changes. The empty state rendered exactly
as required: a clear sentence, no broken-looking blank screen, a "Start
another round" button. (This is where bugs #1 and #2 above were found
and fixed.)

**Round tab, real pending changes:** on one attempt, got 2 real proposed
changes (Article 3 — Wages, Article 7 — Grievance Procedure), each
showing the `[DISAGREEMENT: ...]` text SuperDocs generated. The diff-chip
pattern rendered correctly: struck-through old value (plain text,
HTML-stripped via `DOMParser`) → arrow → new value, `ai_explanation`
shown as a caption underneath. Clicked Approve on one, Reject on the
other — the per-item toggle worked (left border and outcome badge
updated live, "Submit N/M decisions" stayed disabled until both had a
decision), then clicked "Submit 2/2 decisions". Real
`POST /rounds/{id}/decisions` call, resolved to `status: "completed"`.

**Open Items tab:** showed exactly 2 rows — `APPROVED` (green) for the
wages clause, `REJECTED` (red) for the grievance clause — matching the
decisions just submitted, read live from `GET
/negotiations/{id}/open-items`. Confirms the write path
(`upsert_decided_item` hooked into `decide()`) end to end through the
actual UI, not just through pytest.

**REOPENED status:** not observed live this session. Started 4 more
rounds on the same negotiation trying to get SuperDocs to re-flag one of
the two decided clauses; all 4 came back completed-with-nothing-to-review
(the same non-determinism noted above). Did not keep spending live API
calls chasing this — the reopen transition is covered by two passing
automated tests (`test_reproposing_a_decided_chunk_reopens_it`,
`test_multi_round_reopen_flips_status_and_updates_round_links`), and
`TrackerItem`'s rendering for `status="reopened"` is the identical code
path already visually confirmed correct for `open`/`approved`/`rejected`
— just a different CSS class (`.tracker-item.status-reopened`,
`.status-badge.reopened`). Low risk, but genuinely unverified live —
noted honestly rather than claimed as observed.

**Export:** clicked "Export agreement (.docx)" on the tracker tab.
Real `GET /negotiations/{id}/export?format=docx` call, no error banner,
button returned to normal state. Verified outside the browser:

```
$ ls -la ~/Downloads/ | grep docx
Northfield Manufacturing — Local 214.docx   37150 bytes

$ file "Northfield Manufacturing — Local 214.docx"
Northfield Manufacturing — Local 214.docx: Microsoft OOXML
```

A real, valid `.docx` downloaded with the negotiation's name as the
filename.

**Console:** no JS errors or exceptions at any point (checked via
`read_console_messages`, `onlyErrors: true`).

**One mistake worth logging honestly:** before starting the backend for
this session, I ran `rm -f backend/redliner.db` without checking its
contents first — should have moved it aside instead. It's gitignored
(`**/*.db`), schema-only and regenerable via `scripts/init_db.py` (which
I then ran), and nothing in this session's live scripts had written to
it, so the practical damage looks like none — but the right move was to
check or back it up before deleting, not after.
