# Gap Analysis — before / after this pass

## What existed before this pass

From the prior session: `types.ts`, `chunkDiff.ts`, `claimReconciler.ts`,
`changeModel.ts`, `revertEngine.ts`, `superdocsClient.ts`, `extension.ts`,
`turnsTreeProvider.ts`, 39 passing tests, `README.md`,
`docs/IMPLEMENTATION_PLAN.md`.

Audited against this pass's own checklist:

| Question | Verdict |
|---|---|
| What was already correct? | `chunkDiff`, `claimReconciler`, `changeModel`, `revertEngine` — all real logic against real fixtures, no fabrication. Kept as-is except for two additive fixes below. |
| What was incomplete? | Everything that turns those four modules into an actual system: no orchestration layer, no persistence, no audit log, no session polling, no real UI. |
| What was only scaffolding? | `extension.ts` and `turnsTreeProvider.ts` — a connect command and a tree view that could only ever show two hard-coded empty-state strings. Correctly honest (no fake data), but not a product yet. |
| What was not connected to real SuperDocs behavior? | `superdocsClient.ts` existed but nothing called it except the one-off `healthCheckKey` on connect. No turn discovery, no approve/reject/revert against a live session. |
| What assumptions were unsupported? | None asserted as fact — `docs/IMPLEMENTATION_PLAN.md §15` already listed the open questions honestly. That list is unchanged by this pass (still genuinely open; see `docs/SECURITY.md` and the README for what's still unverified). |
| What tests were weak? | None were misleading, but coverage stopped at the four pure modules — nothing tested the *system* (idempotent ingestion, decision flows, conflict handling end-to-end). |

## Two correctness fixes made to the "already good" code

Preserved rather than replaced, but two real gaps were found and fixed
while wiring the orchestration layer around them:

1. **`Change` had no way to know where it came from.** SuperDocs's
   human-in-the-loop path (change not yet applied; reject = deny) and its
   default auto-apply path (change already applied; reject = must actively
   undo) need different reject semantics. The original `Change` type had no
   field distinguishing them. Added `source: "auto_apply" | "hitl"`.
2. **A HITL-sourced change had no way to be approved/denied later.**
   Approving/denying a HITL change requires the originating `job_id`, which
   wasn't captured anywhere. Added `sourceJobId`, populated automatically at
   ingestion from the turn's `correlationId` — callers never have to
   separately track or re-supply it.

Both were caught by writing the orchestration layer honestly rather than
gluing it together loosely — exactly the kind of gap this phase's audit
step is meant to surface.

## What this pass added

- `persistence.ts` — `InMemoryBackend` (tests) and `JsonFileBackend` (real,
  atomic-write, restart-durable) behind one interface.
- `auditLog.ts` — append-only audit trail.
- `reviewStore.ts` — the actual review/change engine: idempotent turn
  ingestion, approve/reject/revert with correct per-source semantics,
  conflict detection reusing `revertEngine`, supersession of stale
  proposals, audit emission for every transition.
- `sessionWatcher.ts` — polls SuperDocs jobs per session and feeds new
  turns into the store; `extractTurn` is a pure, isolated function so the
  one genuinely uncertain part (exact job-payload field shapes, never
  live-tested — see `docs/SECURITY.md`/README) is contained to one place.
- `webviewRender.ts` + `reviewPanel.ts` — a real webview: strict CSP,
  validated inbound messages, before/after rendering, claim/actual badges,
  status-appropriate action buttons, native VS Code theming via
  `--vscode-*` CSS variables.
- `liveSideEffects.ts` — the real network-facing implementation of the
  store's side-effect port, with its one unverified design decision
  (how a computed patch gets written back to SuperDocs) documented in the
  code itself, not hidden.
- `turnsTreeProvider.ts` rewritten to show real turn/change data grouped
  and status-annotated, still with honest empty states.
- 49 new tests (39 → 88 total, all passing — see `docs/EVALUATION.md` for
  the actual run).

## What is still not done, stated plainly

- **No live smoke test.** This sandbox's network egress does not reach
  `api.superdocs.app`; nothing here has been run against a real SuperDocs
  account. Everything is verified against fixtures built from the
  documented API shapes.
- **No visual QA.** This environment cannot launch a GUI VS Code instance.
  The webview's HTML/CSS/message-handling logic is unit-tested; its actual
  rendered appearance (spacing, narrow/wide layout, focus order in a real
  browser engine) has not been visually inspected.
- **`claimedIntentText` is not wired.** `sessionWatcher.ts` currently
  passes an empty string for the user's original instruction — job payloads
  give high-confidence access to the assistant's reply and the document
  diff, but correlating the *original user message* per turn needs
  `session/history` message data whose exact shape wasn't confirmed (see
  IMPLEMENTATION_PLAN.md §15). The claim-vs-actual reconciliation itself
  does not depend on this field, so it doesn't block correctness — it only
  means the "what did the agent claim it would do" line is currently blank
  in the UI, not the "what did it say it did" line, which does work.
