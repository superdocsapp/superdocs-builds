# Mobile Share-Sheet App — Design Spec

> **Start with `TASK.md` in the repo root instead of this file.** This doc captures the original
> reasoning and is kept for reference, but `TASK.md` has one corrected flow (upload once, then chat
> by `session_id`, not resending the document every turn) and is the authoritative operational doc
> — this file and `TASK.md` disagree on that one point, and `TASK.md` wins.

Source: SuperDocs-Task-Engineer.pdf, Task 2, assigned build "Mobile share-sheet app" (S2).
Destination: PR into `github.com/superdocsapp/superdocs-builds`, `extensions/` folder.

## What it does

Receive a document via the OS share sheet, type or dictate one edit instruction, review the
result on a thumb-sized screen, export, and re-share — three taps, works on a poor connection by
finishing in the background even if the app is closed.

## Stack

**Flutter**, bare (not a no-code builder) — one codebase for iOS + Android. iOS still needs a
small native Share Extension target (an iOS platform requirement, not a Flutter limitation) that
hands the shared file to the main app via an App Group.

## Logged assumptions (unverified — confirm against a real SuperDocs account before building)

1. **Auth**: manual API key entry on first launch (`flutter_secure_storage`), not OAuth — SuperDocs
   has no public OAuth flow yet per the brief.
2. **File upload format**: the shared file's raw bytes go to SuperDocs' upload endpoint as-is;
   assumed the backend converts PDF/DOCX server-side ("we take documents, not raw Word XML").
   Only a summarized doc fetch was available, not a live API call — verify first thing.

## Architecture: async job + local background queue

```
Share sheet → instruction screen → POST /v1/chat/async (job_id) → persist locally, app can close
→ background poll GET /v1/jobs/{job_id} → local notification when awaiting_approval/completed
→ reopen → review screen (WebView, changed sections highlighted, bottom Approve/Reject)
→ approve: POST /v1/chat/{session_id}/approve → poll → POST /v1/documents/export
→ share sheet again, send the exported file onward
```

**v1 cut**: whole-document approve/reject only, not per-chunk (the API supports per-chunk; a
"3 of 7 changes" stepper is real extra UI for an S2 build — v2 addition, not a hidden gap).

## Task breakdown — 4 branches, mostly non-overlapping files

### Branch 1: `foundation` — lands first, defines the shared interfaces
- Flutter project scaffold, `pubspec.yaml`, app navigation shell (onboarding → home →
  instruction → review)
- `SuperDocsClient` (Dart service): wraps upload, `chat/async`, `jobs/{id}` poll, `approve`,
  `export` — the one file every other branch imports against
- Data models: `EditJob`, `DocumentChanges`, `ExportResult`
- API key onboarding screen + secure storage
- **Owns**: `lib/api/`, `lib/models/`, `lib/app.dart`, `pubspec.yaml`

### Branch 2: `share-intake`
- iOS Share Extension target + App Group handoff; Android intent handling via
  `receive_sharing_intent`
- Instruction screen: text field (OS dictation is free via the keyboard), "Go" button, calls
  `SuperDocsClient.startEdit()` from Branch 1, persists the returned `job_id` to a local pending-jobs
  list
- **Owns**: `ios/ShareExtension/`, `lib/screens/instruction_screen.dart`, `lib/storage/job_queue.dart`
- **Depends on**: Branch 1's `SuperDocsClient` interface (can build against a stub/mock of it in
  parallel, wire the real one at merge time)

### Branch 3: `background-engine`
- `workmanager` (Android) + iOS `BGTaskScheduler` wiring to poll every pending `job_id` from
  Branch 2's queue via Branch 1's client
- `flutter_local_notifications` on status change to `awaiting_approval`/`completed`/`failed`
- Backoff/retry for poor connectivity
- **Owns**: `lib/background/`, platform-specific background-task registration files
- **Depends on**: Branch 1's client + Branch 2's job-queue storage shape (agree the shape in
  Branch 1's data models, build against it directly)

### Branch 4: `review-export`
- WebView screen rendering `document_changes.updated_html` at phone viewport width, injected CSS
  highlighting changed chunks
- Bottom-pinned Approve/Reject bar
- Approve → Branch 1's `approve()` → poll → `export()` → hand the file to the OS share sheet
- **Owns**: `lib/screens/review_screen.dart`, `lib/export/`
- **Depends on**: Branch 1's client + models only

## Synthesis plan

1. Branch 1 merges to `main` first — it's small, foundational, and everything else imports its
   interfaces. (Matches how Task 1's Phase 1 skeleton had to land before its parallel tracks.)
2. Branches 2, 3, 4 are then genuinely parallelizable (as 3 worktrees, mirroring Task 1's
   Track A/B/C pattern) — they touch disjoint file sets and only share Branch 1's already-frozen
   interfaces.
3. Merge order for 2/3/4 doesn't matter functionally; merge whichever finishes first. Expect zero
   file-level conflicts between them — cross-check at merge time regardless.
4. Integration pass after all four are merged: wire navigation end-to-end (share → instruction →
   close app → notification → review → export → re-share), run once on a real iOS device and once
   on Android (Share Extensions and background execution cannot be fully verified on simulators).

## Testing

- Branch 1: unit tests for `SuperDocsClient` against a mocked HTTP layer (request shape, response
  parsing, the documented double-JSON-parse behavior on proposed changes if confirmed real).
- Branch 3: the one behavior worth real device testing, not just unit tests — background poll
  surviving app termination is the brief's explicit bar ("background completion survives the app
  being closed").
- Branch 4: WebView renders at phone width with no horizontal scroll on a real formatted document,
  not just a plain-text stub.

## Explicit non-goals for v1

- Per-chunk approve/reject
- Any auth beyond manual API key entry
- Offline editing (queuing works for the *request*; nothing here works with zero connectivity ever)
