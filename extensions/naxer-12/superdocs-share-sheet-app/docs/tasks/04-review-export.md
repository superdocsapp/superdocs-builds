# Branch: `review-export`

**Read this whole file before writing code. If you haven't read `TASK.md` in the repo root yet,
stop and read that first.**

## Your job, in one sentence

The third tap: show the proposed edit on a screen a thumb can actually use, let the user approve or
reject it, then export and hand the finished file back to the OS share sheet.

## Before you start

Check `git branch -a` for whether `foundation` has merged; build against the real
`SuperDocsClient` if so, otherwise against the stub interface documented in `TASK.md` (same rule as
every other branch — do not block on `foundation`, do not redefine its interface).

## What to build

1. **`lib/screens/review_screen.dart`** (replaces the stub route from `foundation`): takes a
   `jobId`/`sessionId` as a route argument. Calls `SuperDocsClient.getJobStatus()` to get
   `updated_html` and `chunk_diffs`. Renders the HTML in a WebView (`webview_flutter`) sized to the
   phone's viewport width — inject a `<meta name="viewport" content="width=device-width">` tag if
   the returned HTML doesn't already have one, so nothing requires pinch-zoom or sideways scroll
   (this is an explicit bar in the brief: "without pinching or scrolling sideways").
2. **Highlight changed sections**: inject a small CSS block into the WebView marking elements whose
   `chunk_id` (from `chunk_diffs`) changed — a background-color highlight is enough, this doesn't
   need to be a full visual diff/redline for v1.
3. **Bottom action bar**: Approve and Reject buttons, large tap targets, pinned to the bottom of the
   screen (thumb-reachable, not top). This is v1 whole-document approve/reject, not per-chunk — see
   `TASK.md`'s "v1 cut" note; don't build a per-chunk stepper, it's explicitly deferred.
4. **On Approve**: call `SuperDocsClient.approve(sessionId, approved: true)`, briefly poll
   `getJobStatus()` again until `status == "completed"` (a simple loop with a short delay and a
   handful of retries is enough — this step is typically fast since the heavy work already
   happened), then call `SuperDocsClient.export(sessionId, format: "docx")`.
5. **Hand off to the OS share sheet**: take the exported file bytes, write them to a temp file with
   the right extension, and invoke the platform share sheet (`share_plus` package covers this) so
   the user can send the finished file onward — this is the "share it onward" half of the brief's
   loop, and it's this branch's responsibility to close it.
6. **On Reject**: call `approve(sessionId, approved: false)`, show a simple confirmation, return to
   home. No retry/re-instruction flow needed for v1 — that's a reasonable v2 addition, not built here.

## Owns

`lib/screens/review_screen.dart`, `lib/export/` (the export-and-share logic).

## Definition of done

- Given a real (or stubbed) `awaiting_approval` job, the review screen renders real formatted HTML
  at phone width with zero horizontal scroll — test this against an actual formatted document (a
  real DOCX-derived HTML sample, not a one-line plain-text stub, which would hide layout bugs).
- Approve → export → share-sheet handoff works end to end against a real account (once `foundation`
  is confirmed working per its own definition of done).
- Reject path works and doesn't crash or leave the job queue in a broken state (coordinate with
  `background-engine` on how a rejected job's stored status should read — `rejected` or `cancelled`,
  pick one and note the choice in `PROGRESS.md` since both other branches may read that field).

## Out of scope for this branch

Share intent handling (that's `share-intake`), background polling before this screen opens (that's
`background-engine` — by the time this screen opens, the job is already at `awaiting_approval` or
later), per-chunk approve/reject (explicitly deferred to v2, see `TASK.md`).
