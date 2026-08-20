# SuperDocs for Google Chat — One-Page Write-Up

**Built by Ekansh Kumar for the SuperDocs engineer task (Task 2 assigned build).**

## What it is
A Google Chat app that lets document work **start in chat** and run end-to-end on
SuperDocs. @mention it in a space with a request — *"draft the renewal letter for
Acme"* — and it drafts the document, posts an **item-by-item approval card**, applies
exactly the changes a reviewer approves, and returns a real, downloadable file. A
`digest` command (and a scheduler endpoint) reports what the space produced and what
is still waiting, so nothing sits silently forever.

## Who it's for
Teams on Google Workspace who want document requests and approvals to happen where
they already talk — legal ops, proposal desks, people ops. The reviewer never leaves
Chat: they see each proposed change, approve or reject it, and the approved result
lands in the document with a download link.

## Results, measured
- **39 tests pass with no API key and no network** (`pytest -q`) — the whole flow is
  tested through pure dispatch functions with a fake SuperDocs client.
- **The four-call contract is verified against the live API**, not mocked: upload →
  `chat_async(ask_every_time)` → poll → approve → export produced a **36,753-byte,
  valid `.docx`** (PK-magic), and the result card carried a **real signed
  `storage.googleapis.com` download URL** from `POST /v1/downloads`.
- **Item-by-item approval is real**: approving one change and rejecting another in the
  same review sends the exact per-change decision array; a unit test locks it in.
- **Multi-document reference drafting is non-destructive** (verified live): *"draft the
  2025 renewal based on last year's"* opens the prior document as a reference tab and
  creates a **separate** new document — the referenced doc is never mutated.

## Key trade-offs (and why they're right)
- **Polling over SSE.** A Chat webhook is request/response, and SuperDocs warns its SSE
  `proposed_change_batch.content` is a JSON-string-inside-JSON. Driving the flow with
  `GET /v1/jobs/{id}` (where `metadata.pending_changes` is already parsed) sidesteps
  that trap; `parse_pending_changes()` still handles the double-encoded shape
  defensively so the "empty diff card" failure mode can't happen.
- **Honest links, never fabricated.** SuperDocs has no public per-session share URL, so
  instead of inventing one the app mints a genuine ~15-minute signed download URL via
  `/v1/downloads` (which costs no operation) and omits the button if that call fails.
- **Undecided defaults to rejected on apply.** A change nobody reviewed never lands —
  the safe default for a human gate.
- **Pure dispatch + injected client.** All business logic is pure functions with the
  SuperDocs client passed in, so the entire flow is testable offline with a fake and
  **no key** — matching the brief's "tests run without a live key."
- **Opt-in request auth.** `GOOGLE_CHAT_AUDIENCE` unset = frictionless local dev; set
  it and the webhook verifies Google's signed JWT and rejects forged calls with `401`.

## Where it breaks (honest limits)
- **Scheduler digest push needs Chat service-account credentials.** The
  `POST /tasks/daily-digest` endpoint is real and secret-guarded, but pushing the card
  *into* a space requires a service account — a deployment step, documented, not built.
  Without it the endpoint returns the per-space digest payload for pull/preview.
- **In-memory review state.** Reviews/digest live in memory (lock-guarded, per-space
  isolated); a production deploy swaps the store for a database. Declared, not built.
- **New-document creation auto-applies.** SuperDocs applies a *created* document
  immediately even in review mode, so a reference draft may have nothing to approve —
  the app then reports the doc as *ready to download*, never "no changes needed."
- **No live Chat screenshot yet.** The SuperDocs side is proven live; the desktop/mobile
  card render needs a GCP deploy (guide is in the README) to capture `docs/approval-card.png`.

**Bottom line:** a modestly-scoped assigned build taken past its floor — item-by-item
approvals, honest signed links, non-destructive multi-document drafting, a scheduler
digest, and opt-in auth — with proofs (a counted test suite, a live round-trip, a real
downloaded `.docx`) rather than claims. Built **on** SuperDocs, never a clone **of** it.