- **Multi-document-per-turn is not modeled yet.** The store's data model
  supports it (`documentId` on every `Change`), but `sessionWatcher`
  currently assumes one document per session.
- **No accessibility or performance testing was performed** (screen reader
  testing, 500+ change/1000+ audit-event load testing) — out of reach
  without a real host to run them in, within this pass's time.

## Hardening pass — bugs found and fixed

A second, adversarial pass over this same code surfaced one genuinely
serious bug and several real hardening gaps. Listed here rather than only
in commit history because "what was wrong and how it was found" is exactly
what a reviewer needs to trust the fix.

1. **Document-corruption bug in `parseChunks`/`serializeChunks`.** `data-chunk-id`
   can appear on nested elements (a table, separately on its rows and
   cells). The original parser captured nested ids as *extra*, separate map
   entries in addition to the parent's own full HTML. Flattening that map
   back into a document (`serializeChunks`, used by every write-back) would
   have duplicated the nested content — a real, silent document-corruption
   risk for any table-containing document, not a style nitpick. Fixed by
   making chunk capture top-level-only. Also added `canSafelyRoundTrip()`,
   an empirical runtime gate (`serialize(parse(html)) === html`) that any
   live write-back must pass before proceeding — see `docs/SECURITY.md`.
2. **Out-of-order job processing.** The session watcher processed jobs in
   whatever order the API returned them, which could diff a job against the
   wrong "previous" snapshot if jobs resolved out of creation order. Fixed:
   jobs are sorted by `created_at` before processing.
3. **Overlapping polls, no rate-limit backoff, one session blocking all
   others.** The watcher now guards against a slow poll overlapping the
   next tick, honors `Retry-After` on a 429 by pausing, and isolates each
   session's failure so one broken session doesn't stop the rest.
4. **Poll cursors were in-memory only.** Lost on restart, meaning a restart
   would re-fetch and re-process every already-seen job (wasteful, though
   not data-corrupting — `ReviewStore`'s own idempotency was already a
   safety net). Cursors are now persisted to the same backend as everything
   else.
5. **`claimedIntentText` was a hardcoded empty string.** Now correlated
   from session history by matching the assistant's reply text against the
   message log (`findPrecedingUserInstruction`), rather than assuming this
   watcher's locally-assigned turn index lines up with SuperDocs's own
   message indexing (still unverified — content matching avoids depending
   on that assumption).
6. **The UI never showed a claim for the common (auto-apply) case.**
   `aiExplanation` is only populated for HITL-sourced changes, so the
   review panel showed no claim text at all for most changes. Added a
   `TurnRecord` (instruction + reply, captured once per turn) rendered at
   the turn level, distinct from any change-specific `aiExplanation`.
7. **Audit fields named `fromVersion`/`toVersion` held raw HTML,** not
   version identifiers — a real naming/semantics bug, since SuperDocs's
   actual version concepts (`checkpoint_id`, `turn_index`) are a different,
   not-yet-wired thing. Renamed to `beforeContent`/`afterContent`.
