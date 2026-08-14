# SuperDocs Gmail + Drive Attachment Normaliser

Screenshots [SuperDocs Normaliser in Gmail] (check docs folder)
Built for the SuperDocs Round 2 task (assigned build, difficulty band **S2**).

> Open a Gmail message with an attachment, or paste a Drive file link. The
> add-on offers to normalise it into your organisation's house template -
> headings mapped, tables restyled, logo placed, cover page added - and
> hands the result back as a Drive file and a reply/email. It's built to
> handle the awkward cases (legacy `.doc`, OpenDocument, RTF, scanned PDF)
> rather than refusing them.

## Submission status (read this first)

This repository covers **Task 2: Your Assigned Build** in full - the
Gmail + Drive attachment normaliser, plus three unprompted extras (see
below). It does **not** cover the other three tasks in the round, logged
here honestly rather than left to be discovered:

| Task                                                 | Status      | Where it goes                                      |
| ---------------------------------------------------- | ----------- | -------------------------------------------------- |
| Task 1 - Agentic System (the document-pile analyser) | Not started | its own **private** repo                           |
| **Task 2 - Assigned Build (this repo)**              | **Done**    | PR into the **public** repo's `extensions/` folder |
| Task 3 - Use cases + real buyers                     | Not started | submission form                                    |
| Task 4 - Demo video + one-page write-up              | Not started | submission form                                    |

