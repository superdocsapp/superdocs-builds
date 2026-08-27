# The recovery rate — method first, then the number

**Measured 2026-08-26.** Raw data: [`corpus/measurements.json`](corpus/measurements.json),
written by `python3 -m docrepair.measure --write` and never by hand.
`tests/test_corpus.py` fails if that file and the code disagree.

Reproduce it in one command, with no key, no network and nothing installed:

```
python3 -m docrepair.measure
```

---

## The method

### What is measured

**87 fixtures: 5 base documents × 18 damage modes**, minus the modes that need a
picture on a document that has none. Each fixture is one document broken in
exactly one named way.

### The base documents, and why three of them are strangers

| Document | Written by | Words in the body |
|---|---|---|
| `synthetic-report` | this package | 25 |
| `synthetic-illustrated` | this package | 13 |
| `apple-textutil` | Apple `textutil` | 52 |
| `opf-lorem-ipsum` | the OPF `variations` converter | 660 |
| `gdocs-fully-featured` | Google Docs | 363 |

A repair tool measured only against its own output is measured against its own
assumptions. Three of these five were written by other software and vendored
under [`corpus/originals/`](corpus/originals/README.md) with their provenance and
licences.

### The three kinds of damage, and why they cannot share a denominator

A single "recovery rate" over mixed damage is a number about nothing: it moves
when you change the mix, not when the tool changes. So every damage mode is
declared as one of three kinds **before** the run, in `corpus.py`:

| Kind | What it means | What counts as correct |
|---|---|---|
| **lossless** | Every word is still in the bytes; only the container or the metadata is damaged | **Full recovery.** Anything less is this tool's defect and nobody else's |
| **lossy** | Bytes were physically removed | Full, partial, or an honest refusal. No rate here is a score out of 100 — the missing words are missing |
| **fatal** | The words are not in the file at all | A refusal. Or a partial, when the body was emptied and a picture or a header was still in the archive |

The bar for each kind is `measure.ACCEPTABLE`, written down before the run rather
than read off the results.

| | Damage | What happened to the file |
|---|---|---|
| lossless | `missing-content-types` | the part that tells Word what the other parts are is gone |
| lossless | `missing-rels` | the part that says where each picture belonged is gone |
| lossless | `bad-characters` | a bare ampersand and two control characters in the body |
| lossless | `mangled-xml-declaration` | the body declares an encoding that does not exist |
| lossless | `garbage-prefix` | an HTTP response header left in front of the file |
| lossless | `zeroed-eocd` | the archive's index signature destroyed, content untouched |
| lossless | `duplicate-entry` | a second, empty copy of the body under the same name |
| lossless | `bad-crc` | the stored checksum no longer matches the body's bytes |
| lossy | `truncated-90` / `-60` / `-30` | the download stopped at 90%, 60%, 30% |
| lossy | `unclosed-tags` | the body is cut off mid-element |
| lossy | `body-bitrot` | bit flips inside the compressed body |
| lossy | `media-truncated` | a picture's bytes cut in half |
| fatal | `missing-document-part` | the body part is gone entirely |
| fatal | `zero-length-body` | the body part is present and zero bytes long |
| fatal | `not-a-zip` | the file was never a Word document |
| fatal | `empty-body` | a valid, empty document |

### How a recovery is scored

**Word recall** — the share of the original's words present in the recovered
text, as multisets, so a word said four times and returned once scores a
quarter rather than full marks.

Ground truth is the intact original read by `corpus.text_of`: a regex over
`<w:t>` runs, standard library only, **no code shared with the repair path**.
The same function reads the rebuilt file, so both sides of every ratio are
measured the same way and neither side is measured by the thing under test.

### What is not measured

- **Formatting fidelity.** Every figure here is measured on the **local
  rebuild**, which is deliberately plain: theme, fonts and spacing are not
  recovered from a damaged file and are not guessed at. The file a person is
  actually handed has since been through the SuperDocs styling pass, which is
  where the formatting comes from. Nothing in this document measures that pass —
  it is a network call to a service whose output is not deterministic, so it is
  guarded (a styled file returning with fewer pictures or different words is
  refused) rather than scored. The local rebuild is what these numbers are
  about, and it is also the file a person gets when the pass cannot run.
- **Real-world damage.** Every fixture was damaged by `corpus.py` in a named way.
  See *What was looked for and not found* below.
