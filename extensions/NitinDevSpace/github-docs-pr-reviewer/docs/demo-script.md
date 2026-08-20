# Demo Script

The target flow for the recording. Steps marked *not built yet* are still ahead
of the current sprint and must not be claimed in the video until they work.

## 1. The problem, in one shot

Show a docs PR in the test repo that changes `docs/getting-started.md` with a
skipped heading level, an image with no alt text, a `TBD` placeholder, and a
sentence using "utilize".

## 2. The review

Show the app's PR review: one summary comment plus a small number of inline
comments. Call out that findings are capped so maintainers do not mute the app,
and that the summary reports how many findings were suppressed.

## 3. The preview

Open the generated preview artifact and show that it is built from the same HTML
the eventual export uses.

## 4. Applying a fix

Comment `/superdocs apply <finding-id>` using an ID copied from an inline comment.
Show the app's reply naming the commit and the exact lines it changed, then show
the commit on the PR branch.

Then show the honest edges, because they are the point:

- Comment the same command again and show the app reporting it is already applied
  rather than committing twice.
- Comment `/superdocs apply <id>` for the `TBD` placeholder and show the app
  refusing to invent the missing content.

## 5. The release document

Publish a release with notes. Show the generated release document attached to the
release, and open it to show the notes plus the list of documentation files that
changed since the previous release.

## Recording rules

- No credentials, tokens, or `.env` contents on screen.
- Claim only what the recording shows.
- If a step fails while recording, keep the failure in and explain it.