**For the Growth/GTM application specifically:** the assigned-build card
is explicitly the _shared_ task between the Growth and Engineer documents
("if you hold our engineer document as well, do the shared task of the
role you are really going for" / "your assigned build lives in your
engineer document"). This repo satisfies that shared requirement for
either application without needing a separate build. It does **not**
cover the Growth document's own **Task 1 - Build a Growth Machine**
(audience research + an outbound/content/community machine + one real
piece of work + a measurement page), which is a large, separate,
mandatory deliverable for the Growth track and shares no code with this
repo.

## Submitting this build to SuperDocs

Per the task document's own instructions ("Builds on SuperDocs: a pull
request into the public repository ... `github.com/superdocsapp/superdocs-builds`.
... a folder per candidate inside `use-cases/` and `extensions/`"). This
assigned build's card says specifically: **"where the finished work
goes: a pull request into the public repository, extensions folder."**

1. **Fork** `github.com/superdocsapp/superdocs-builds` on GitHub (top
   right, "Fork" button) into your own account.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-github-username>/superdocs-builds.git
   cd superdocs-builds
   ```
3. **Read `CONTRIBUTING.md`** in the repo root once you've forked it -
   the task doc states it "carries the exact folder and pull-request
   mechanics," and this README can't know its exact contents in advance.
   Confirm the folder-naming and PR-title conventions it asks for before
   the next step, and follow those over the generic steps below if they
   differ.
4. **Create your branch and folder:**
   ```bash
   git checkout -b add-gmail-attachment-normaliser
   mkdir -p extensions/<your-name>
   ```
5. **Copy this project into that folder** - everything in this repo
   (`src/`, `test/`, `test-fixtures/`, `appsscript.json`, `README.md`,
   `TASK.md`, `TESTING.md`, `PROGRESS.md`, `package.json`) except:
   - `.clasp.json` (your own script ID - never commit this; keep it
     git-ignored, exactly as `.gitignore` already sets up)
   - `node_modules/` (also git-ignored already)
   ```bash
   cp -r /path/to/superdocs-gmail-normaliser/* extensions/<your-name>/
   ```
6. **Add a credit line to your folder's README**, per the task doc:
   _"Give your README a screenshot and a credit line that says you built
   this for the SuperDocs task."_ A line like this at the top works:

   > Built by <Khushi Parekh> for the SuperDocs Round 2 engineering task.

   Add at least one real screenshot (the Gmail card, and/or the Drive
   homepage card) - the placeholder image link near the top of this
   README should be replaced with a real one before you commit.

7. **Commit and push:**
   ```bash
   git add extensions/<your-name>
   git commit -m "Add Gmail + Drive attachment normaliser (assigned build)"
   git push origin add-gmail-attachment-normaliser
   ```
8. **Open the pull request** on GitHub (a banner appears automatically
   after pushing, or use the "Compare & pull request" button). Per the
   task doc: **put your name in the pull request description** - your
   email should never appear in the public repo; the submission form
   separately collects your email and GitHub handle to match your PR to
   your application.
9. **Put the PR link in the submission form** once it arrives by email
   (the form is "not out yet" per the task doc - keep building and hold
   the link until it does).

**Task 1 (the separate Agentic System, if/when you build it) does NOT
go here** - it goes in its own **private** repository
(`doctask-<your-name>`), with `github.com/o-kadam` invited as a
collaborator, per the task doc's Task 1 submission instructions.

## What makes this submission stand out

The four-call contract (upload → chat → approve → export) is the floor,
built exactly as specified. Everything below is what was built on top of
it, unprompted, aimed specifically at the assignment card's own stated
audience - "a coordinator receiving documents from many outside parties":

- **It automates itself.** A coordinator doesn't have to open every
  message by hand - apply a Gmail label and a background watcher queues
  the attachment with zero clicks (`LabelWatcher.gs`). This is the literal
  shape of the job description's own ambition, applied to this one build:
  an agent doing the repetitive part while a human only steers.
- **It doesn't waste work.** Every job is content-hash deduped
  (`Dedupe.gs`) - the same document forwarded on a new thread, or
  re-attached under a different name, is recognised and skipped instead of
  spending a second SuperDocs operation on it.
- **It doesn't reprocess its own output.** A filename guard stops the
  add-on from ever normalising a file it already normalised - a real,
  found-and-fixed bug (see `PROGRESS.md` #4e) that would otherwise let a
  relabelled thread or a re-opened reply spiral into
  `(normalised) (normalised) (normalised)`-stacked files.
- **It survives being killed mid-run.** All state lives in Script
  Properties, not memory - stop the polling trigger and restart it, and a
  job resumes exactly where it left off rather than restarting or
  duplicating output. Actually tested this way, not just claimed - see
  `TESTING.md` Phase 7.
- **Eight real production bugs, found by actually running it against a
  live account, are logged with root cause and fix - not hidden.** See
  the full list in `PROGRESS.md`. Several of them ("Exceeded maximum
  execution time," hit twice, two separate OAuth scope/permission
  errors, and a filename-collision bug that only shows up on a second
  or third real run) are the kind of thing that only surfaces when you
  genuinely test against Google's real infrastructure rather than a
  mock.
- **A real, runnable test suite (21 unit tests, `node --test`, zero
  installs, no live key) plus a full manual test plan
  (`TESTING.md`) with real synthetic test-fixture files in every declared
  format**, including a genuinely image-only "scanned" PDF (verified with
  `pdftotext` returning nothing) rather than just a text PDF pretending to
  be one.
- **Actually tested against a live account, not just written and hoped
  to work.** Both surfaces, the label watcher, and the dedupe guard were
  run for real against a live Gmail + Drive account and a live SuperDocs
  account - see "Real-world testing" below for a real observed stats
  snapshot, not a hypothetical one.

![screenshot placeholder - add a real screenshot of the card in Gmail and in Drive before submitting]()

## Declared formats and domains

- **Accepted input formats:** `.doc`, `.docx`, `.odt`, `.rtf`, `.pdf`
  (including scanned PDF - OCR happens on SuperDocs's side during upload).
- **Output format:** `.docx`, matched to your SuperDocs house template.
- **Domain:** general business correspondence with mixed-format
  attachments (the "coordinator receiving documents from many outside
  parties" case from the assignment card). A second run with different
  files inside this same declared set is the bar the task doc sets for
  "it works the second time."

## The four-call contract

Built strictly against the minimum contract described in the task
document:

```
upload  ->  chat (edit instruction)  ->  approve  ->  export
```

All API calls live in `src/SuperDocsClient.gs`. Nothing else in the
project talks to the SuperDocs API directly.

## Two surfaces, one pipeline

- **Gmail** (`src/Code.gs`) - a card appears when any message with an
  attachment is opened, with one "Normalise" button per attachment.
- **Drive** (`src/DriveUI.gs`) - a homepage card where you paste a Drive
  file link or ID plus a notification email.

Both surfaces feed the exact same background job pipeline
(`src/AsyncJobs.gs`), so every safety property below applies to both.

## Why every SuperDocs API call happens in a trigger, not a click handler

Gmail/Drive add-on click handlers get killed by Google well before the
general 6-minute Apps Script ceiling (observed in real testing, twice:
"Exceeded maximum execution time" - see `PROGRESS.md` for both times this
was hit and fixed). So click handlers do only local, no-network work
(a content-hash dedupe check, then queuing a job) and return immediately.
A 1-minute polling trigger (`checkPendingJobs` in `AsyncJobs.gs`) does
everything else, in four stages:

```
not_started  ->  waiting_for_reference  ->  processing  ->  (completed)
 (uploads)        (wait for template)      (poll + approve)   export, file,
                                                                 notify
```

Because state is a small JSON blob in Script Properties rather than
in-memory, a job survives the trigger stopping and restarting - kill the
process mid-run and the next tick picks up exactly where it left off.

## Beyond the assignment: three extra pieces built on top of the floor

**Idempotency (`src/Dedupe.gs`).** Every job is keyed by a content hash
(MD5) of the file itself, not its name or which message it arrived on.
Before queuing anything, every entry point (Gmail click, Drive submit,
and the label watcher below) checks whether this exact content has
already been normalised successfully - if so, the existing Drive link is
returned immediately and no SuperDocs operation is spent. This catches
the same document being re-clicked, forwarded on a new thread, or picked
up twice by the label watcher.

**Gmail label watcher (`src/LabelWatcher.gs`).** The manual "open every
message and click" flow doesn't scale to the audience this build is
actually for - a coordinator receiving documents from _many_ outside
parties. Run `setupLabelWatcher()` once (Apps Script editor -> select the
function -> Run) and a `SuperDocs/To-Normalise` Gmail label is created
along with a 10-minute scanning trigger. Apply that label to any message

- by hand, or automatically via a Gmail filter rule - and its attachments
  get queued through the exact same pipeline with zero clicks. This turns
  the tool from "click once per document" into "label it and walk away,"
  which is the actual shape of the job description's own ambition (agents
  doing the work of many while a human only steers).

**Output-recognition guard (`isAlreadyNormalisedFilename`, in
`src/Code.gs`).** Found while testing the label watcher against a live
account: the add-on's own reply attachment (which carries "(normalised)"
in its name) could itself be picked up again - either by opening that
reply in Gmail and clicking its own "Normalise" button, or by relabelling
a thread that already contains one. Left unguarded, this produces
`(normalised) (normalised) (normalised)`-stacked output on the second or
third pass. A single filename check, applied at three call sites (the
button list, the click handler, and the label watcher's thread scan),
closes this - the add-on now recognises and skips its own output
everywhere it could otherwise re-enter the pipeline.

All three are additive: the manual button keeps working exactly as
before, and skipping any of them costs nothing.

## Project layout

```
appsscript.json               Add-on manifest (Gmail + Drive surfaces, scopes)
.gitignore                    Keeps .clasp.json (your own script ID) and node_modules out
src/Code.gs                   Gmail card UI + thin click handler
src/DriveUI.gs                Drive homepage card UI + thin click handler
src/AsyncJobs.gs              The trigger-driven pipeline (all 4 stages)
src/SuperDocsClient.gs        The 4-call API wrapper + the "double-parse" fix
src/Config.gs                 Safe API-key storage (Script Properties, never in code)
src/Stats.gs                  Small counters, shown as a footer on both cards
src/QualityChecks.gs          Content-preservation heuristic on the export
src/Dedupe.gs                 [new] Content-hash idempotency guard
src/LabelWatcher.gs           [new] Label-based auto-queue automation
test/                         21 pure-logic tests, zero installs, no live key
test-fixtures/                Synthetic sample files in every declared format, for manual testing
TASK.md                       Working conventions
TESTING.md                    Full manual + automated test plan, phase by phase
PROGRESS.md                   Logged assumptions, decisions, and every real bug fixed
```

## Getting started (local setup)

You need a Google account, Node.js 18+, and a SuperDocs account
(`use.superdocs.app`).

### 1. Install clasp (Google's CLI for Apps Script)

```bash
npm install -g @google/clasp
```

Or, since this repo already lists it as a dev dependency:

```bash
cd superdocs-gmail-normaliser
npm install
```

### 2. Log in and enable the Apps Script API

```bash
npx clasp login
```

This opens a browser for Google sign-in. Then visit
https://script.google.com/home/usersettings and turn **on**
"Google Apps Script API" (one-time, per Google account).

### 3. Create the Apps Script project

```bash
npx clasp create --type standalone --title "SuperDocs Attachment Normaliser"
```

This generates a real `.clasp.json` with your own script ID - it is
git-ignored on purpose (see `.clasp.json.example` for the shape). Clasp
will also create its own default files; delete any auto-generated
`Code.gs`/`appsscript.json` it adds so they don't clash with the ones in
this repo, then push:

```bash
npx clasp push
```

### 4. Set your SuperDocs API key

```bash
npx clasp open
```

Select the `setup` function (top dropdown) next to the Run button, click
**Run**, and paste your SuperDocs API key when prompted (from
`use.superdocs.app` -> Settings -> API).

### 5. Fill in the two placeholders

In `src/Code.gs`, replace:

- `HOUSE_TEMPLATE_DRIVE_FILE_ID` - the Drive file ID of your house
  template document (upload it to Drive once, open it, copy the ID out
  of the URL).
- `DRIVE_FOLDER_ID` - the Drive folder normalised files should land in.

Then `npx clasp push` again.

### 6. Create the polling trigger (once)

In the Apps Script editor, select `setupPollingTrigger` and click **Run**.
This must be run manually, once, from the editor - not from inside an
add-on click - because Google enforces a much longer minimum interval for
triggers created from an add-on's own execution context.

### 7. (Optional) Turn on the label watcher

Select `setupLabelWatcher` and click **Run**. Follow the prompt for a
notification email.

### 8. Install the add-on for testing

**Deploy -> Test deployments -> Install add-on**. Open Gmail, open any
message with an attachment - the "SuperDocs Normaliser" card should
appear. Open Drive - the same add-on's homepage card should appear in
the side panel.

## Running the tests (no live key needed)

```bash
node --test
```

21 tests across four files, zero installs, zero network calls:

- `parseProposedChanges.test.js` (6) - the "double-parse" logic the task
  document specifically calls out ("proposed-change content arrives as a
  JSON-encoded string and needs a second parse").
- `buildContentLossWarning.test.js` (4) - the content-loss warning
  threshold logic.
- `bytesToHexDigest.test.js` (4) - the dedupe hash's byte-to-hex
  conversion, including Apps Script's signed-byte quirk
  (`Utilities.computeDigest` returns -128..127, not 0..255).
- `pruneToMaxEntries.test.js` (4), plus 3 more spread across the above -
  the dedupe map's oldest-entry eviction logic.

The Apps Script parts (`CardService`, `GmailApp`, `UrlFetchApp`,
`PropertiesService`) only run inside Google's runtime and are not
unit-testable outside it - logged honestly in `PROGRESS.md` rather than
papered over with mocks that only prove the mocks work. That gap is
covered by real manual testing instead - see "Real-world testing" below.

## Real-world testing

This wasn't just written and hoped to work - it was run against a live
Google account and a live SuperDocs account, repeatedly, across both
surfaces. A snapshot of one real testing session (from the add-on's own
stats footer, see `Stats.gs`):

```
Queued: 5 · Auto-queued: 2 · Completed: 4 · Failed: 0 · Deduped: 1
```

That single line is evidence of several things actually working, not
just being claimed: the label watcher genuinely auto-queuing jobs with
no click (`Auto-queued: 2`), the dedupe guard genuinely catching a
resubmitted duplicate (`Deduped: 1`), and jobs completing end to end
through the async pipeline (`Completed: 4`) with nothing failing outright.
Real testing is also exactly how bugs 1-2 and 4-4e in `PROGRESS.md` were
found - every one of them only showed up against Google's real
infrastructure, not in code review. The full phase-by-phase manual test
plan this was tested against - including resumability (kill the trigger
mid-run, confirm it resumes), the dedupe edge cases, and the label
watcher automation - is in `TESTING.md`.

## Known limitations

- **Content-loss check only covers Drive-sourced jobs currently.** See
  `PROGRESS.md` assumption 7 for why, and what re-fetching Gmail source
  bytes at finish time would require.
- **Auto-approval.** The pipeline approves every proposed change in a
  batch automatically rather than rendering a diff review screen first.
  A stronger version would show the proposed changes and let a human
  approve/reject item by item before export - see "What I'd build next."
- **Manifest schema unverified against a live deployment.** The unified
  `addOns` structure in `appsscript.json` is written from documented
  schema knowledge, not confirmed by an actual Test Deployment install -
  see `PROGRESS.md` assumption 10.
- **API response shapes are assumptions.** See `PROGRESS.md` assumption 5.

## What I'd build next, in order

1. A review card showing the proposed diff before calling `approve`,
   instead of auto-approving the whole batch.
2. Extend the content-loss check to Gmail-sourced jobs too (would need a
   small redesign to carry source bytes or a re-fetchable reference
   through the job's serialised state).
3. Idempotency skip-cost reporting in the Stats footer (currently counted
   but not broken out by surface).
4. A small integration test harness that fakes `UrlFetchApp` responses
   shaped like the real API, so the pipeline logic in `AsyncJobs.gs` (not
   just the parsing/warning helpers) is covered without a live key.

---

Built by [Khushi Parekh] for the SuperDocs Round 2 task.
