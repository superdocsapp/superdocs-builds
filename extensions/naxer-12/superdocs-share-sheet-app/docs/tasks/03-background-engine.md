# Branch: `background-engine`

**Read this whole file before writing code. If you haven't read `TASK.md` in the repo root yet,
stop and read that first.**

## Your job, in one sentence

Make the brief's hardest bar real: "background completion survives the app being closed." Poll
every in-flight job's status even while the app is fully closed, and notify the user the moment
one needs their attention.

## Before you start: check two things

1. `git branch -a` — is `foundation` merged? Build against the real `SuperDocsClient` if so,
   otherwise against the stub interface in `TASK.md` (same rule as every other branch).
2. Is `share-intake` merged, or at least has its `lib/storage/job_queue.dart` been written? You
   read from and write to that same local job queue — if it doesn't exist yet, build against the
   exact shape documented there (`{ jobId, sessionId, filename, status, createdAt }`) as your own
   stub, and reconcile at merge time. Don't invent a second, different queue.

## What to build

1. **Android**: register a periodic `workmanager` task (package: `workmanager`) that, on each run,
   reads every job from the queue with status `pending` or `processing`, calls
   `SuperDocsClient.getJobStatus()` for each, and updates the queue's stored status. This must keep
   running even if the user has force-closed the app (that's the whole point — verify this on a real
   device or emulator by closing the app and confirming the poll still fires).
2. **iOS**: register a `BGAppRefreshTask` (via `BGTaskScheduler`, exposed to Flutter through a
   platform channel or a maintained plugin if one covers this adequately — check
   `flutter_background_fetch` or similar before hand-rolling a platform channel) doing the same
   poll. iOS's background execution budget is much stingier than Android's — a real device test
   closing the app and waiting is the only way to actually confirm this works; do not assume it does
   because the code compiles.
3. **`flutter_local_notifications`**: fire a local notification the moment a job's status changes to
   `awaiting_approval` or `completed` (something changed, worth opening the app for) or `failed`
   (something the user needs to know went wrong). Tapping the notification should deep-link straight
   to the review screen for that job (coordinate the route name with `review-export`'s branch — check
   `lib/app.dart` from `foundation` for the route name it registered).
4. **Backoff on failure**: if a poll request fails (no connectivity), retry with increasing delay,
   don't hammer the API or drain the battery. A simple doubling backoff capped at a few minutes is
   enough — this doesn't need to be sophisticated.

## Owns

`lib/background/`, Android `workmanager` registration (in `android/app/src/main/...` as needed),
iOS background-task registration (`ios/Runner/AppDelegate.swift` additions, `Info.plist` background
mode entries).

## Definition of done

- Start a real edit (via `share-intake`'s flow, or by manually inserting a row into the job queue
  with a real `job_id` if that branch isn't merged yet), then **force-close the app**. Confirm,
  without reopening it yourself, that a notification arrives once the job completes.
- This is explicitly not something a unit test can prove — the brief's own bar is behavioral
  ("survives the app being closed"), so the definition of done here is a real device test, described
  in your PR/commit message with what device/OS version you tested on, not just "tests pass."
- Backoff behavior is unit-testable (mock a failing HTTP client, assert the delay grows) — write
  that test even though the main behavior above needs a real device.

## Out of scope for this branch

The instruction screen, the review screen UI itself (you only need to know its route name to
deep-link to it), export/re-share.
