# Insurance loss-run summary app

Turns years of raw loss-run data across multiple policies and carriers into one
review document an underwriter can act on: claim counts, incurred totals, and
open claims grouped by policy year — with every figure traced to the document
and row it came from.

Built on SuperDocs (upload, search, chat, approve, export) for the SuperDocs
task. Assigned build, band S2, surfaces: search and export.

> Built by Siddharth Muneshwar for the SuperDocs task.

## What SuperDocs features it uses

| feature | how |
|---|---|
| **Upload** | the adjuster notes, application and broker correspondence are attached to the session; free, and what makes cross-document retrieval possible |
| **Chat editing** | one turn does two jobs: fills a placeholder section from the attached documents, and writes the opening narrative |
| **Approve** | the proposed changes are approved before anything is written |
| **Export** | the review document comes back as DOCX |

A full review costs **one operation**. Figures never pass through the model:
they are parsed from the loss runs and the instruction forbids changing them.

## Run it

```
pip install -r requirements.txt
python -m pytest tests/ -q
python -m lossrun.review --corpus corpus/out --out out --mode dry --max-ops 6 --as-of 2026-01-09
```

25 tests, no API key, no network, no operations; then the full pipeline
offline.

The generated corpus ships in `corpus/out/`, so there is nothing to build first.
Regenerating it (`cd corpus && python generate.py`) needs LibreOffice on the
path for the PDF loss run; nothing else does.

Against the live API:

```
export SUPERDOCS_API_KEY=...
python -m lossrun.review --corpus corpus/out --out out --mode live --max-ops 6 --as-of 2026-01-09
```

Four operations, capped at six. On PowerShell the first line is
`$env:SUPERDOCS_API_KEY = '...'`.

A `Makefile` wraps these as `make install`, `make test`, `make dry` and
`make live` where `make` is available. It is a convenience, not a dependency —
every command above runs as written on Windows, macOS and Linux.

The key is read from the environment only — never an argument, never logged,
never written to an output file, and a test asserts no key-shaped string reaches
any output.

## The one design decision everything follows from

**Figures are parsed. They are never searched for, inferred, or model-generated.**

Claim counts, incurred totals and loss ratios are arithmetic over rows read out
of the loss runs. An underwriter cannot act on a total that might be a plausible
guess, and a summary whose numbers need re-checking has saved nobody any work.

Search and chat are spent where they earn their cost:

| work | how | operations |
|---|---|---|
| claim figures, counts, totals, ratios | parsed from CSV/PDF rows | 0 |
| contradictions living in prose, and the narrative | one edit | **1** |
| upload, attach, approve, export | free per published pricing | 0 |

**A full review costs one operation.**

**On the search surface, and two wrong turns getting here.** A dedicated
`/v1/search` endpoint returned `HTTP 404` live, so retrieval moved to the chat
surface: the prose documents are attached to the session by `upload`, which is
free. The first attempt asked for a JSON chat reply and looked for it in the
proposed-changes payload — which carries document edits, not chat text, so the
answer was never there to find. That was fighting the product. SuperDocs is an
editing agent: the answer belongs *in the document*. The review is now written
with a placeholder section, and one edit both fills it from the attached
documents and adds the opening narrative. Supported path, and half the cost of
the version that was wrong.

`SuperDocsClient.search` and `.retrieve` are kept, unused, for the day a search
endpoint or a chat-reply field is exposed. `search` raises `SearchUnavailable`
on 404 rather than pretending an empty search succeeded.

The chat instruction says explicitly that every number in the document is
already correct and must not be changed, recalculated, rounded or restated.
There is a test asserting that instruction still says so.

A naive design that searched once per claim would have spent 41 operations on
one account and still produced figures nobody could audit.

## What makes loss runs hard

A loss run is a carrier's claims history for one policy year. They get
**reissued**, and reserves develop between issues. The same claim carries
$45,000 on the run valued January 2024 and $182,400 on the reissue valued
January 2026. Neither document is wrong.

This is not a detail. On the sample account:

| source for policy year 2023 | incurred | loss ratio | referral rule |
|---|---|---|---|
| original run, valued 2024-01 | $286,092.44 | **57.1%** | passes |
| reissue, valued 2026-01 | $647,992.44 | **129.3%** | **refer** |

The same account either clears the 60% referral threshold or blows through it
twice over, depending on which document is trusted. So the app takes the later
valuation as authoritative **and records the difference as a conflict** rather
than overwriting quietly. A conflict is never delivered pre-resolved; there is a
test for that.

## What it produces

`out/review.html` — and see the known defect below regarding the DOCX export:

- **Summary by policy year** — claims, open count, paid, reserve, incurred, loss
  ratio, and which document each year's figures came from
- **Open claims**, listed separately with months open, because reserves on open
  claims may still develop
