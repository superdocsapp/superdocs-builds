# PROGRESS.md — dated log, append only, most recent entry on top

Read `TASK.md` first for orientation. This file is the running record of what actually happened
and what was decided along the way that `TASK.md` might not reflect yet.

---

## 2026-08-17 (later same day) — Decided Android-only for now; share-intake was dead code; two more real bugs found and fixed on-device

**Decision**: iOS work is explicitly deferred (see `TASK.md`'s "Platform focus" note) — no Xcode
on this machine, only the App Store can provide one, and that needs a real person's Apple ID.
Everything below is Android, verified on the real `SuperDocs_Pixel` emulator again.

- **`ShareIntentHandler` was defined but never actually used.** `main()` called
  `runApp(SuperDocsApp(...))` directly — the whole class that listens for a real OS share intent
  and navigates to the instruction screen was dead code. This is not a small thing: it's the
  literal feature `share-intake` exists to build ("receive a document... share it to this app").
  **Fixed**: `runApp(ShareIntentHandler(child: SuperDocsApp(...)))`, plus a real structural fix it
  needed to work at all — `ShareIntentHandler` sits *above* `MaterialApp` in the tree, so it has no
  `Navigator` ancestor to call `Navigator.of(context)` on. Added a `GlobalKey<NavigatorState>`
  (`SuperDocsApp.navigatorKey`) and switched to `navigatorKey.currentState?.pushNamed(...)`.
  **Verified live**: pushed a real file onto the emulator (`adb push`), fired a real
  `ACTION_SEND` intent at the app via `adb shell am start` (simulating another app sharing to us,
  not a synthetic in-app test), and it correctly opened straight to the instruction screen with
  the real filename shown. Typed an instruction, tapped Go, and the real file uploaded and started
  an edit successfully — the full share-intake path now genuinely works, not just compiles.
- **`home_screen.dart`'s "New Edit" button sent placeholder `[1, 2, 3, 4]` bytes.** Confirmed live
  by actually tapping through the flow: real `400 {"detail":"Invalid DOCX file: File is not a zip
  file"}`. **Fixed**: this entry point has no real file picker (that's out of scope for
  `share-intake`, which handles *receiving* a file, not picking one) — it now omits `fileBytes` so
  `instruction_screen.dart`'s own valid embedded sample DOCX is used, which is what it was already
  built to fall back to.
- **`POST_NOTIFICATIONS` was declared in the manifest but never requested at runtime.** Android
  13+ requires an explicit runtime grant separate from the manifest declaration. Confirmed via
  `adb shell dumpsys package ... POST_NOTIFICATIONS`: `granted=false`, even after the app had run
  and its background poll had already fired successfully — the poll worked, but no notification
  could ever have appeared. **Fixed**: `BackgroundService.initialize()` now calls
  `requestNotificationsPermission()` on the Android-specific plugin implementation. Verified live:
  the real system permission dialog appeared on a fresh install, and after granting it (once via
  the real dialog, once via `adb shell pm grant` to keep testing moving),
  `dumpsys package` showed `granted=true`.
- **`callbackDispatcher()` (the WorkManager background-isolate entry point) never called
  `WidgetsFlutterBinding.ensureInitialized()`.** This is a well-known Flutter background-isolate
  requirement — without it, plugin method channels can silently fail. Real symptom that led here:
  `dumpsys jobscheduler`'s execution history proved the background poll task genuinely ran to
  completion while the app was force-closed (`START` → `STOP: app called jobFinished`, confirmed
  twice, at real, separate timestamps, well after `am force-stop`) — the brief's actual hardest
  bar, working — but the job's persisted local status never changed and no notification appeared,
  even with the permission fix above in place. **Fixed** by adding the missing
  `WidgetsFlutterBinding.ensureInitialized()` call as the first line of `callbackDispatcher()`.
- **Honestly unresolved**: after the fix above, I could not get a *specific* newly-created job to
  be the one an actual periodic execution checked within this session's testing window — Android's
  WorkManager enforces a real minimum ~15-minute periodic interval, `registerPeriodicPoll()` uses
  the default `ExistingPeriodicWorkPolicy` (which keeps the existing schedule across app relaunches
  rather than resetting it), and manually force-running the job via `adb shell cmd jobscheduler run
  -f` repeatedly landed on executions that happened *before* the specific test job existed in the
  queue. The `WidgetsFlutterBinding` fix is real and necessary regardless (a background isolate
  without it is broken by definition, and this was confirmed missing, not assumed), but "does a
  notification fire for a job that completes while the app is closed" needs a longer, real-time
  test — start an edit, then genuinely wait 15-20 minutes with the app untouched — to fully close
  out. Flagged here rather than claimed as proven, since the actual mechanism (poll survives
  closure) is proven but the full chain through to a visible notification isn't yet.
- `flutter analyze` clean (style-only info/warnings) and all 5 unit tests still pass after these
  changes.

Full session: installed the missing toolchain, made the project genuinely buildable, then proved
the whole user flow works by actually running it on a real Android emulator against the real
SuperDocs API — not just reading code or running unit tests. Nine real bugs found this way, eight
fixed, all backed by a real crash, a real error dialog, or a real HTTP response, not by inspection.

**Toolchain, from nothing to a real running app:**
- Flutter wasn't installed at all. Installed via `brew install --cask flutter` (3.47.0).
- `ios/` didn't exist (no Share Extension target, no Xcode project at all) and `android/` only had
  a hand-written `AndroidManifest.xml` (no Gradle files, no `MainActivity.kt`) — the Dart source
  under `lib/` for all four conceptual branches existed, but nobody had ever run `flutter create`
  or tried to compile any of it. Ran `flutter create --platforms=ios,android,macos --org
  com.superdocs .` in place — verified first (via `diff` against a backup) that it left the
  existing `AndroidManifest.xml` untouched rather than overwriting the custom share-intent filters
  already written into it.
- Android build tooling (SDK, a full `SuperDocs_Pixel` AVD, Gradle 9.1.0/9.3.1 dist caches) turned
  out to already exist on this machine from earlier, separate work — just not wired up. Pointed
  Flutter at it (`flutter config --android-sdk`, `--jdk-dir` after installing a keg-only
  `openjdk@17` via `brew install openjdk@17`, since the cask-based JDK installer needs an
  interactive sudo password this session can't provide).
- Gradle's own wrapper download of 9.3.1 timed out over Java's `HttpURLConnection` even though
  `curl` reached the same host fine — downloaded the zip with `curl` directly into gradle's own
  wrapper-dist cache location and marked it complete (`.ok` marker), sidestepping Java's networking
  entirely rather than fighting it.
- **iOS/macOS remain hard-blocked**: no full Xcode is installed, only the command-line-tools stub
  (`xcodebuild` isn't even on `PATH`). Getting a full Xcode install needs the App Store and a
  signed-in Apple ID — genuinely requires the user, not something scriptable from here.

**Real API verification (resolves logged assumption #2 for good):**
- Signed up for a real SuperDocs account via the documented agent self-signup flow
  (`POST /v1/agents/signup`, `terms_accepted: true`) with the user's explicit go-ahead. Free tier,
  500 ops/month, credentials saved to `~/.superdocs/agent_credentials.json` per the docs.
- Fetched the real `https://api.superdocs.app/openapi.json` (not a docs summary) for the exact
  schema of every one of the four core endpoints, then drove one real document through the entire
  upload → chat/async → poll → (auto-)approve → export loop with real HTTP calls. A real `.docx`
  came back (confirmed via `file`, 37KB, valid OOXML). Full corrected contract is in `TASK.md`.

**Nine real bugs found, eight fixed:**
  1. `uploadDocument()` always sent `session_id: null` — the real API does not auto-generate one,
     so no upload ever persisted or returned a usable session_id. **Fixed**: generate a UUID
     client-side (`package:uuid` added to `pubspec.yaml`).
  2. `JobStatusResult.fromJson` read `document_changes` at the top level; the real shape nests it
     under `result.document_changes`. **Fixed.**
  3. `home_screen.dart`/`background_service.dart` checked for a `'processing'` status that doesn't
     exist — real value is `'in_progress'`. In `background_service.dart` this was the serious one:
     the "still active" poll filter excluded `in_progress` jobs, so polling stopped the moment a
     job left `pending`. **Fixed** in both files.
  4. `approve()` never sent the required `job_id` field — every real call 422'd. **Fixed** —
     signature now requires `jobId`; updated call sites in `review_screen.dart` and `TASK.md`.
  5. `export()`'s filename parsing naive-split on `"filename="`, which also matches inside the real
     header's trailing `filename*=UTF-8''...` (RFC 5987) segment, corrupting the filename.
     **Fixed** with a regex extracting only the quoted value.
  6. A job can go straight from `pending` to `completed` with no `awaiting_approval` step
     (auto-approved). First found via the curl-based API test; **then reproduced live on-device**:
     tapping Approve on such a job hit a real `400 {"detail":"Job is not awaiting approval (status:
     completed)"}` dialog. **Fixed**: `_handleApprove`/`_handleReject` in `review_screen.dart` now
     check `_statusResult?.status` and skip the doomed `approve()` call when already `completed`.
  7. `workmanager: ^0.5.2` doesn't compile against this Flutter version at all — real Kotlin
     compile errors (`Unresolved reference 'ShimPluginRegistry'`, `'registerWith'`, etc.) from
     legacy v1-embedding shim code inside the old plugin version itself. **Fixed**: bumped to
     `^0.10.0` (resolved 0.10.7) — the Dart-facing API our code calls
     (`initialize`/`executeTask`/`registerPeriodicTask`/`Constraints`/`NetworkType`) is unchanged,
     so no application code needed to change, only the pubspec constraint.
  8. Gradle build itself failed twice more on real, concrete config gaps: `compileSdk` needed
     raising to 37 (`receive_sharing_intent` requires it; `flutter.compileSdkVersion` only gave 36),
     and `flutter_local_notifications` requires core library desugaring enabled. **Fixed** in
     `android/app/build.gradle.kts` (`compileSdk = 37`, `isCoreLibraryDesugaringEnabled = true`,
     `coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")`).
  9. `home_screen.dart`'s "New Edit" quick-action button passed placeholder `[1, 2, 3, 4]` as
     `fileBytes` — not a real file. Confirmed live: tapping through onboarding → New Edit → Go
     produced a real `400 {"detail":"Invalid DOCX file: File is not a zip file"}`. **Fixed**: this
     entry point has no real file picker yet (that's `share-intake`'s job), so it now omits
     `fileBytes` entirely, letting `instruction_screen.dart`'s own valid embedded sample DOCX
     (`kValidSampleDocxBytes`) be used as the demo fallback it was already built for.
  - Also found and fixed a build-blocking XML syntax error of my own making while fixing bug #8's
    manifest: an inline code comment containing a literal `--` inside an XML comment is illegal
    (`Error parsing AndroidManifest.xml` with no further detail) — worth remembering, since the
    error message alone doesn't say why.
  - Not a bug, a real constraint: the generated `android/app/build.gradle.kts` sets `namespace =
    "com.superdocs.superdocs_share_sheet_app"`, but the hand-written manifest still had
    `package="com.superdocs.share_sheet_app"` (no doubled prefix) — modern AGP rejects a
    `package=` attribute on `<manifest>` outright now. Removed it from the manifest (namespace
    already governs this via Gradle); this doesn't rename anything else, App IDs everywhere else
    already used the doubled form.

**Proof, not assertion — the full loop was run for real, once, start to finish**, on the real
`SuperDocs_Pixel` emulator (Android 13, `google_apis` image) with the real API key from the account
above: onboarding → save key → New Edit → type an instruction → real upload+edit (fixed by #9) →
job appears `PENDING` on the home screen → open it → review screen renders the real edited HTML
with the AI's actual change highlighted (proves fix #2) → tap Approve → correctly skips the doomed
approve call for this auto-completed job (proves fix #6) → exports a real file → hands off to the
real native Android share sheet with `edited_document.docx` ready to send. Screenshots taken at
every step. `flutter analyze` and `flutter test` are clean (5/5 tests pass, including two rewritten
to assert the exact real-world shapes that caused bugs #4 and #5).

**Still not done**: the iOS side entirely (no Share Extension, blocked on Xcode as above), a real
device/emulator test of the *background* polling behavior specifically (surviving a force-close —
the brief's hardest bar for `background-engine`; today's run only proved the foreground flow),
`share-intake`'s actual OS share-sheet intent handling (only the manual "New Edit" button was
exercised, not receiving a real shared file from another app), and a real file picker for that
"New Edit" entry point (still using the embedded sample DOCX, per fix #9).

---

## 2026-08-10 — Comprehensive Ambiguities & Scope Update (Android First Focus)

- **Platform Focus Update**: User specified to target **Android first** while building in Flutter (cross-platform framework). iOS Share Extension setup (`ios/ShareExtension/`) and iOS `BGAppRefreshTask` setup will remain stubbed/modularized so cross-platform Flutter code runs cleanly on Android target now and can easily activate iOS targets later.
- **Ambiguities & Logged Assumptions Documented**:
  1. **Upload Format (`/v1/documents/upload-base64`)**: Unverified if backend accepts raw PDF/DOCX base64 bytes directly or requires pre-parsed HTML. Need live API call verification during implementation.
  2. **`chunk_diffs` Parsing**: Client handles both parsed JSON objects and raw stringified double-JSON payloads defensively.
  3. **API Key Onboarding Validation**: Onboarding screen validates key formatting and offers instant connection test.
  4. **Reject Path Status**: Standardized local job queue status on Reject to `"cancelled"` to match SuperDocs backend enum (`pending`, `processing`, `awaiting_approval`, `completed`, `failed`, `cancelled`).
  5. **Post-Approval Finalization**: Approving an async edit job triggers a fast status check poll before requesting export (`POST /v1/documents/export`).
  6. **Android Share Intent**: Standardized on `receive_sharing_intent` for Android `ACTION_SEND` intents (`application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `text/plain`).
  7. **Android Background Engine**: Standardized on `workmanager` and `flutter_local_notifications` for Android background polling surviving app closure.
- **Destination Target**: Flutter project scaffold and code being placed in `superdocs-share-sheet-app` and integrated into `/Users/jainamshah/doctask-jainam-shah/extensions/superdocs-share-sheet-app`.

---

## 2026-08-10 — Spec written, no code yet

- Wrote the design spec (`docs/superpowers/specs/2026-08-10-mobile-share-sheet-app-design.md`),
  `TASK.md`, and this file. Nothing else exists in this repo yet — no Flutter project scaffold, no
  branches beyond `main`, zero lines of app code.
- Stack decided: Flutter, bare workflow. (User corrected an earlier draft that proposed React
  Native.)
- Corrected the API flow while writing `TASK.md`: upload once via `/v1/documents/upload-base64` to
  get a `session_id`, then chat by `session_id` — no need to resend the document on every
  instruction. (An earlier draft of the design spec had this wrong; `TASK.md` is the corrected
  version, treat it as authoritative over the original spec doc where they differ.)
- Three assumptions logged as unverified in `TASK.md` — most important one: whether
  `/v1/documents/upload-base64` actually accepts real PDF/DOCX bytes or only pre-extracted HTML.
  **Nobody has made a real API call against a real SuperDocs account yet.** This is the single
  highest-priority thing for whoever starts `foundation` to check first, before writing the
  `SuperDocsClient` implementation for real.
- Branch/task-doc structure decided (4 branches: `foundation`, `share-intake`,
  `background-engine`, `review-export`) but the branches themselves don't exist yet and the
  per-branch task docs in `docs/tasks/` haven't been written yet either — that's the next step,
  not done as of this entry.

**Next action for whoever picks this up next**: write the four files in `docs/tasks/`, then create
the `foundation` branch and confirm assumption #2 above against a real account before writing any
other code.
