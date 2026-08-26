# Fund document annual-update engine

Fund paperwork refreshes on a calendar. Performance figures, fees, risk indicators, holdings tables
and dates move; the legal wording does not. Doing that by hand means retyping numbers across a
prospectus, a factsheet and a KID, then asking a compliance reviewer to spot anything that changed
which should not have.

This engine takes **last year's document set plus this year's figures** and updates only what
actually moved. It hands the reviewer a marked version and a change log where every number points
back to the cell it came from, exports the clean final, and then checks its own work: page budgets
held, tables did not gain rows, and untouched legal wording is byte-identical.

Built on SuperDocs. All documents and figures here are fictional.

---

## What it actually does

**Only what changed.** The engine reads the current value out of each document and compares it to
the data file. In the sample set, four of the five performance rows carry the same value as last
year, so no edit is requested for them and no operation is spent. Thirteen edits across three
documents cost **three operations**, because edits are batched one request per document and a
single request covers up to twenty-five targeted sections.

**It refuses to fill in gaps.** The sample data file gives `holding_2` a company name with no
weight. A holdings row needs both. The engine does not carry the old weight forward and does not
estimate one; it puts the row in front of a person and says why.

**It keeps the sentence around the number.** The KID says "Summary risk indicator: 4 out of 7" and
the data file supplies `5`. A naive replace produces "Summary risk indicator: 5" and quietly deletes
the scale. Fields that sit inside a sentence declare how they render, in the field map, not in code.

**Nothing commits itself.** Every edit is sent with `approval_mode: ask_every_time`, so changes wait
as pending items until a reviewer approves or rejects each one. Rejecting one leaves the rest.

**It checks the artefact, not the intent.** After export, the engine re-reads the produced files
and asserts: protected legal paragraphs hash identically to before, tables listed as
`must_not_reflow` have the same row and column counts, the exported PDF is within the page budget
(three pages for a KID is a regulatory ceiling, not a preference), and no paragraph changed that no
edit asked for.

---

## Run it

```bash
python -m venv .venv && . .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"

python make_fixtures.py        # builds the sample document set and this year's figures
fund-update plan               # what would change. No key, no network, no spend.
```

`plan` writes two artefacts to `out/review/`:

- `marked-version.html` — the reviewable marked version, grouped by document, each change beside
  the cell it came from
- `change-log.docx` — the change-log document, one row per edit with its source

To drive SuperDocs for real:

```bash
cp .env.example .env           # then add your key
fund-update whoami             # tier and operations remaining
fund-update run                # prompts for each change
fund-update run --approve-all  # approves everything, for a demo
fund-update run --sample 2     # small-sample mode, for a cheap first run
```

| Variable | Meaning |
|---|---|
| `SUPERDOCS_API_KEY` | `your-key-here` from use.superdocs.app |
| `SUPERDOCS_API_BASE` | defaults to `https://api.superdocs.app` |
| `FUND_UPDATE_MAX_OPERATIONS` | stopping rule; the engine halts rather than overspending |
| `FUND_UPDATE_SAMPLE` | process only the first N fields |

```bash
pytest -q     # 30 tests, no API key required
```

---

## Measured on a live run

Full run against a live SuperDocs account on 19 August 2026, `model_tier: pro`, free tier.

| | |
|---|---|
| Edits requested | **13**, across 3 documents |
| Edits verified present in the exports | **13 of 13** |
| Operations spent | **3** (one chat request per document) |
| API requests | 42 |
| API time | 34.5s |
| Fields unchanged, so never requested | **4** (`perf_2021`–`perf_2024`) |
| Figures referred to a human instead of guessed | **1** (`holding_2`, name with no weight) |
| Release guards | passed on all three documents |
| Tests, no API key needed | **30**, in under a second |

The verification is not the engine marking its own homework: the exported `.docx` files are
re-read from disk and every requested value is looked for in the text and table cells. The KID's
`4 out of 7` became `5 out of 7`, not a bare `5`.

![The marked version a reviewer signs off](docs/marked-version.png)

Both artefacts from that run are committed: [`docs/marked-version.html`](docs/marked-version.html) and [`docs/change-log.docx`](docs/change-log.docx).

---

## What it uses from SuperDocs

| Surface | Used for |
|---|---|
| `POST /v1/sessions/init` | one session per document, see below |
| `POST /v1/documents/upload-base64` | upload the prospectus, factsheet or KID |
| `POST /v1/attachments/upload-base64` | attach the approved figures so the model reads them rather than being told them |
| `POST /v1/chat/async` | the targeted edits, with `approval_mode: ask_every_time` |
| `GET /v1/jobs/{job_id}` | poll for pending changes |
| `POST /v1/chat/{session_id}/approve` | the reviewer gate, item by item or batched |
| `POST /v1/documents/export` | clean final as .docx and .pdf |
| `GET /v1/agents/whoami` | tier and remaining operations |

**One session per document.** Uploading a second file into a session replaces the first rather
than adding it, so a three-document set needs three sessions. Sessions and attachments cost no
operations, so this is free; only `chat/async` is billable.

**The figures go up as markdown, not CSV.** The attachments endpoint rejects `.csv` with a 415, so
the engine renders the data file to a markdown table and uploads that.

---

## Three traps this build handles on purpose

**Proposed-change content arrives as a JSON-encoded string.** The final result is already an
object, but pending changes are not, and missing that second parse is the documented reason
integrators see diff cards where every field reads `undefined`. `parse_change` handles the string,
the object, and the double-encoded case, and all three are tested.

**Long operations look like crashes.** Runs at deeper model settings take from thirty seconds to
several minutes with no visible progress. The client polls with a deadline and, on timeout, says
that the job may still be running and that retrying costs another operation, rather than silently
firing a second request.

**An export taken straight after approval is the old document.** Approved changes apply
asynchronously and `export` does not wait, so the file comes back valid, correctly sized, and
missing every edit. Nothing in the response says so. The engine re-exports until the values it
asked for are actually present, and fails loudly if they never arrive. This one is not theoretical:
it is what the first full live run did, and every layout guard passed on the untouched document,
because a document where nothing changed satisfies "wording unchanged" perfectly.

---

## Honest limitations

**The reviewer gate is exercised, but `--approve-all` was used for the recorded run.** Every
change still goes up as a pending item and is approved through `/approve`; nothing auto-commits at
the API level. A human approving item by item is the default path and what `fund-update run` does
without the flag.

**Only the `.docx` export is verified before release.** The wait-for-apply loop reads the Word
file, because that is the format the engine can parse. The PDF is exported after that check passes
and is used for the page-budget guard alone.

**Page budgets are only verified when a PDF export exists.** Word documents have no page count
until something renders them, so the pre-flight check is structural and the real check happens on
the exported PDF. If no PDF comes back, the guard says the budget is unverified rather than
claiming it passed.

**Layout preservation is asserted, not authored.** The engine proves the typeset layout survived
by measuring the exported artefact. Keeping it intact is SuperDocs' job; catching it when it does
not is this engine's.

**The field map covers one fund range.** Adding a document type, a figure or another fund is a
change to `fieldmap.yaml`. It should never be a code change, and if it ever is, that is a bug.

---

Built by **Kanak Kholwal** for the SuperDocs engineer task, August 2026. MIT licensed.
All funds, figures and documents here are fictional.
