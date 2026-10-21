# Bugs and rough edges found while building on SuperDocs

Each entry follows the shape the task asks for: what I did, what I expected, what happened instead, how badly it blocked me, and how to reproduce it.

Everything below was found against `api.superdocs.app` in August 2026 using a free agent account. The reproductions are runnable with any `sk_` key and cost **zero operations** — exports and image uploads are not billable, which is itself a very good property and worth keeping.

---

## 1. Data-URI images are dropped from exports with no warning

**Severity: high.** Silent data loss.

**What I did.** Exported HTML containing `<figure><img src="data:image/png;base64,…"></figure>` to `.docx`.

**What I expected.** Either the image embedded, or — since the API has a documented `image_download_failed` warning channel — a warning telling me it had not been.

**What happened.** HTTP 200. A well-formed `.docx` with the figure caption present, the image absent, `word/media/` empty, and `X-Export-Warnings` **not set at all**.

**How badly it blocked me.** Badly, and quietly, which is worse. A book with seven plates exported "successfully" with zero plates in it, and nothing in the response said so. I only caught it because I was byte-inspecting the `.docx` rather than trusting the 200. Anyone who trusts the status code ships a book with holes in it.

**Fix in my code.** Every figure is uploaded via `POST /v1/documents/images/upload-base64` first, and the returned URL is substituted into the `src`. Content-addressed by sha256 so recompiles do not re-upload.

**Suggested fix.** Emit `image_download_failed` (or a new `data_uri_unsupported`) for any `src` that does not survive to the output. A dropped image should never be silent.

```python
# repro — the exported .docx contains the caption and no image, warnings header absent
html = '<figure><img src="data:image/png;base64,iVBORw0KGgo..."><figcaption>Plate 1.</figcaption></figure>'
r = requests.post("https://api.superdocs.app/v1/documents/export",
                  headers=H, json={"html": html, "format": "docx"})
print(r.headers.get("X-Export-Warnings"))   # None
zipfile.ZipFile(io.BytesIO(r.content)).namelist()  # no word/media/*
```

---

## 2. Three load-bearing HTML conventions are undocumented

**Severity: medium.** Cost me most of a working session and three operations to discover.

The exporter honours specific HTML markers that appear nowhere in the docs. I found each by asking the chat API to perform the action and then reading the HTML it produced:

| Feature | The markup that works | Where it is documented |
|---|---|---|
| Page break | `<hr data-page-break="true">` | nowhere |
| Footnote reference | `<sup data-footnote-ref="fn-1" role="doc-noteref">1</sup>` | nowhere |
| Footnote body | `<aside data-part-type="footnote" data-part-id="fn-1" role="doc-footnote">…</aside>` | `data-part-type` is mentioned in the editor-integration guide as something to *preserve*, never as something you may *author* |
| Auto table of contents | `<div class="table-of-contents" data-toc=""></div>` | nowhere |

**The trap underneath this.** The obvious thing to reach for is CSS, and **every CSS page-break form is silently ignored**. I tested ten variants — `page-break-before`, `page-break-after`, on `div`, `p`, `br`, `hr`, `span`, plus the classic `mso-special-character` incantation — and all ten produced a `.docx` with exactly zero `w:type="page"` breaks and no warning.

This matters more than it looks. These conventions are the difference between "a document" and "a print-ready book", and they are free — the compiler emits them itself, spending nothing, where the alternative is an AI operation per book to insert page breaks.

**Suggested fix.** A short "Authoring HTML for export" page listing the markers the exporter recognises. It would have saved a day and three operations, and it makes the product look considerably more capable than the docs currently do.

---

## 3. AI-inserted footnote bodies carry their own number, which doubles in Word

**Severity: low.** Cosmetic, but it lands in the final artefact.

**What I did.** `POST /v1/chat` — *"Add a real Word footnote to the sentence 'The map was wrong.' The footnote text should read: 'Survey of 1913, sheet 4.'"*

**What I expected.** A footnote body containing `Survey of 1913, sheet 4.`

**What happened.** The body came back as `<p>1. Survey of 1913, sheet 4.</p>`. Word numbers footnotes itself from the reference, so the printed note reads **"1 1. Survey of 1913, sheet 4."**

**Suggested fix.** Do not emit a manual number in a footnote body; the numbering belongs to the renderer. My compiler omits it, and a test asserts that no footnote body it produces starts with `N. `.

---

## 4. The `data-toc` block concatenates sibling headings

**Severity: low-medium.** Produces visibly wrong output.

**What I did.** Exported a document containing `<div class="table-of-contents" data-toc="">` above `<h1>Chapter One</h1><h2>A Section</h2><h1>Chapter Two</h1>`.

**What I expected.** Three entries, indented by level.

**What happened.** The `.docx` text runs are:

```
'Contents', 'Table of Contents', 'Contents', 'Chapter OneA Section', 'Chapter Two'
```

Two problems. `Chapter One` and `A Section` are concatenated with no separator into a single entry `"Chapter OneA Section"`, and the block also picks up the `<h1>Contents</h1>` heading of the contents page itself.

There are also no page numbers and no Word TOC field, so the result is a static list rather than something that updates. Reasonable as a limitation — but it is not stated anywhere, and a user asking for "a table of contents" in a 300-page book will reasonably expect page numbers.

**Fix in my code.** I build the table of contents myself from the heading tree, with anchors and hyperlinks (both of which survive to `.docx` and PDF, verified), and document the absence of page numbers as a limitation rather than shipping the concatenated one.

---

## 5. Footnotes render as page-foot notes in DOCX and as collected endnotes in PDF

**Severity: low.** Surprising rather than broken.

The same `<sup data-footnote-ref>` + `<aside data-part-type="footnote">` markup, exported twice from identical HTML:

- **`.docx`** — real Word footnotes. `word/footnotes.xml` present, `footnoteReference` elements in the body, notes at the foot of the page they belong to. Exactly right.
- **`.pdf`** — the markers stay as superscript links, and every note body is collected into a list at the very end of the document with `↩` back-links.

Both are defensible renderings. They should agree, or the difference should be documented, because "print-ready PDF" and "editor's DOCX" are usually expected to be the same book.

---

## 6. `/v1/users/me` returns 401 for a valid API key

**Severity: low — and the docs already warn about it, which is exactly right.**

Worth restating because it is the first thing anyone tries: the natural way to check a key is `GET /v1/users/me`, and it returns `401` for a perfectly good `sk_` key because that endpoint is web-app-only. The docs call this out explicitly and recommend `GET /v1/sessions` instead. That warning saved me an hour, and I mention it here only as a vote for keeping it prominent — or, better, for making `/v1/users/me` return a `403` with an explanatory body so the failure is self-describing.

---

## What worked notably well

Balance, since the above is a list of complaints:

- **The agent signup flow is genuinely excellent.** One `POST`, a working key, a quota, and copy-paste MCP configuration in the response. Under a minute from nothing to a first call.
- **Exports and image uploads cost zero operations.** This is a very good decision. It meant I could iterate on typesetting dozens of times, byte-inspecting every `.docx`, without touching the budget. All the operations I spent — three — went on learning undocumented behaviour.
- **The `usage` block on every chat response** made it trivial to build an accurate spend counter into the plugin's status bar.
- **The docs are unusually honest about their own traps.** The warnings about the second JSON parse, the `awaiting_kind` branch, and the required top-level `approved` field each describe a bug I would otherwise have shipped. That is rare and it shows.