- **Conflicts between sources**, surfaced with both figures and the consequence
- **Checklist findings** against eight underwriting rules
- **What this review does not establish** — named, not smoothed over
- **Sources**, including which documents were read and superseded

`out/summary.json` carries the same content for anything downstream.

## The rules

R1 severity claims need an adjuster note · R2 open more than 36 months ·
R3 loss ratio above 60% · R4 date of loss outside its policy period ·
R5 application consistent with the loss runs · R6 dormant reserves ·
R7 duplicate claims · R8 loss run adds up to its own stated total

A clean corpus produces no findings at all, and that path is tested. An honest
report of nothing is a valid output.

## Formats

CSV and PDF loss runs both parse to the same rows, and there is a test asserting
the same policy year read two ways gives identical facts. The PDF parser is
deliberately conservative: a row is accepted only when every field is present
and every figure parses. Rows that look like claim lines but do not fully parse
are counted and reported as unreadable rather than guessed at, because a
half-read row is worse than a missing one on a document feeding a coverage
decision.

Accountant notation is parsed as written: `(12,400.00)` is negative, `—` is nil,
`$1,204,880.00` is a figure. A string that is not a figure raises rather than
quietly becoming `0.00` — silently reading `pending` as zero would corrupt a
total.

## Budget

One operation per run, capped at six. The cap is enforced **before** each
spend. Hitting it degrades rather than dies: the review is still produced, and
the section that could not be completed is named in *What this review does not
establish* instead of quietly disappearing. There is a test that runs with a cap
of one and asserts exactly that.

```bash
python -m lossrun.review --corpus corpus/out --out out --mode live --max-ops 6 --as-of 2026-01-09 --skip-prose
```

## The corpus

`corpus/` generates a fabricated account — Meridian Cold Chain Logistics, a
refrigerated carrier — with 41 claims across four policy years, five loss runs
including one reissue, three adjuster notes, a signed application, a broker
cover note, and the underwriting checklist. CSV, PDF and DOCX.

`corpus/MANIFEST.md` is the answer key: nine planted conflicts and thirteen
expected findings, with verified figures. The test suite asserts the app
reproduces it **exactly** — every planted item found, and nothing outside the
key reported. 34 of the 41 claims are deliberately clean, which is what makes a
false positive measurable rather than arguable.

Everything is fabricated. Meridian Cold Chain Logistics, Kestrel Mutual and
Ardent Risk Partners do not exist, and no figure comes from any real claim,
policy or company.

## Known defect: the DOCX export returns the wrong document

**`out/review.html` is correct and complete. `out/loss-run-review.docx` is not.**

The app uploads the adjuster notes, application and correspondence to the
session so the agent can read them for the correspondence section. Export then
asks the session for "the document" — and returns the last file uploaded, not
the review that was passed to the edit call as `document_html`. On the sample
corpus the exported DOCX comes back containing the underwriting checklist.

Everything upstream of the export is unaffected: the figures, the conflicts, the
findings and the citations are all correct, and `out/summary.json` and
`out/review.html` carry them. The defect is in how this build sequences upload
against export, not in the analysis.

The likely fix is to make the review itself the session document before editing,
rather than passing it only as `document_html`. That needs live API calls to get
right, so it is stated here rather than guessed at.

## Honest limits

- **The carrier's own numbers are taken as given.** Each run is checked against
  itself and against the others; nothing here can confirm the carrier was right.
- **Retrieval quality is not measured.** The offline fake fills the placeholder
  by keyword, deliberately weaker than the live agent, so a point that only
  surfaces against the real API stays visible rather than hidden.
- **If the edit proposes no changes**, the correspondence section keeps its
  placeholder and the run says so under *What this review does not establish*
  rather than reporting a success it did not have.
- **Figures do not depend on retrieval at all**, and there is a test that proves
  it: the pipeline is run twice, once with retrieval and once with
  `--skip-prose`, and every total, ratio and finding must be identical.
- **R5 reads specific declarations** from the application. Where a declaration
  is not found, nothing is asserted about it — an absent statement is not a
  false one.
- **PDF reading needs `pdfplumber`**, which `requirements.txt` installs. An
  earlier version shelled out to `pdftotext`, a Unix binary: it worked on the
  machine it was written on and died with a bare `WinError 2` on the machine it
  was used on. Where no reader is available the CSV path is unaffected and the
  failure names the fix instead of raising a traceback.
- **R7 needs description overlap**, not just a matching date and amount. An
  early version flagged any two claims sharing a date and figure, which on a
  fleet account is coincidence rather than duplication. Found by the
  clean-corpus test, and the rule was fixed rather than the test.
- **The DOCX export is broken**, as above. The HTML review is the working
  deliverable.
- **No coverage recommendation.** The app summarises and flags; it does not
  advise whether to write the risk, and the chat instruction forbids adding one.

Portions of this work were written with AI assistance, directed and reviewed
by me.
