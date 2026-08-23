# Preprint-to-Journal Converter — Walkthrough

A Flask web app that takes a preprint manuscript (DOCX) and reformats it to meet the submission requirements of a target journal, using the SuperDocs API to apply and review every change.

---

## What was built

### The problem

Researchers write preprints in a generic format, then manually reformat them for each journal they submit to — different section orders, reference styles, word limits, abstract structures, and blinding requirements. This is tedious and error-prone.

### The solution

Upload your DOCX once. Pick a journal. The app sends the manuscript to SuperDocs with a precise transformation instruction, then surfaces every proposed change for your approval before anything is committed. After you approve, it generates a compliance report telling you what was fixed, what still needs attention, and (for double-blind journals) flags any remaining author identifiers it found.

### Architecture

```
Browser  ──►  Flask (app.py)  ──►  SuperDocs REST API
                  │
                  ├── superdocs_client.py   thin HTTP wrapper
                  ├── journal_loader.py     loads JSON profiles
                  ├── instruction_builder.py  builds the prompt
                  ├── blinding.py           author-blinding logic
                  ├── preservation_checker.py  science integrity check
                  └── compliance_reporter.py   per-requirement status
```

State is held in memory (keyed by browser session UUID). No database, no external infrastructure.

### Journals supported

| Journal | Refs | Word limit | Abstract | Blinded |
|---|---|---|---|---|
| Nature | Numbered superscript | 3 000 words | 150 words, unstructured | No |
| PLOS ONE | Author-year | None | 300 words, structured (Background / Methodology / Conclusions) | Yes (double-blind) |

These two were chosen deliberately — they differ on every axis, so every feature of the app gets exercised.

### Key design decisions

- **Original manuscript is immutable.** `original_html` is captured once at upload and stored read-only. Every journal conversion starts from it. Journal A output never feeds Journal B.
- **Human-in-the-loop approval.** SuperDocs is called with `approval_mode='ask_every_time'`. Every proposed change is shown to you with a before/after diff. You approve or deny each one before anything is written.
- **Honest reporting.** Reference style is always reported as `instruction_sent` (the app cannot verify citation format from HTML). Missing declarations are named individually as `unmet`. Word-limit overruns show the exact count.
- **Blinding is heuristic, not guaranteed.** The app flags potential remaining identifiers (author names, "our lab/group", email addresses, self-identifying language) but always tells you this is a heuristic scan, not a guarantee.
- **Science preservation checker.** After transformation, the app compares numbers, statistical markers, equations, and citation references between original and output. A clean report does not prove preservation — the limitation is always shown.

---

## Project structure

```
preprint-to-journal/
├── app.py                    Flask routes and in-memory state
├── superdocs_client.py       SuperDocs API wrapper
├── journal_loader.py         JSON profile loader/validator
├── instruction_builder.py    Builds the transformation prompt
├── blinding.py               Blinding directives + post-transform scan
├── preservation_checker.py   Science integrity comparison
├── compliance_reporter.py    Per-requirement compliance status
├── journal_profiles/
│   ├── nature.json
│   └── plos-one.json
├── templates/
│   ├── index.html            Upload + journal selection
│   ├── review.html           Change approval UI
│   └── report.html           Compliance report + export
├── static/
│   ├── app.js
│   └── style.css
├── demo/
│   └── sample_manuscript.md  Synthetic preprint for testing
├── tests/                    117 unit tests (all passing)
├── requirements.txt
└── .env.example
```

---

## How to run it

### 1. Prerequisites

- Python 3.9+
- A SuperDocs API key — get one at [docs.superdocs.app](https://docs.superdocs.app)

### 2. Install dependencies

```bash
cd use-cases/AdhiShak3008/preprint-to-journal
pip install -r requirements.txt
```

### 3. Set your API key

```bash
cp .env.example .env
```

Open `.env` and set:

```
SUPERDOCS_API_KEY=your-actual-key-here
```

### 4. Start the server

```bash
python app.py
```

The app runs on `http://localhost:5000` by default. Set `PORT=8080` in `.env` to change it.

---

## How to use it

### With the demo manuscript

The `demo/sample_manuscript.md` file is a synthetic neuroscience preprint (DRP1/mitochondria/Parkinson's disease) with realistic statistics, equations, self-citations, and author acknowledgements — designed to exercise every feature.

Convert it to DOCX first (Pandoc, Word, or any Markdown editor), then follow the steps below.

```bash
# If you have Pandoc installed:
pandoc demo/sample_manuscript.md -o demo/sample_manuscript.docx
```

### Step-by-step

1. Open `http://localhost:5000`
2. Upload your DOCX file
3. Select a journal (Nature or PLOS ONE)
4. For PLOS ONE, optionally enter author names and institution — the app will instruct SuperDocs to blind them
5. Click **Transform** — the app uploads your document to SuperDocs and starts the transformation
6. The **Review Changes** page polls for proposed changes. Each change shows a before/after diff with Approve / Deny buttons. Use **Approve All** or **Deny All** for speed, or review individually
7. Click **Submit Decisions** — approved changes are committed, denied ones are discarded
8. The **Compliance Report** page shows:
   - Per-requirement status (met / unmet / instruction sent / unverifiable)
   - Science preservation check (numbers, stats, equations, citations compared)
   - Blinding scan (PLOS ONE only) — flags any remaining author identifiers
9. Click **Export DOCX** to download the final document

---

## How to run the tests

```bash
cd use-cases/AdhiShak3008/preprint-to-journal
pytest
```

Expected output: `117 passed`

All HTTP calls to SuperDocs are mocked — no API key needed to run the tests.

### What the tests cover

| File | Tests | What's covered |
|---|---|---|
| `test_superdocs_client.py` | 30 | Upload, transform, poll, double-parse of pending changes, approve, export, missing API key |
| `test_journal_loader.py` | 12 | Valid loads, missing fields, invalid JSON, wrong types, malformed files skipped |
| `test_instruction_builder.py` | 17 | Science preamble, section order, reference style, word limits, blinding present/absent |
| `test_preservation_checker.py` | 19 | Number/stat/equation/citation extraction, missing items flagged, structural reorder no false positive |
| `test_blinding.py` | 22 | All 7 blinding directives, placeholder detection, remaining identifier detection |
| `test_compliance_reporter.py` | 17 | Section present/missing, word limit met/exceeded, declarations met/unmet, blinding met/partial |

### Note on pycache

If you see a single unexpected failure on the very first run, delete the cache and re-run:

```bash
# Windows
rmdir /s /q __pycache__
pytest

# macOS / Linux
rm -rf __pycache__
pytest
```

---

## Adding a new journal

1. Create `journal_profiles/<journal-id>.json` — copy `nature.json` as a template
2. Fill in: `id`, `name`, `section_order`, `reference_style`, `figure_placement`, `table_placement`, `blinded_review`, `required_declarations`, and optionally `word_limit`, `abstract_word_limit`, `abstract_structure`, `notes`
3. Restart the server — the new journal appears automatically in the UI

No code changes required.

---

## API endpoints (for scripting)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/upload` | Upload DOCX, returns `session_id` |
| `POST` | `/api/transform` | Start transformation, returns `job_id` |
| `GET` | `/api/poll/<job_id>` | Poll job status and pending changes |
| `POST` | `/api/approve` | Submit per-change approve/deny decisions |
| `GET` | `/api/export` | Download final DOCX |
| `GET` | `/api/journals` | List available journal profiles |
