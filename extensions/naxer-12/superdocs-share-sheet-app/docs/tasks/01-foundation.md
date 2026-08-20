# Branch: `foundation`

**Read this whole file before writing code. If you haven't read `TASK.md` in the repo root yet,
stop and read that first — it has the overall project context this file assumes you already have.**

## Your job, in one sentence

Build the SuperDocs API client, the core data models, and the app's navigation shell — the
foundation every other branch (`share-intake`, `background-engine`, `review-export`) builds on top
of. Nothing user-facing beyond a working onboarding screen and empty placeholder screens for the
others to fill in.

## Do this first, before writing any client code

**Already done, 2026-08-17 — do not repeat.** A real SuperDocs account was created via the agent
self-signup flow and the full upload → edit → poll → approve/auto-complete → export loop was run
live against it. Logged assumption #2 is resolved; see `TASK.md`'s "API contract — verified live"
section for the full corrected contract and the six real bugs it caught and fixed in
`lib/api/superdocs_client.dart` and friends. The contract below is now the verified real shape, not
a guess — no need to re-verify it, just build against it.

## API contract to implement (verified live, 2026-08-17)

Base URL: `https://api.superdocs.app`. Every request needs header
`Authorization: Bearer <api_key>`.

**Upload**: `POST /v1/documents/upload-base64`
```json
// request — session_id is NOT auto-generated if omitted; generate a UUID client-side and always
// send one, or the document won't persist and you'll get no session_id back at all.
{ "filename": "contract.pdf", "file_base64": "<base64 file bytes>", "session_id": "<client UUID>", "return_html": true }
// response
{ "html": "...", "session_id": "...", "filename": "...", "chunks_count": 12, "version_id": "...", "page_setup": null, "persisted": true }
```

**Start an edit**: `POST /v1/chat/async`
```json
// request
{ "message": "<the user's one-sentence instruction>", "session_id": "<from upload>" }
// response
{ "job_id": "...", "session_id": "...", "status": "pending" }
```

**Poll job status**: `GET /v1/jobs/{job_id}`
```json
// response, once ready — the result is nested under "result", not top-level
{
  "status": "awaiting_approval",
  "result": {
    "document_changes": { "updated_html": "...", "chunk_diffs": [ { "chunk_id": "...", "action": "update", "content": "..." } ] }
  }
}
```
Status values: `pending`, `in_progress`, `awaiting_approval`, `completed`, `failed`, `cancelled`.
**A job can go straight to `completed` with no `awaiting_approval` step** if the edit was
auto-approved — handle both, don't assume approval is always needed.

**Approve**: `POST /v1/chat/{session_id}/approve`
```json
// request — job_id is required, a bare {approved} 422s
{ "job_id": "...", "approved": true }
// response
{ "status": "approved", "job_id": "...", "message": "..." }
```

**Export**: `POST /v1/documents/export`
```json
// request
{ "session_id": "...", "format": "docx" }
// response: binary file body. Content-Disposition carries BOTH filename="..." and a
// filename*=UTF-8''... form on the same line — parse only the quoted filename="..." part,
// a naive split on "filename=" picks up junk from the second form too.
```

## What to build

1. Flutter project scaffold (`flutter create`), reasonable package name, both iOS and Android
   targets present and building (even if the app just shows a blank screen).
2. `lib/api/superdocs_client.dart` — implements exactly the `SuperDocsClient` interface specified
   in `TASK.md`'s "shared interface" section. Do not change that interface's method signatures
   without updating `TASK.md` and flagging it in `PROGRESS.md` — the other three branches are
   building against it as-is, possibly before this branch merges.
3. `lib/models/` — `UploadResult`, `ChatJobResult`, `JobStatusResult`, `ExportResult`, matching
   `TASK.md` exactly.
4. `lib/storage/api_key_store.dart` — wraps `flutter_secure_storage` for saving/reading the user's
   SuperDocs API key.
5. `lib/screens/onboarding_screen.dart` — a single screen: paste your API key, save it, continue.
   Nothing fancier.
6. `lib/app.dart` — navigation shell with named routes for: onboarding, home (can be a stub list
   view for now), instruction (stub), review (stub). The other branches will fill in the real
   instruction and review screens; your job is just that the routes exist and navigate correctly.
7. Unit tests for `SuperDocsClient` against a mocked HTTP client (use `package:http`'s testable
   client or `mockito`) — one test per method, covering the request shape sent and the response
   parsed correctly.

## Owns (files this branch is the only one touching)

`pubspec.yaml`, `lib/api/`, `lib/models/`, `lib/storage/api_key_store.dart`, `lib/app.dart`,
`lib/screens/onboarding_screen.dart`, `ios/` and `android/` project scaffold files.

## Definition of done

- `flutter test` passes for the API client's unit tests.
- App builds and runs on both an iOS simulator and an Android emulator, showing onboarding then an
  empty home screen after saving a key.
- A real call to each of the four API methods (against a real account) has been made at least once
  manually and the response shape confirmed to match what's documented above — corrections written
  into this file and `TASK.md` if reality differed.
- `PROGRESS.md` has a new dated entry summarizing what was confirmed/corrected.

## Out of scope for this branch

Share intent handling, background polling, the real instruction/review screen UI, export-then-share.
Those are the other three branches' jobs — build the stub screens/routes they'll fill in, nothing more.
