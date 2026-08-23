# Preprint to Journal Submission Converter

A tool that transforms a manuscript from preprint format to the submission requirements of a specific target journal, using [SuperDocs](https://superdocs.app) as the document editing engine.

**Built for:** Researchers moving a manuscript from a preprint server to a journal submission.

---

## What it does

1. Accepts a manuscript as a `.docx` file
2. Lets the user select a target journal
3. Sends the manuscript to SuperDocs with a journal-specific transformation instruction
4. Presents each proposed change for the user to approve or deny individually
5. Builds a compliance report showing which journal requirements were met, unmet, or unverifiable
6. Checks that scientific content (numbers, statistics, equations, citations) was not altered
7. Applies blinding when the journal requires double-blind review
8. Exports the finished manuscript as `.docx`
9. Supports switching to a different journal — always restarting from the original manuscript

---

## Who it serves

Researchers who need to reformat a preprint for journal submission. The tool handles structural and formatting changes (section order, reference style, figure/table placement, declarations, blinding) while explicitly preserving scientific content.

---

## How to run

### Prerequisites

- Python 3.10+
- A SuperDocs API key ([get one free at use.superdocs.app](https://use.superdocs.app))

### Setup

```bash
cd use-cases/AdhiShak3008/preprint-to-journal

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set SUPERDOCS_API_KEY=your-key-here
```

### Run

```bash
# Load environment variables and start the server
# macOS/Linux:
export $(cat .env | xargs) && python app.py

# Windows (PowerShell):
Get-Content .env | ForEach-Object { $k,$v = $_ -split '=',2; [System.Environment]::SetEnvironmentVariable($k,$v) }
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## Required environment variables

| Variable | Required | Description |
|---|---|---|
| `SUPERDOCS_API_KEY` | Yes | Your SuperDocs API key. Never committed to the repository. |
| `FLASK_SECRET_KEY` | No | Flask session signing key. Defaults to a random value (sessions lost on restart). |
| `FLASK_DEBUG` | No | Set to `true` for development. Default: `false`. |
| `PORT` | No | Server port. Default: `5000`. |

---

## How SuperDocs is used

This project uses the SuperDocs REST API for all document operations:

| Operation | SuperDocs endpoint | Purpose |
|---|---|---|
| Upload manuscript | `POST /v1/documents/upload` | Parse DOCX into structured HTML with `data-chunk-id` attributes |
| Start transformation | `POST /v1/chat/async` with `approval_mode='ask_every_time'` | Submit the journal-specific transformation instruction |
| Poll for progress | `GET /v1/jobs/{job_id}` | Check job status; retrieve proposed changes when ready |
| Approve/deny changes | `POST /v1/chat/{session_id}/approve` | Submit per-change decisions |
| Export | `POST /v1/documents/export` | Download the finished manuscript as DOCX |

The API key is held server-side only and never sent to the browser.

`data-chunk-id` attributes are preserved throughout — they are what allow SuperDocs to make targeted, section-level edits rather than rewriting the whole document.

---

## How journal profiles work

Journal requirements are stored as JSON files in `journal_profiles/`. Each file describes one journal's requirements:

```json
{
  "id": "nature",
  "name": "Nature",
  "section_order": ["Abstract", "Introduction", "Results", "Discussion", "Methods", "References", ...],
  "reference_style": "numbered-superscript",
  "word_limit": 3000,
  "figure_placement": "end",
  "table_placement": "end",
  "blinded_review": false,
  "required_declarations": ["competing_interests", "data_availability", "author_contributions"]
}
```

**Adding a new journal** means adding a new JSON file — no code changes are needed. The application reads all profiles at startup and presents them as options.

Included profiles:
- `nature.json` — Nature: numbered-superscript references, 3000-word limit, Methods after Discussion, no blinding
- `plos-one.json` — PLOS ONE: author-year references, structured abstract, double-blind review, funding declaration required

---

## How journal switching works

The original manuscript HTML is captured once at upload and stored immutably in the server session. Every journal conversion creates a **fresh SuperDocs session** and passes the original HTML as the starting document.

```
original_html (immutable)
    ├── conversion session → Nature
    ├── conversion session → PLOS ONE
    └── conversion session → (any other journal)
```

Switching journals never chains transformations. Journal A's output is never used as input for Journal B.

---

## How scientific-content preservation is checked

After transformation, `preservation_checker.py` compares the original and transformed HTML:

- **Numerical values**: integers, decimals, percentages, scientific notation
- **Statistical markers**: p-values, confidence intervals, F-statistics, t-statistics, n=, r=, OR=, HR=, Cohen's d
- **Equations**: LaTeX inline/display math, `<math>` elements
- **Citation references**: numbered `[1]`, author-year `(Smith et al., 2020)`
- **Sentence fingerprints**: first-6-word fingerprints of substantive sentences

Any marker present in the original but absent in the transformed version is flagged. The compliance report shows the full list of flagged items.

**Limitation (shown to users):** This check provides a practical signal, not a guarantee. Structural changes (section reordering, reference reformatting) may produce false positives. A clean report does not prove that scientific content is unchanged — it means no numerical, statistical, equation, or citation markers were lost.

---

## How blinding is handled

When a journal profile has `"blinded_review": true`, the transformation instruction includes explicit blinding directives:

1. **Author names** → replaced with `[AUTHOR REMOVED]`
2. **Affiliations** → replaced with `[AFFILIATION REMOVED]`
3. **Acknowledgements** → entire section replaced with `[ACKNOWLEDGEMENTS REMOVED FOR BLIND REVIEW]`
4. **Funding details** → grant numbers and funder names replaced with `[FUNDING DETAILS REMOVED FOR BLIND REVIEW]`
5. **Self-citations** → references matching author surnames replaced with `[SELF-CITATION REMOVED FOR BLIND REVIEW]`
6. **Self-identifying language** → phrases like "in our previous work", "our group", "our lab" replaced with neutral alternatives and flagged with `[SELF-IDENTIFYING LANGUAGE REMOVED]`
7. **Contact details** → email addresses and postal addresses replaced with `[CONTACT DETAILS REMOVED FOR BLIND REVIEW]`

After transformation, `blinding.py` analyses the output for:
- Blinding placeholders that were successfully inserted
- Potentially remaining identifiers (self-identifying phrases, email patterns, known author name fragments)

The compliance report shows both what was removed and what may remain, with an explicit limitation notice.

**Limitation (shown to users):** Automated blinding is not infallible. Users must review the blinded manuscript before submission.

---

## How unmet requirements are reported

The compliance report uses five honest statuses:

| Status | Meaning |
|---|---|
| ✓ Met | Requirement was checked and found to be satisfied |
| ~ Instructed | The AI was instructed to apply this; cannot be verified programmatically — manual review recommended |
| ⚠ Partial | Requirement partially satisfied; some items missing |
| ✗ Unmet | Requirement was checked and found not to be satisfied |
| ? Unverifiable | Cannot be checked from the HTML alone |

Rules:
- Reference style formatting is always `Instructed` — it cannot be reliably verified from HTML
- Missing declarations are `Unmet` with the specific declaration named
- Word limit exceeded is `Unmet` with the word count shown
- The system never claims compliance for something it cannot verify

---

## Known limitations

1. **Reference style verification**: The system cannot reliably verify that reference formatting was applied correctly. Manual review of the reference list is always required.
2. **Automated blinding**: Cannot guarantee complete anonymisation. Self-citations and self-identifying language detection is heuristic and may miss cases or produce false positives.
3. **Scientific content preservation**: The checker detects missing numerical/statistical markers but cannot verify that the meaning of every sentence is preserved.
4. **Word counting**: The word count is approximate (counts all text in the HTML) and may differ from the journal's official counting method.
5. **Section detection**: Section heading matching is fuzzy — a section titled "Materials and Methods" will match a profile requirement of "Methods" but may not match "Experimental Procedures".
6. **In-memory state**: Session state is lost on server restart. This is appropriate for a demo; a production deployment would use a persistent store.
7. **Single user**: The demo is designed for single-user local use. Multi-user deployments would need per-user session isolation.
8. **DOCX only**: Only `.docx` input is supported. PDF and other formats are not supported.

---

## How to run tests

Tests run without a live SuperDocs API key. All HTTP calls are mocked.

```bash
cd use-cases/AdhiShak3008/preprint-to-journal
pip install -r requirements.txt
pytest tests/ -v
```

Test coverage:
- `test_journal_loader.py` — profile loading, validation, error handling
- `test_instruction_builder.py` — instruction generation for both journals
- `test_preservation_checker.py` — number/stat/equation/citation extraction and comparison
- `test_blinding.py` — blinding instruction building and post-transformation analysis
- `test_compliance_reporter.py` — requirement checking and report generation
- `test_superdocs_client.py` — API client, response parsing, double-parse of proposed changes, error handling

---

## Demo

A synthetic manuscript is provided for testing in two formats:

- **`demo/sample_manuscript.docx`** — ready to upload directly into the app
- **`demo/sample_manuscript.md`** — the same content in Markdown for reference

The demo manuscript is a fictional neuroscience study with realistic structure, statistics, equations, self-citations, and acknowledgements — designed to exercise all transformation and blinding features.

---

## SuperDocs features used

- Document upload (multipart DOCX → structured HTML with chunk IDs)
- Async chat with `approval_mode='ask_every_time'` (human-in-the-loop approval)
- Job polling (`GET /v1/jobs/{job_id}`)
- Per-change approval/denial (`POST /v1/chat/{session_id}/approve`)
- DOCX export (`POST /v1/documents/export`)

---

## Author

AdhiShak3008
