# Reference Letter Drafter

Built by Muhammed Shajahan for the SuperDocs engineer task (assigned build, S2 difficulty).

Drafts reference and recommendation letters from a structured intake, in the writer's own voice, with strength
calibrated honestly — a lukewarm reference reads as lukewarm, it doesn't get inflated into something warmer.
Built on [SuperDocs](https://superdocs.app), against the REST API.

> **Screenshot / demo**: not included in this PR. Every claim below was verified from the terminal (curl against
> the live API, then curl against this app's own routes) rather than by opening a browser — see
> [Verification](#verification-what-i-actually-checked). If a maintainer wants a screenshot or short screen
> recording added, say so and I'll add one.

## Who it's for

Managers and academics writing reference letters — the case that motivated this build is a manager who has to
write a reference for someone they'd give a genuinely mixed review of, and doesn't want the letter to come out
sounding warmer than they mean it, just because "recommendation letter" pulls language toward enthusiasm by
default.

## What it does — the flow

1. **Intake** (`components/IntakeForm.tsx`) — the writer fills a structured form: their own identity, the
   subject's name/role, the relationship and how long they've known them, the purpose (job / grad school /
   fellowship / other), an explicit **strength band** (Strong / Solid / Mixed / Reluctant-Lukewarm), a
   repeatable list of *claim → evidence* pairs, free-text reservations, optional tone notes, and a length
   preference.
2. **Start a session** (`POST /api/session` → `lib/superdocs.ts#uploadStarterDocument`) — uploads a minimal
   placeholder document into a fresh SuperDocs session via `documents/upload`. This is the literal "upload a
   document" leg of the four-call minimum contract, and it means the letter is built via chunk-ID structural
   edits from the very first turn instead of being generated with no document context.
3. **Draft** (`POST /api/draft` → `lib/buildInstruction.ts` → `chat/async`) — the intake is turned into one
   instruction string. The strength band maps to explicit constraint language (see
   [Calibration logic](#calibration-logic---the-actual-product) below), and the call is made with
   `approval_mode: "ask_every_time"` plus `cross_session_memory` keyed to the writer's email.
4. **Review** (`components/ReviewPanel.tsx`, polling `GET /api/jobs/[jobId]`) — when the job reaches
   `awaiting_approval`, every proposed paragraph is rendered as a before/after diff card with SuperDocs' own
   `ai_explanation`. The writer approves or rejects each change individually, with optional feedback on
   rejections, before anything is finalized. Nothing reaches the final document without an explicit decision.
5. **Export** (`components/ExportButton.tsx` → `POST /api/export`) — the approved letter is exported as a real
   `.docx` and downloaded in the browser.

## Calibration logic — the actual product

Everything else here is plumbing around `lib/buildInstruction.ts`, which is the part that makes "a lukewarm
reference reads as lukewarm" true instead of aspirational. Each strength band maps to specific constraint
language injected into the instruction sent to SuperDocs:

| Band | Constraint |
|---|---|
| Strong | Confident, specific, evidence-led language allowed — but still nothing beyond what the evidence supports. |
| Solid | Positive but measured; explicitly forbids words like "best", "exceptional", "outstanding", "brilliant". |
| Mixed | Strengths and weaknesses stated side by side, in proportion to what was reported — the instruction explicitly says not to resolve the mix into an overall positive tone. |
| Reluctant / Lukewarm | Forbids superlatives and enthusiasm markers entirely (no "pleasure to recommend"), requires flat/hedged phrasing, and requires the writer's stated reservations to appear directly rather than be softened or omitted. |

On top of the band, the instruction:

- Lists every claim/evidence pair the writer entered and tells the model to use **only** those — no invented
  accomplishments, numbers, or anecdotes.
- Includes the writer's reservations verbatim and tells the model they must be reflected, not buried.
- Sets length by preference (brief / standard / detailed → rough word-count ranges).
- Tells the model to write in the writer's first person and sign off with their name.

This was verified for real (not just read from the docs) — see the reluctant-band test transcript in
[Verification](#verification-what-i-actually-checked): the letter that came back said "Sam missed one deliverable
during the first quarter" and "rarely took initiative beyond assigned scope" as flat statements, with zero
superlatives, exactly as the reservations were entered.

## SuperDocs features used

| Feature | Where | Why |
|---|---|---|
| `documents/upload` | `lib/superdocs.ts#uploadStarterDocument` | The mandatory "upload a document" call; also means chunk-ID structural edits are available from turn one. |
| `chat/async` with `approval_mode: "ask_every_time"` | `lib/superdocs.ts#startDraftJob` | Nothing is applied to the document without the writer approving it first. |
| `GET /jobs/{job_id}` (polling) | `lib/superdocs.ts#getJobStatus`, `components/ReviewPanel.tsx` | Drives the review screen; branches on `status` and `metadata.awaiting_kind`. |
| `chat/{session_id}/approve` | `lib/superdocs.ts#approveChange` | Per-change approve/reject, with optional feedback on rejected changes. |
| `documents/export` | `lib/superdocs.ts#exportDocument` | Final `.docx` download. |
| Cross-session memory (`cross_session_memory` + `cross_session_memory_key`) | `lib/superdocs.ts#startDraftJob` | Keyed on the writer's email so each writer's own voice/phrasing preferences persist across letters without bleeding into another writer's drafts on the same deployment. |
| Templates (`templates/upload`, `GET /templates`) | `app/api/templates/route.ts` | Writers can save a reusable letterhead; SuperDocs searches saved templates itself when drafting. Wired as an API route; not yet surfaced in the intake form UI (see [Weak areas](#weak-areas--what-i-would-fix-next)). |

## Architecture

```
Browser (React client components)
  IntakeForm → POST /api/session → POST /api/draft
  ReviewPanel → polls GET /api/jobs/[jobId] → POST /api/approve
  ExportButton → POST /api/export (streams .docx back)
        │
        ▼
Next.js Route Handlers (server-only, app/api/*)
        │  reads SUPERDOCS_API_KEY from env — never sent to the browser
        ▼
lib/superdocs.ts  (typed fetch client)
        │
        ▼
api.superdocs.app/v1  (upload, chat/async, jobs, approve, export, templates)
```

- **State**: `store/useSessionStore.ts` (Zustand) holds the intake data, `sessionId`, `jobId`, and current stage
  (`intake` → `review` → `done`) client-side. There's no database — a SuperDocs `session_id` *is* the durable
  state for a given letter; the app doesn't persist anything of its own.
- **Server/client boundary**: the SuperDocs API key lives only in `lib/superdocs.ts`, marked `import
  "server-only"`. Every SuperDocs call is proxied through a Next.js Route Handler; the browser never sees the key.
- **Polling, not SSE**: `ReviewPanel` uses TanStack Query with a 3-second `refetchInterval` against
  `GET /api/jobs/[jobId]`, rather than opening an SSE stream. Simpler to reason about and to proxy through a
  Route Handler; the tradeoff is slightly higher latency to see a proposed change than SSE would give (see
  [Weak areas](#weak-areas--what-i-would-fix-next)).
- **Sanitization**: proposed-change HTML and the diff preview are rendered with `dangerouslySetInnerHTML`, run
  through `lib/sanitizeHtml.ts` (DOMPurify, allowlisting a small set of block/inline tags) first. The content
  originates from an authenticated SuperDocs session rather than arbitrary third-party input, but it still
  reaches the browser as raw HTML, so it's sanitized rather than trusted.

## Design decisions

- **Always upload a starter document, even for a from-scratch letter.** The task brief's minimum contract is
  four calls — upload, edit, approve, export — regardless of what the assigned card's surfaces list says. There's
  no existing document to upload for a letter drafted from scratch, so the app uploads a two-line placeholder
  (`<h1>Reference Letter</h1><p>[placeholder]</p>`) and lets the AI replace it. This keeps the literal upload
  call in the flow and gives chunk-ID structural editing from the start, instead of skipping straight to a
  document-less chat call.
- **`cross_session_memory_key` = the writer's email**, not a random session id. The card's "in the writer's own
  voice" requirement is exactly what SuperDocs' cross-session memory is for — this is a direct mapping, not a
  workaround. It also means a single deployment can serve multiple writers without their tone preferences
  mixing (SuperDocs' B2B2C pattern).
- **Polling over SSE.** SSE would give faster feedback during the review step, but adds a persistent-connection
  proxy through Next.js Route Handlers and the documented double-parse handling
  (`JSON.parse(event.data)` then `JSON.parse(envelope.content)` again) for no benefit at this scale — a single
  letter has at most a handful of proposed changes. Noted as the first thing to revisit if this needs to feel
  more real-time.
- **DOMPurify over a hand-rolled sanitizer.** Considered writing a small allowlist sanitizer to avoid a new
  dependency, but the review screen's whole job is rendering AI-generated HTML into the DOM — that's exactly
  the case a battle-tested sanitizer exists for, and hand-rolling HTML parsing/allowlisting correctly is a much
  larger surface to get right than pulling in a well-maintained ~20kb library.
- **No database.** A SuperDocs `session_id` already carries the durable state (the document, its chunk history,
  cross-session memory). Adding a database to also track "which letters exist" would duplicate that without
  buying anything for a tool this size — see [Weak areas](#weak-areas--what-i-would-fix-next) for what this
  costs.

## Weak areas — what I would fix next

Being honest about this is worth more than pretending it's finished:

- **No letter history / no database.** If the writer closes the tab mid-review, the `sessionId` and `jobId` are
  gone — there's no way to resume a specific letter later or list past letters. The SuperDocs session still
  exists server-side, but this app has no index of "which sessions belong to which writer." A real version
  would need at least a lightweight `(writer_email, session_id, subject_name, created_at)` table.
- **Templates are wired on the backend but not in the UI.** `GET/POST /api/templates` work (they proxy
  `templates/upload` and `GET /templates` correctly), but `IntakeForm` doesn't yet have the "pick or upload a
  letterhead template" control described in the plan. The AI does search saved templates on its own when asked
  to draft, so templates a writer previously uploaded via the API directly would still get picked up — but
  there's no in-app way to upload or choose one yet.
- **The review step isn't guaranteed to appear.** During testing, drafting into a still-placeholder document
  was sometimes treated by SuperDocs as `create_full_document` rather than a chunk-level `edit`, which comes
  back `auto_approved` with the job going straight to `completed` — `ask_every_time` doesn't gate whole-document
  creation the same way it gates edits to existing content. The app handles this gracefully (a `completed` job
  with no pending changes just moves straight to the export step), but it means a writer occasionally sees no
  review UI at all, which is a real gap against "a human holds the gate" for this kind of build. I did not find
  a documented way to force chunk-level review of an initial full-document draft; it may be a genuine product
  gap on SuperDocs' side rather than something fixable client-side. Worth a bug report.
- **No tests.** Everything below in Verification was checked by hand with curl, not with an automated test
  suite. For a tool this size that's a defensible cut, but it means there's no regression protection if the
  instruction-builder or the API client changes later.
- **No retry/backoff on the API proxy layer.** `lib/superdocs.ts` calls fail fast and surface a 502 with the raw
  SuperDocs error message. For an operation-metered API on a free tier, a naive retry loop would be worse than
  no retry, but a single retry-with-backoff on `5xx`/network errors would make the review flow more robust to
  the "still processing" slowness the task brief calls out.
- **No operation budget / stopping rule in the UI.** The task brief asks builds that "measure something or run
  in a loop" to have a small-sample mode and a stopping rule. This build doesn't loop — one letter costs one
  `chat/async` operation (plus one more per rejected-and-retried change) — so there's nothing to runaway, but
  there's also no UI surfacing of `usage.monthly_remaining` to warn a writer as the free tier's 500 ops/month
  gets close to exhausted. That's a small, worthwhile addition.
- **Single-document sessions only.** The app doesn't use SuperDocs' multi-document session support; each letter
  is one session with one document. Fine for this use case (a reference letter is self-contained), but it means
  a writer can't, say, keep an evidence-source document open alongside the letter in the same session.

## Setup

```bash
npm install
cp .env.local.example .env.local
# edit .env.local and set SUPERDOCS_API_KEY
npm run dev
```

Environment variables:

| Variable | Description |
|---|---|
| `SUPERDOCS_API_KEY` | Your SuperDocs API key. Never sent to the browser — every SuperDocs call goes through this app's own API routes. Get one via [agent signup](https://docs.superdocs.app/introduction/agent-signup) or a normal account at [use.superdocs.app](https://use.superdocs.app). |

## Verification — what I actually checked

Per the task brief's note that the first request in a fresh session can be slow, and that the double-parse
gotcha is the most common integration bug, I verified the four core calls **by hand with curl against the real
API** before writing any app code, then verified the app's own `/api/*` routes the same way after building
(`next build && next start`, then curl against `localhost`). No browser was opened for either pass. Specifically
confirmed:

- `documents/upload` returns `data-chunk-id` on every block, matching the docs.
- `chat/async` → `GET /jobs/{id}` polling reaches `awaiting_approval` with `metadata.pending_changes` in the
  documented shape (`change_id`, `chunk_id`, `old_html`, `new_html`, `ai_explanation`).
- `chat/{session_id}/approve` requires the top-level `approved` field even on a single-change request — the docs
  call this out as a common `422` trap, and it was reproduced and worked around (`app/api/approve/route.ts`
  always sets it).
- A full poll-to-`completed` → `documents/export` round trip produced a real `.docx` (`file` reported "Microsoft
  Word 2007+" both times, once from the raw API and once through this app's own export route).
- The reluctant/lukewarm strength band produces measured, hedged language with no superlatives and the stated
  reservations intact, confirming the calibration instruction actually holds against the model rather than just
  reading well on paper.
- The `create_full_document` / `auto_approved` behavior documented above in
  [Weak areas](#weak-areas--what-i-would-fix-next) was discovered during this verification pass, not assumed.

`npm run lint`, `npx tsc --noEmit`, and `npm run build` all pass clean.
