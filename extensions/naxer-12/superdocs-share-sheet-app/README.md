# SuperDocs Mobile

A Flutter app that lets you edit a document from your phone in three taps: share a file into the
app from Mail, Messages, or Files, type or dictate one instruction, review the AI's proposed edit,
and share the finished file back out. It's a thin client on top of SuperDocs' own API — this app
does no editing itself.

Built for SuperDocs' engineering round, assigned build: mobile share-sheet app.

## What it does

1. Share a document into the app (or open it and tap "New Edit").
2. Type or dictate one instruction — the OS keyboard's built-in mic covers dictation, no custom
   speech-to-text needed.
3. The app uploads the document and starts the edit in the background — you can close the app here.
4. A background task polls for completion and notifies you when it's ready to review.
5. Review the change highlighted in a WebView, approve or reject.
6. Export the finished file and hand it straight to the OS share sheet to send onward.

## What SuperDocs features it uses

- `POST /v1/documents/upload-base64` — uploads the shared file and starts a session
- `POST /v1/chat/async` — sends the edit instruction as a background job
- `GET /v1/jobs/{job_id}` — polls job status, including the async/background-completion path
- `POST /v1/chat/{session_id}/approve` — the human-approval gate before anything is final
- `POST /v1/documents/export` — exports the approved edit back to a real file

## Platform status

**Android**: built and verified on a real device/emulator — the full flow above (share intent,
upload, edit, review, approve, export, background completion surviving the app being force-closed)
was run end to end against a live account.

**iOS**: not built. This needs a Share Extension target and a background-task registration that
require a full Xcode install and a signed-in Apple ID to build and test — genuinely blocked, not
skipped by choice. The project scaffold (`ios/`) exists so this can be picked up directly.

## How to run it

Requires the [Flutter SDK](https://docs.flutter.dev/get-started/install) and, for Android, the
Android SDK + an emulator or device.

```bash
flutter pub get
flutter run
```

On first launch, paste a SuperDocs API key (get one at [use.superdocs.app](https://use.superdocs.app)
or via the agent self-signup flow documented at [docs.superdocs.app](https://docs.superdocs.app)) —
stored locally via `flutter_secure_storage`, never hardcoded.

Running the tests:

```bash
flutter test
```

## Known limitations

- The in-app "New Edit" quick-action button (as opposed to sharing a real file in) uses a bundled
  sample document rather than a real file picker, since that entry point's job is just to
  demonstrate the flow, not replace share-intake.
- Background completion is proven to survive the app being force-closed at the OS level (confirmed
  via Android's own job scheduler logs showing the poll task run to completion while closed), but a
  full real-time test of the resulting notification firing for one specific job needs longer than a
  single working session — Android's real minimum background-poll interval is about 15 minutes.

## Full build log

The complete, dated log of what was verified against the real API, every bug found and fixed, and
why — see `PROGRESS.md` and `TASK.md` in this folder.
