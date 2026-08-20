# Branch: `share-intake`

**Read this whole file before writing code. If you haven't read `TASK.md` in the repo root yet,
stop and read that first.**

## Your job, in one sentence

Let a user share a file into this app from any other app (Mail, Files, Messages), type or dictate
one instruction, and kick off the edit — that's taps 1 and 2 of the brief's "three taps and one
sentence."

## Before you start: check whether `foundation` has merged

Run `git log --all --oneline --graph` and `git branch -a`. If `foundation` is merged into `main`,
branch off `main` and use the real `SuperDocsClient`. If it hasn't merged yet, branch off `main`
anyway and build against the exact interface documented in `TASK.md`'s "shared interface" section
as a stub (a fake implementation returning canned values) — swap in the real import once
`foundation` lands. Do not block on `foundation` finishing; do not redefine the interface yourself.

## What to build

1. **iOS Share Extension**: a native Swift Share Extension target (`ios/ShareExtension/`) that
   accepts documents (PDF, DOCX, plain text) shared from other apps, writes the file into a shared
   App Group container, and opens the main app with a URL scheme or deep link carrying a reference
   to it. Use the `receive_sharing_intent` Flutter package's documented iOS setup for this — it
   handles most of this scaffolding; don't hand-roll it if the package covers it.
2. **Android share intent**: handle `ACTION_SEND` intents for common document MIME types
   (`application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`,
   `text/plain`) via the same package's Android side.
3. **`lib/screens/instruction_screen.dart`**: replaces the stub route from `foundation`. Shows the
   shared file's name, one multiline text field (the OS keyboard's built-in mic button covers
   "dictate" — do not add a custom speech-to-text package, it's not needed), and a "Go" button.
   On tap: call `SuperDocsClient.uploadDocument()` then `.startEdit()`, then persist the result (see
   next item) and navigate to the home screen with a "processing" state shown for that job.
4. **`lib/storage/job_queue.dart`**: local persistence (SQLite via `sqflite`, or a simple JSON file
   — pick whichever is less code) for the list of in-flight jobs: `{ jobId, sessionId, filename,
   status, createdAt }`. This is the shape `background-engine` will read from and write status
   updates to — keep the field names exactly as listed here since that branch depends on them.

## Owns

`ios/ShareExtension/`, `lib/screens/instruction_screen.dart`, `lib/storage/job_queue.dart`,
Android manifest changes for intent filters.

## Definition of done

- Sharing a real PDF from the iOS Files app into this app opens it directly to the instruction
  screen with the filename shown.
- Same for Android, sharing from a file manager or Gmail attachment.
- Typing an instruction and tapping Go results in one row appearing in `job_queue`'s storage with
  status `pending` or `processing`, and a real `job_id` from a real API response (or the stub, if
  `foundation` hasn't merged yet — note in your commit message which one you tested against).
- Dictation works via the OS keyboard with zero custom code — verify by actually tapping the mic
  icon on the keyboard, not just assuming it works because you added a multiline `TextField`.

## Out of scope for this branch

Background polling of job status after the initial `startEdit()` call (that's
`background-engine`), the review screen (that's `review-export`), export/re-share.
