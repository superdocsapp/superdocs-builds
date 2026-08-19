# Comment replies are lost on an upload and export round trip

Measured 9 Aug 2026. Reproducible with `scripts/roundtrip_check.py` against a
fixture built by `src/thread_resolver/samples/builder.py`, so no private
document is involved.

## What I did

Uploaded a `.docx` containing five comment threads via
`POST /v1/documents/upload-base64`, made no edits, and exported it straight back
via `POST /v1/documents/export` with `format: docx`.

## What I expected

An unedited round trip returns the comments as they went in. The documentation
says comments export as "real Word comments", and that out-of-flow parts
"survive edits, revert, multi-document sessions, and the round-trip to `.docx`
and PDF".

## What happened

| | before | after |
|---|---|---|
| comments | 6 | **5** |
| threads | 5 | 5 |
| replies | 1 | **0** |
| resolved threads | 1 | **0** |
| `word/commentsExtended.xml` | present | **removed** |

Three separate losses:

1. **A reply was deleted.** "No, leave it. Finance signed off on monthly." is
   absent from the exported file. No error, no warning; the export reports
   success.
2. **Thread structure is gone.** `word/commentsExtended.xml` carries
   `w15:paraIdParent`, which records who replies to whom, and is not written at
   all. Surviving comments come back as a flat list.
3. **Resolved state is lost.** `w15:done` lives in that same part, so a thread
   closed before the round trip comes back open.

Top-level comments survive intact, so the documented promise holds for those.

## What it changed

This build walks comment threads, so it cannot use the exported file as its
output: doing so would silently discard replies and reopen resolved threads the
run never touched. Approved edits are written back into the original `.docx`
instead, which leaves every untouched byte untouched.

The one comment lost was a dissenting reply. For a tool whose whole purpose is
surfacing disagreement, that is the most expensive comment in the file to lose.
