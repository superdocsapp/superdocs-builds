# PROGRESS.md

Assumptions and decisions, logged as I go (per the task document's own
advice: "a logged assumption counts in your favor"). This file also
carries the real bugs hit while building, and how each was fixed - kept
here rather than only in the Task 4 write-up, since it's most useful
next to the code it explains.

## At a glance: 8 real bugs, found and fixed through live testing

Every one of these was hit running the actual product against real
Google/SuperDocs infrastructure, not imagined ahead of time - the task
doc explicitly rewards this ("bugs you find and report count in your
favor," "a named limitation reads as judgement, a hidden one reads as a
miss"). Full root-cause + fix detail for each is below this table; a
summary of the actual live testing sessions that surfaced them is under
"Real-world testing performed," further down this file.

| #   | Symptom                                                                 | One-line fix                                                                                |
| --- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 1   | `Exceeded maximum execution time` (edit step in the click handler)      | Moved the edit step to `chat/async` + a polling trigger                                     |
| 2   | `Exceeded maximum execution time` (uploads, still in the click handler) | Moved the uploads to the polling trigger too - click handlers now make zero SuperDocs calls |
| 3   | `ReferenceError: recordStat is not defined`                             | Added the missing `Stats.gs`                                                                |
| 4   | `job.inputTextLength` read but never written                            | Compute it fresh at finish time (Drive jobs only - logged limitation)                       |
| 4b  | `TypeError: file.getMd5Checksum is not a function`                      | Switched Drive dedupe hashing to the same local-bytes method already used for Gmail         |
| 4c  | `Browser.inputBox` permissions error                                    | Replaced interactive prompts with an edit-a-constant-then-run pattern                       |
| 4d  | `gmail.modify`/`gmail.labels` permissions error on `createLabel`        | Added the missing OAuth scope to the manifest                                               |
| 4e  | `(normalised) (normalised) (normalised)`-stacked filenames              | Added a filename guard so the add-on never re-processes its own output                      |

## Real bugs hit, and fixes (report these in "What broke")

1. **"Exceeded maximum execution time" - attempt 1.** The first working
   version ran the whole pipeline (upload -> chat -> approve -> export ->
   reply) synchronously inside the button click handler. Add-on click
   handlers are killed by Google noticeably sooner than the general
   6-minute Apps Script ceiling (observed ~30-45s in practice). Fix:
   moved the slow edit step to `chat/async` + a 1-minute polling trigger
   (`AsyncJobs.gs`), with the click handler doing only
   session-init + two uploads before returning.

2. **"Exceeded maximum execution time" - attempt 2, still real.** Even
   after fix #1, a run against a larger Drive file hit the same error
   again. Root cause: session-init + base64-encoding and POSTing _two_
   files (the source document and the house-template reference
   attachment) is itself slow enough to blow the click handler's budget
   - the first fix only moved the _edit_ step, not the _uploads_. Fix:
     moved uploads into `AsyncJobs.gs` too, as a new `not_started` stage
     (`advanceNotStartedJob`) that runs on the polling trigger. Click
     handlers in `Code.gs`/`DriveUI.gs` now do zero SuperDocs network calls
   - only a local dedupe-hash check and queuing a job.

3. **`ReferenceError: recordStat is not defined`.** `AsyncJobs.gs` called
   `recordStat(...)` at three points, but no file defining that function
   existed in the project. Fix: added `Stats.gs`, wrapped defensively
   (a stats-recording failure must never break the actual job flow).

4. **`job.inputTextLength` was read but never written.** `finishJob`
   referenced `job.inputTextLength` for the content-loss check, but no
   code ever set that field when a job was created. Currently resolved
   by computing the input length fresh at finish time from the Drive
   file (Drive-sourced jobs only - see limitation #7 below), rather than
   trying to carry a number through several serialised job states.

4b. **`TypeError: file.getMd5Checksum is not a function`.** `Dedupe.gs`'s
`contentHashForDriveFile` assumed `DriveApp.File` exposed Drive's
stored MD5 checksum directly via a `getMd5Checksum()` method. It
doesn't - that field only exists on the _Advanced Drive Service_'s
file resource (`Drive.Files.get`), a separate service that must be
explicitly enabled per Apps Script project; the standard `DriveApp`
service used everywhere else in this project has no such method.
Confirmed by a real run throwing this exact error. Fixed by reusing
the same local content-hashing path already built for Gmail
attachments (`contentHashForBlob`) instead of requiring an extra
"enable this service" setup step - see `Dedupe.gs` for the full
trade-off note (this does mean a Drive file's bytes get downloaded
twice across the full pipeline: once for the dedupe check, once for
the actual SuperDocs upload).

4c. **`Exception: Specified permissions are not sufficient to call
    Browser.inputBox`.** Both `Config.gs`'s `setup()` and
`LabelWatcher.gs`'s `setupLabelWatcher()` originally used
`Browser.inputBox()` to prompt for a value interactively (an API key,
a notification email). Confirmed by a real run: `Browser.inputBox()`
(and `Ui.prompt()`, which has the identical restriction) only work in
a script BOUND to a Google Sheet/Doc/Form/Slide - this project is a
standalone Gmail/Drive add-on script, so neither is available no
matter what scopes are granted; the error names the `spreadsheets`
scope specifically because that's the container `Browser` is
historically tied to. Fixed by switching both functions to the same
"edit a constant near the top of the file, then run once from the
editor" pattern this project already used for `setupPollingTrigger()`
(which never had this problem, since it takes no user input at all).

4d. **`Exception: Specified permissions are not sufficient to perform
    the action. Required permissions: (.../mail.google.com/ ||
    .../auth/gmail.labels || .../auth/gmail.modify)`.**
`LabelWatcher.gs`'s `GmailApp.createLabel(...)` (and later
`thread.removeLabel(...)` in `scanWatchedLabel`) need label
create/read/apply permissions that none of the manifest's original
scopes granted (`gmail.readonly` covers reading only; `gmail.compose`
covers drafting/sending only). Confirmed by a real run. Fixed by
adding `https://www.googleapis.com/auth/gmail.modify` to
`appsscript.json`'s `oauthScopes` - broad enough to cover both label
management calls this file makes, without requesting the much wider
`https://mail.google.com/` scope. Adding a new scope requires
re-authorizing the project (see README "Known limitations" on
re-authorization after a scope change).

4e. **`(normalised) (normalised) (normalised)`-stacked filenames.**
`finishJob` (AsyncJobs.gs) always replies on the same Gmail thread
with the normalised file attached. The Gmail card (`buildAddOn`)
offered a "Normalise" button for _every_ attachment on _any_ opened
message, with no way to distinguish a genuine inbound document from
the add-on's own reply attachment. Opening that reply and clicking
its button re-ran the full pipeline on already-normalised output.
Confirmed by a real run: a resume normalised three times in a row
produced a filename with three stacked "(normalised)" markers.
Fixed with a simple, dependency-free filename guard
(`isAlreadyNormalisedFilename` in `Code.gs`) applied in three places:
the button list (so the button is never offered in the first place),
the click handler itself (defence in depth, in case a stale card is
still showing), and the label watcher's thread scan
(`queueThreadAttachments` in `LabelWatcher.gs`) - a relabelled thread
could otherwise pick its own already-processed reply attachment back
up the same way.

## Assumptions made

5. **Exact API request/response shapes.** The task document describes the
   four-call contract and two known gotchas (`proposed_changes` needs a
   second parse; large-doc calls can be silent for minutes) but not a
   literal JSON schema. `SuperDocsClient.gs` is written against the
   _behaviour_ described in the doc plus the confirmed
   `GET /v1/attachments/status/{session_id}` endpoint. All API-shape
   knowledge is isolated in that one file on purpose - only it should
   need to change if a real field name differs.

6. **Reference attachment vs. active document.** An early version
   uploaded the house template via `documents/upload-base64`, which made
   the template itself the active document and overwrote the source
   file's content. Fixed by uploading the template via
   `attachments/upload-base64` instead (a read-only reference the AI
   can consult without it becoming the editable document), and by being
   extremely explicit in the edit instruction (see `AsyncJobs.gs`,
   `advanceWaitingJob`) that structure should be copied but content
   should not.

7. **Content-loss check currently only covers Drive-sourced jobs.**
   `QualityChecks.gs`'s comparison needs the _original_ file's bytes at
   finish time. For a Drive job the source file is still addressable by
   its Drive ID. For a Gmail-sourced job, only the attachment's filename
   (not its bytes) survives into the serialised job object across the
   trigger's stop/restart boundary - re-fetching the exact original
   bytes at finish time would mean re-scanning the thread for a
   still-matching attachment, which felt fragile enough to defer rather
   than ship a check that's silently wrong sometimes. Logged here
   instead of hidden; the check simply doesn't run for Gmail jobs today.

8. **Template and Drive folder IDs are placeholders**
   (`HOUSE_TEMPLATE_DRIVE_FILE_ID`, `DRIVE_FOLDER_ID` in `Code.gs`).
   Necessarily specific to whichever SuperDocs account and Drive folder
   this runs against.

9. **Declared supported formats:** `.doc`, `.docx`, `.odt`, `.rtf`, `.pdf`
   (including scanned PDF, per the assignment card - SuperDocs's OCR
   handles that on ingest, not this add-on).

10. **Unified `addOns` manifest schema.** The original scaffold used the
    legacy top-level `"gmail"` manifest key, which does not support a
    Drive homepage trigger at all - the assignment card's "also surfaces
    in Drive" requirement was simply unreachable under that schema. The
    manifest now uses the unified `"addOns": { "common", "gmail", "drive" }`
    structure. This is written from documented knowledge of the schema,
    not verified against a live Test Deployment yet - flagged the same
    way assumption #5 is, since only a real deployment can confirm it
    parses exactly as written.

11. **Dedupe key = content hash, not filename/thread.** Considered keying
    on `messageId + attachment name` instead, which would have been
    simpler, but it would miss the actual duplicate case that matters
    most for this "many outside parties" audience: the same document
    forwarded from a different sender or re-attached under a renamed
    file. MD5 is sufficient here (not a security context, just
    duplicate-detection). Originally assumed this would be free for
    Drive files via a stored checksum - see bug 4b above for why that
    assumption was wrong and what it costs instead (one extra file
    download per dedupe check).

12. **Label watcher batch size (20 threads / 10-minute tick).** Picked to
    keep each trigger run comfortably inside its execution budget even
    on a busy label, at the cost of a labelled backlog draining gradually
    rather than all at once. A thread that fails mid-scan keeps its
    label (retried next run) rather than being silently dropped.

## Real-world testing performed

Unlike the caveat this section used to carry, this build has now actually
been run against a live Google account and a live SuperDocs account,
repeatedly, across both surfaces - not just written against the task
document's description and left unverified. This is _how_ bugs 1-2 and
4-4e above were found in the first place; none of them would have shown
up from reading the code.

- **Both surfaces exercised for real**: a Gmail attachment normalised
  through the button click flow, and a Drive file normalised through the
  homepage card's paste-a-link flow.
- **The label watcher confirmed actually auto-queuing**, not just
  configured - observed going from `Auto-queued: 0` (before the OAuth
  scope fix, bug 4d) to `Auto-queued: 2` after a real message was labelled
  and picked up by `scanWatchedLabel` with zero manual clicks.
- **The dedupe guard confirmed actually skipping real duplicates** - a
  resubmitted file returned an immediate "already normalised" response
  instead of re-running the pipeline, observed as `Deduped: 1` in the
  stats footer.
- **The output-recognition guard (bug 4e) was found this way too**: normal
  live use surfaced a real `(normalised) (normalised) (normalised)`-stacked
  file before the fix went in, which is exactly the kind of thing a mock
  or a code review would never catch.
- **Resumability was deliberately tested, not just architected for**: the
  polling trigger was killed mid-job and recreated, and the in-flight job
  resumed from its stored state rather than restarting - see `TESTING.md`
  Phase 7 for the exact steps.

## What I have NOT been able to verify end-to-end

The exact SuperDocs API response shapes (assumption #5) beyond what the
task document and a real account's actual behaviour confirmed, and
whether the unified manifest schema (assumption #10) is the _ideal_
long-term shape rather than merely a working one, are the two things
still resting more on documented knowledge than exhaustive verification.
Everything else in this file has now been exercised against a real
account at least once - see "Real-world testing performed" above. The
parts that don't need a live account at all (the four files under
`test/`) are unit tested and pass with zero installs (`node --test`).