- **Word's own verdict.** Outputs are reopened and reread by Python, not by
  Microsoft Word. Eight files are opened in Word by hand instead, and
  [`manual-test/MANUAL_QA_PLAN.html`](manual-test/MANUAL_QA_PLAN.html) records
  that separately.
- **Anything about a population.** 87 fixtures from 5 documents is a corpus, not
  a sample. There is no confidence interval here and none is implied.

---

## The result

```
kind         n   mean recall     min   verdicts
lossless    40         1.000   1.000   full=40
lossy       27         0.644   0.000   full=8 partial=12 refused=7
fatal       20         0.003   0.000   partial=4 refused=16

  damage that destroyed nothing, fully recovered   40/40
  fatal damage, correctly refused                  16/20  (the other 4 below)
  empty successes                                      0
  crashes                                              0
```

> **The lossy verdicts moved on 2026-08-26, and the tool did not get worse.**
> `full=14 partial=6` became `full=8 partial=12` because the harness learned to
> see picture and table loss. `_verdict` used to return *full* on any fixture
> with complete word recall, consulting pictures only to tell an empty success
> apart and never consulting tables at all — so a rebuild that dropped every
> photograph in the document still scored full marks. Six fixtures that were
> being called full were losing structure. They are the same six files; only the
> honesty of the label changed. BUG-093.

**On damage that destroys no content, every word came back: 40 out of 40, word
recall 1.000, minimum 1.000.** That is the number worth quoting, because it is
the one where a shortfall would be nobody's fault but this tool's.

**Nothing came back as an empty success, and nothing crashed.** Those two counts
are the ones that would matter most if they were not zero: a file that opens
with nothing in it is the failure this build exists to prevent, and a crash
tells its owner nothing at all.

### Per damage mode

| Kind | Damage | n | mean recall | Verdicts |
|---|---|---|---|---|
| lossless | missing-content-types | 5 | 1.000 | full 5 |
| lossless | missing-rels | 5 | 1.000 | full 5 |
| lossless | bad-characters | 5 | 1.000 | full 5 |
| lossless | mangled-xml-declaration | 5 | 1.000 | full 5 |
| lossless | garbage-prefix | 5 | 1.000 | full 5 |
| lossless | zeroed-eocd | 5 | 1.000 | full 5 |
| lossless | duplicate-entry | 5 | 1.000 | full 5 |
| lossless | bad-crc | 5 | 1.000 | full 5 |
| lossy | truncated-90 | 5 | 1.000 | full 4, partial 1 |
| lossy | truncated-60 | 5 | 1.000 | full 3, partial 2 |
| lossy | truncated-30 | 5 | 0.400 | full 1, partial 1, refused 3 |
| lossy | unclosed-tags | 5 | 0.651 | partial 5 |
| lossy | body-bitrot | 5 | 0.028 | partial 1, refused 4 |
| lossy | media-truncated | 2 | 1.000 | partial 2 |
| fatal | missing-document-part | 5 | 0.000 | refused 5 |
| fatal | not-a-zip | 5 | 0.000 | refused 5 |
| fatal | zero-length-body | 5 | 0.007 | partial 2, refused 3 |
| fatal | empty-body | 5 | 0.007 | partial 2, refused 3 |

### `media-truncated`: full recall, and still not a full recovery

Every word comes back — the damage is to a picture, not to the body — and the
mode scored **full** until 2026-08-26. It was wrong twice over. The half-read
picture was written into the rebuild, where Word draws a grey placeholder, and
`counts_of` counted it as recovered because a member with that name existed in
the archive. A picture is now counted only if its bytes decode and run to the
format's own end marker, and one that does not is refused and reported rather
than embedded. The mode scores **partial**, which is what it always was.

### The four fatal fixtures that were not refused

`synthetic-illustrated` and `gdocs-fully-featured`, on `zero-length-body` and
`empty-body`. In each the body carried nothing and the archive still held a
photograph, a header or a footnote — so the file that comes back has those in it
and none of the body's words. That is recovery, not invention, and the report
says which parts it is handing over. It is listed here rather than folded into
the refusals because a reader deciding whether to trust this tool should see it.

### What a truncation costs depends on where the body sits, not on the percentage

The most useful thing the corpus found. Cut to 30%:

| Document | Words | Verdict |
|---|---|---|
| `opf-lorem-ipsum` | 660 | **full** — every word |
| `gdocs-fully-featured` | 363 | **full** — every word |
| `synthetic-report` | 25 | refused |
| `synthetic-illustrated` | 13 | refused |
| `apple-textutil` | 52 | refused |

