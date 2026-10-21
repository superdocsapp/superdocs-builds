# Contractor Estimate & Quote App

Built by Shivansh Kalra for the SuperDocs task.

A small web app for "Bright Line Electric" (a fictional residential
electrical contractor): enter site-visit notes plus one photo per issue
found on the walkthrough, and it generates a branded, itemized estimate
against the real, hosted SuperDocs product where each priced line item
genuinely displays the photo that justified it -- not described near it,
literally embedded in the same table cell as that line item.

Unlike the Construction Contract Pack build, this card benefits from an
actual interface (site-visit data entry naturally wants a form, not a
script argument), so this ships as a small FastAPI backend plus a plain
HTML/JS form -- no build tooling, scoped to what an S2 card needs.

All content is synthetic: a fictional contractor, fictional client, and
two illustrative placeholder photos generated for this task (clearly
labeled as such, not claimed to be real photographs -- see
`content/site_photo_*.jpg`).

## What it does

1. You fill in job notes (address, client, overview) and, for each of two
   issues found on-site, a short caption plus the photo that shows it.
2. Each photo is uploaded to SuperDocs directly (`/v1/documents/images/upload`)
   and gets back a real, stable URL.
3. A branded template (`content/estimate_template.html` -- the Bright Line
   Electric letterhead style) is uploaded once via `/v1/templates/upload`.
4. A chat instruction asks SuperDocs to draft the estimate: one priced line
   item per captioned issue, with that issue's real uploaded photo URL
   embedded directly under its description -- the mapping from photo to
   line item is explicit in the instruction (this app knows which photo
   goes with which issue because the person filling out the form said so),
   not left to an AI vision guess.
5. The draft is approved and exported as `.docx`.
6. The result is verified programmatically: for each issue, does the
   output actually contain an `<img>` tag with that issue's real photo URL,
   positioned near that issue's caption text? Not asserted -- checked
   against the real returned HTML.

## How to run it

```bash
python -m venv .venv
.venv/Scripts/activate    # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env      # then set SUPERDOCS_API_KEY
uvicorn server:app --reload --port 8020
```

Open `http://127.0.0.1:8020`, fill in the form (two sample photos are in
`content/` if you want to reuse them), and submit. A run costs a small
number of operations (two image uploads, one template upload, one chat
edit); exports don't cost operations. The first request in a fresh
session can be slow or fail while things warm up -- normal, not a bug.

## SuperDocs features used

- **Image upload** (`POST /v1/documents/images/upload`) -- real,
  stable URLs for each site photo, used inline in the generated document
- **Templates** (`POST /v1/templates/upload`) -- the branded letterhead
  style SuperDocs draws on when generating the estimate
- **Chat / async edit** (`POST /v1/chat/async`) with `approval_mode:
  "ask_every_time"` -- genuinely exercised here (this build drafts a
  single document with no `document_id` targeting, so it doesn't hit the
  approval-gate bug found while building the Construction Contract Pack)
- **Export** (`POST /v1/documents/export`, `.docx`)

## Verified result

Both captioned issues passed on the first real run against the live API
(strong bar only requires one):

```
PASS: "Corroded panel, double-tapped breakers..." -- photo embedded in the output
PASS: "Knob-and-tube wiring exposed in wall cavity..." -- photo embedded in the output
```

Real drafted numbers from that run: Issue 1 ($600 labor + $450 material =
$1,050), Issue 2 ($1,200 labor + $750 material = $1,950), correct total
$3,000.00.

## A real SuperDocs platform behavior worth noting

SuperDocs' image upload returns a Google Cloud Storage **signed URL**, valid
24 hours (`X-Goog-Expires=86400`), not a permanent link. That looked like a
real durability risk for the exported estimate at first -- an `<img src>`
pointing at a link that expires the next day would make "traceable" true
only until the URL dies. It was flagged as a limitation in an earlier draft
of this README without actually checking the exported file, which turned
out to be the wrong way to confirm it.

Checked directly instead: unzipped `output/estimate.docx` and inspected it
as the OOXML package it is. `word/media/image1.jpg` and `image2.jpg` are
present as real JPEGs, byte-identical to the original uploaded photos, and
`word/_rels/document.xml.rels` references them as standard internal
relationships (`Type=".../relationships/image"`, `Target="media/image1.jpg"`)
with no `TargetMode="External"`. That's genuine embedding -- SuperDocs'
`.docx` export fetches the image content at export time and writes the
actual bytes into the file, rather than carrying the signed URL forward.
Confirmed the same for `output/estimate.pdf` (exported separately, while
the signed URLs were still live, specifically to have a second durable
snapshot): the PDF contains two real `/Subtype/Image` objects with
`DCTDecode` (JPEG) streams, not a broken-link icon.

So: **the exported `.docx` and `.pdf` are durable and don't depend on the
signed URL surviving.** One real gap remained, though: the *session's*
document state on SuperDocs' side presumably still only held the signed
URL, since that's what upload returned -- so re-opening the same session
and re-exporting after the 24-hour window would plausibly have failed to
pull fresh image bytes.

**Closed.** `server.py` now re-uploads each photo's original bytes (still
held in memory from the form submission) fresh, immediately before calling
export, and swaps the possibly-stale URL for the new one in the drafted
HTML before export runs -- see `refresh_urls_before_export()`. Export no
longer depends on how long ago the photo was first uploaded. Re-verified
end to end: fresh URLs distinct from the original upload, `estimate.docx`
re-unzipped and still shows both images as genuine embedded binary media.

## Honest limitations

- **Screenshot**: not included. Screenshot capture wasn't working in the
  session this was built in (a tooling limitation on my end, not the
  app's). The app is real and runs -- `uvicorn server:app --reload` and
  open the URL above to see it live; a screenshot is a 10-second addition
  once you have a display to take it from.
- **File-picker automation**: this run submitted the exact same
  `POST /api/estimate` multipart request the browser's own JS sends (same
  code path, real photos, real response), rather than literally clicking
  through the file inputs -- the automation environment used to build this
  had no native file-dialog control. The form itself was confirmed
  rendering correctly (all fields, correct structure) before this.

## Files

- `server.py` -- FastAPI backend: the upload -> template -> chat -> approve
  -> export -> verify flow
- `static/index.html` -- the form and result display
- `content/estimate_template.html` -- the branded letterhead template
- `content/site_photo_*.jpg` -- illustrative placeholder site photos
- `output/` -- exported `.docx` and `.pdf` (gitignored; run the app to
  regenerate), both confirmed to genuinely embed the site photos as real
  binary image data, not links to the signed URLs
