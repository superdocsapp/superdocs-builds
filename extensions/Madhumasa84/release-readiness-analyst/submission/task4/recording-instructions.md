# Recording and copy instructions

These are instructions for a future human recording. No recording, upload, publication, or submission was performed while preparing this package.

## Prepare a safe local recording

1. Use only the checked-in synthetic fixtures and deterministic offline fixture server. Do not use a real API key or private document.
2. Run `sdx` with an isolated temporary `HOME` and a credential-free fixture configuration. Do not print environment variables, profiles, credentials, signed URLs, or full machine paths.
3. Start the analyst’s offline backend and frontend. Use a fixture run identifier such as `run_demo_01`; replace any generated IDs in the overlay with neutral labels.
4. Set 1920×1080, 30 fps, a readable terminal/browser font, and a clean microphone. Hide browser bookmarks, notifications, shell history, and unrelated windows.
5. Record the sequence in `shot-list.md`. Keep the master between 2:30 and 3:30 and never above the hard 5:00 maximum.
6. Show the final limitations card. It must say that the run is offline, current-audit live operations are zero, no live cassette was recorded, rendered 120-page counting was unavailable, and PDF clause verification is pending.
7. Export a review master as H.264 video with AAC audio. Keep the master locally until the user approves the copies. Optionally calculate a checksum, but do not put local paths in the video or description.

## YouTube copy (only after approval)

- Sign in through the user’s normal browser; never put a credential in a script or terminal.
- Upload the approved master as **Private** or **Unlisted** according to the user’s instruction. Do not choose Public by default.
- Use a neutral title such as “Release Readiness Analyst — Task 4 draft demo”. Mention that the data is synthetic and the demo is offline. Do not include job IDs, API endpoints, signed URLs, or local paths.
- Verify the full duration, audio, captions if supplied, and access setting in a second browser/profile. Record the resulting link only in the user’s private submission notes.
- Do not send the link, submit a form, or contact a buyer from this workflow.

## Google Drive copy (only after approval)

- Upload the same approved master to a user-selected restricted folder. Do not enable “anyone with the link”.
- Verify that the file opens, plays from start to finish, and inherits the intended folder permissions. Check that no thumbnail or description exposes private content.
- Keep the Drive URL out of source files and public repository history. Share it only through the user-approved submission channel.

## Stop conditions

Stop and ask for review if the PDF is still unavailable, a frame exposes a secret/signed URL/private document, the final file exceeds five minutes, a renderer or shell check is unavailable, or a copy requires public publication. This package does not authorize any of those external actions.