The two large real documents survive losing 70% of the file, because
`word/document.xml` is written early in the archive and the tail that gets cut
is styles, theme and fonts. The three small ones lose everything, because in a
4 KB document the body is proportionally later and the cut lands in the middle
of it. **"70% of the file survived" says nothing about how much of the document
survived**, and any tool quoting a percentage-of-bytes recovered is quoting the
wrong number.

---

## Four defects the corpus found, all fixed

None of these were visible to the 63 tests that existed at the time. Each is in
`BUGS.md` with its repro.

- **BUG-065 — a bit-rotted file crashed the repair.** `zipfile.testzip()` raises
  `zlib.error`, which is not an `OSError`, so it went straight through
  `salvage_members` and out of `repair()`. On the page that is a 500 with no
  explanation. Now caught, and the damaged member is re-read by the
  local-header path, which keeps whatever inflated before the damage instead of
  discarding it.
- **BUG-066 — raw XML was pasted into recovered documents.** The last-resort
  text extractor matched `<w:t[^>]*>`, which also matches `<w:tbl>`, `<w:tr>`
  and `<w:tc>` — so on any document with a table it captured the table's markup
  as if the owner had typed it. It was visible in a committed interface fixture:
  `<p>&lt;w:tblPr&gt;&lt;w:tblStyle w:val="TableGrid"/&gt;…Region</p>`. Ten
  tests and a rendered page had been passing over it.
- **BUG-067 — a duplicate entry could hide the real body.** When a name appears
  twice, `ZipFile.read(name)` answers with whichever copy the index lists last.
  The copy with content is now preferred.
- **BUG-068 — a bad XML declaration cost the whole structure.** One unparseable
  declaration sent a perfectly readable document down the run-by-run path,
  losing every heading and table. The declaration is now normalised.

And two in the measurement itself, both found by disagreeing with the product
and both this session's own work:

- The ground-truth extractor had **BUG-066's exact bug**, which made the Google
  Docs file look 84% unrecovered when nothing was wrong.
- It joined runs with a space, so `adi` + `piscing` became two words and the
  rebuild was blamed for losing them. Word splits a word across runs whenever
  the formatting changes mid-word; runs inside a paragraph join with nothing
  between them.

Both are in `tests/test_corpus.py` as tests, because a yardstick that can be
wrong quietly is worse than no yardstick.

---

## What was looked for and not found

A corpus of **genuinely** corrupt DOCX files was searched for first. There does
not appear to be a public one, and the reason is structural: a recovery *rate*
needs to know what the document said before it broke, and a corrupt file found
in the wild does not come with that. What exists nearby, and why each was not
used:

| Source | What it is | Why not |
|---|---|---|
| [Digital Corpora / govdocs1](https://digitalcorpora.org/corpora/file-corpora/files/) | ~1M real files from `.gov` domains, in 1,000-file subsets | Real but **intact**, and 2009-era, so mostly `.doc`. No ground truth for anything damaged |
| [openpreserve/format-corpus](https://github.com/openpreserve/format-corpus) | CC0 preservation test corpus | Its damaged-file sets are **PDF** — `pdfCabinetOfHorrors`, `govdocs1-error-pdfs`, `jhove-errors`. It holds exactly two `.docx`, both healthy. **Both are used here as base documents** |
| [docx-corpus](https://docxcorp.us/) | 736K classified `.docx` from Common Crawl | Real, large, and intact — a source of base documents, not of damage |
| msx-13 (Roussev & Quates) | 22,000 crawled MS Office files | Intact, and assembled for forensic triage rather than repair |
| [poi-fuzz](https://github.com/centic9/poi-fuzz) / OSS-Fuzz seeds | Malformed OOXML used to fuzz Apache POI | The closest thing to a damaged-DOCX corpus, and it exists to make parsers **crash**, not to be recovered. No originals, so no rate is computable |

So the damage is generated here, from documents that are real. The honest
consequence is stated plainly: **every fixture was broken by code that knows how
it broke them**, which is the one thing a wild corpus would fix and this one
cannot. `corpus.py`'s damage modes are written to match what actually happens to
files — a cut download, a mail-client prefix, bit rot, a duplicated entry from a
bad merge, a hand-edited body — rather than to be easy to recover.

Anyone holding real broken documents can point this at them: the fixtures are
generated, so replacing them is a matter of supplying files and their originals.
Without originals, the harness can still report whether each file opened, what
came out and what was claimed — but not a rate, and it will not pretend
otherwise.