8. **The hand-rolled regex sanitizer was replaced with `sanitize-html`**
   (a maintained library), with an explicit allowlist. New tests cover
   attack classes the original regex approach didn't: SVG-based script
   vectors, `style`-attribute vectors, and fake credential forms.
9. **Packaging was actually broken**, not just under-verified:
   `npx vsce package` failed outright on the placeholder publisher name,
   then warned about a missing `repository` field (relative doc links would
   break once published), then warned about a missing `LICENSE` and no
   `.vscodeignore`. All fixed and re-verified — see `docs/EVALUATION.md`
   for the actual passing package command.
10. **`documentId` is still set equal to `sessionId`** in the session
    watcher as an explicit, commented placeholder — not a claim that the
    API guarantees that relationship. Real multi-document support needs
    this resolved against a live account first.

Every item above has a corresponding test named after the bug it fixes,
per this pass's own request not to declare something fixed without one.

## Third pass — audit-driven fixes

A third, independent audit surfaced one more genuinely serious bug and two
real robustness improvements.

1. **Bootstrap/baseline bug — a pre-existing document would be reported as
   entirely agent-created.** `SessionWatcher` initialized every newly-seen
   session's baseline as an empty string. The very first job ever observed
   on a session was therefore diffed against nothing — so if that session's
   document already had 50 paragraphs before the agent touched anything,
   the very first turn observed would report all 50 as newly created. This
   is a real, believable bug (every existing test built its fixtures with
   explicit before/after HTML, so nothing exercised "a session that already
   has history when first observed"). Fixed with `bootstrapCursor()`: any
   job already `completed` at first sight is silently accounted for as
   pre-existing history (never reviewed, since there's no reliable "before"
   snapshot for it), and the baseline is established from the session's
   actual current state. A job that's `awaiting_approval` at first sight is
   deliberately *not* bootstrap-skipped — it's a real pending decision
   regardless of when the watcher started. Covered by three new tests in
   `sessionWatcher.test.ts`'s "bootstrap baseline" suite, including the
   exact regression case (a pre-existing document, then a genuinely new
   edit, asserting only the real edit is reported).
2. **Turn identity now rests on the server's own `job_id`, not a local
   counter.** `turnId` was `${sessionId}:${locallyIncrementingIndex}`. A
   counter can drift (across restarts, reordering, or a future bug) in a
   way a real server-assigned id cannot. `turnId` is now
   `${sessionId}:${job.job_id}` — the same job can never become two
   logical turns by construction, not just by careful counter bookkeeping.
   `reviewPanel.ts`'s `sessionIdFromTurnId` string-parsing helper (a
   fragile dependency on turnId's exact format) was also removed in favor
   of reading `change.documentId` directly, which already carried the same
   information.
3. **Duplicate `data-chunk-id` values were silently lossy.** If a document
   ever reused a chunk id, `parseChunks`'s `Map` could only keep one
   occurrence — a diff computed from it could be quietly wrong about which
   occurrence changed. `diffDocumentHtml` now throws `DuplicateChunkIdError`
   naming the offending id(s) rather than returning a diff built on lossy
   data; `SessionWatcher` catches this per-job (isolated from sibling jobs
   in the same session), reports it, and marks the job done so it doesn't
   retry forever. **Known trade-off, stated plainly:** once a session's
   baseline itself contains a duplicate id, later turns diffed against that
   baseline are *also* flagged — deliberately conservative (a diff built on
   a known-contaminated baseline is still unreliable, even if the new
   content looks unrelated) — and there is currently no dedicated UI action
   to reset a session's tracking and recover from this state. That's a real
   gap, not silently glossed over.

An unrelated environment issue was also found and fixed while re-verifying
this pass: a `node_modules` state had drifted to the point that neither
`npx tsc` nor `npm run typecheck` were resolving the project's actual
pinned TypeScript version, surfacing an unrelated deprecation error from
whatever version they fell back to instead. Fixed with a clean reinstall;
mentioned here because it's exactly the kind of "verified" claim that
would have been wrong if the discrepancy hadn't been chased down instead
of assumed to be a real code bug.
