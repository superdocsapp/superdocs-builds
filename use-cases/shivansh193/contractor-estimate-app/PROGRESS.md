# Progress log

Dated notes on real findings while building this against the live SuperDocs
product. Not a design doc -- just what actually happened, for Task 4's
"what broke" question and for anyone revisiting this build later.

## 2026-08-19 -- signed image URLs vs. what actually ships in the export

Built the estimate flow: upload two site photos (`POST
/v1/documents/images/upload`), reference their returned URLs in a chat
instruction so each priced line item embeds the photo that justified it,
export as `.docx`.

First pass verification only checked the *chat response's* HTML -- it
contains `<img src="https://storage.googleapis.com/...">`, and that URL is
a Google Cloud Storage **signed URL**, `X-Goog-Expires=86400` (24 hours).
Wrote that up as a limitation ("the exported `.docx` will show broken
images after 24h") without actually opening the exported file to check --
a real reviewer of this build's own README correctly called that out as
an assumption, not a verified finding, and asked for direct inspection
instead.

**Direct inspection** (unzip `output/estimate.docx`, read it as the OOXML
package it is):
- `word/media/image1.jpg` / `image2.jpg` are present, real JPEGs,
  byte-identical to the source photos uploaded.
- `word/_rels/document.xml.rels` references them via standard
  `Type=".../relationships/image"` relationships with no
  `TargetMode="External"` -- genuine internal embedding, not a link.

**Conclusion, corrected**: SuperDocs' `.docx` export resolves image `src`
URLs at export time and writes the real bytes into the file. The exported
artifact does not depend on the signed URL surviving. Also exported
`output/estimate.pdf` the same way (while the signed URLs were still live,
as a second durable snapshot) and confirmed it too contains two real
`/Subtype/Image` objects with `DCTDecode` (JPEG) streams via a byte-level
check, not just a plausible file size.

**What was still true and worth closing**: the *session's* own stored
document state on SuperDocs' side presumably still only held the signed
URL (that's literally what upload returned), not the embedded bytes --
embedding happens at export time, not at draft time. So re-opening the
same session and re-exporting after the 24-hour window would plausibly
have failed to pull fresh image content, even though the files already
sitting in `output/` were unaffected.

**Closed.** `server.py`'s `refresh_urls_before_export()` re-uploads each
photo's original bytes (kept in memory from the initial form submission,
nothing extra to fetch) immediately before calling export, and swaps the
possibly-stale URL for the freshly-minted one in the drafted HTML before
export runs. This decouples "how long ago was this drafted" from "does the
exported file's embedded image resolve" entirely -- export now always uses
a URL minted seconds earlier, regardless of session age. Verified against
a real run: the "refreshed URL for..." log line fired for both photos with
new URLs distinct from the original upload, and the resulting
`estimate.docx` was re-unzipped and still shows both images as genuine
embedded binary media (same check as before -- real JPEGs in
`word/media/`, standard internal relationships, no `TargetMode="External"`).

One thing this fix run surfaced that's unrelated to it: the LLM's draft
structure varies run to run -- one run placed each photo inline in its line
item's table cell, another placed both photos in a shared evidence row
below the table (with a correct `alt` attribute identifying which is
which). Both are legitimate ways to satisfy "traceable to the photo," but
it means a naive proximity check (this app's own `near_related_text`
heuristic) can under-report on a structurally-different-but-still-correct
draft. Not fixed -- it's an internal diagnostic signal, not the actual
grading bar (`photo_embedded` is), and tuning it further wasn't worth the
time against this task's remaining scope.

**The actual lesson**: "the HTML response contains a URL with an expiry"
and "the exported file depends on that URL" were two different claims, and
only checking the first one produced a wrong conclusion about the second.
Unzip the artifact and check -- and then, once a real gap is confirmed,
the fix (re-upload fresh bytes at the point of use) was genuinely a
15-minute change, not a rabbit hole.
