# Systematic Review Package Assembler

Built on [SuperDocs](https://superdocs.app) for a research fellow or evidence-synthesis specialist preparing a systematic review for publication. Assembles the pieces a systematic review needs to ship — a PRISMA-style flow diagram generated from real screening counts, evidence tables built from an extraction sheet, a search-strategy appendix, a risk-of-bias summary, and a reporting checklist whose page references are detected from the actual exported document, not typed by hand — as a sequence of targeted, human-reviewed edits against a real manuscript.

## Why this exists

Systematic reviews have a structural integrity problem: the flow diagram's numbers, the prose describing those numbers, and the checklist's page references all have to agree with each other and with the real document — and they routinely don't, because they're maintained by hand in three different places. This tool makes the diagram and the checklist **derived**, not typed: change a screening count and the diagram moves with it; re-paginate the manuscript and the checklist's page numbers are re-detected from the real, freshly-exported PDF.

## What it does

1. **Validates** screening counts for internal arithmetic consistency (identified → screened → assessed → included) before generating anything from them.
2. **Renders** a PRISMA flow diagram locally from those counts — no number in the diagram is ever hand-typed.
3. **Assembles**, via a sequence of targeted, human-reviewed SuperDocs chat edits: the flow diagram (as an image attachment), an evidence table (from a CSV extraction sheet), a search-strategy appendix (from a CSV of database queries), and a risk-of-bias summary table (from a CSV).
4. **Detects real page numbers** for a reporting checklist by exporting the assembled manuscript as a PDF and searching it directly (via `pymupdf`) for each checklist item's expected content.
5. **Verifies every single step** against the actual exported file — not just the API's own "success" response — and retries automatically if content is missing, duplicated, or fabricated.
6. **Proves** the checklist updates correctly after the manuscript changes: insert new content earlier in the document, re-export, re-detect, and the affected checklist entries' page numbers move accordingly (see `src/prove_repagination.py` and `PROGRESS.md`).

## Quickstart

```bash
git clone <this-repo-url>
cd superdocs-review-assembler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your SuperDocs API key (get one at use.superdocs.app)
```

Run the full assembly pipeline against the included sample data:

```bash
cd src
python assemble_review_package.py
```

This validates the sample screening counts, renders the flow diagram, uploads a sample manuscript, and inserts everything — pausing for human review (via the API's `ask_every_time` approval mode) before each change is committed. The finished package lands at `output/final_review_package.docx`.

To prove the checklist's page references update correctly after an edit:

```bash
python prove_repagination.py <session_id>
```

(Use the session ID printed near the top of the assembly run's output.)

## Bring your own data

Replace the files in `sample_data/` with your own:

- `screening_counts.json` — your PRISMA screening counts
- `search_strategy.csv` — one row per database (`database,query,filters,date_run,hits`)
- `extraction_sheet.csv` — one row per included study (`study_id,author_year,design,n_participants,intervention,comparator,primary_outcome,result`)
- `risk_of_bias.csv` — one row per study (`study_id,randomization,deviations,missing_data,outcome_measurement,selective_reporting,overall`)
- `draft_manuscript.html` — your manuscript draft (plain HTML)

Adjust `src/checklist.py`'s `CHECKLIST_ITEMS` if your reporting checklist differs from the included PRISMA-style example — each item needs an `anchor_text` string that will appear exactly once in your assembled document.

## Running tests (no API key required)

```bash
cd tests
pytest . -v
```

Covers count-consistency validation, PDF page-detection accuracy, and the content-verification/duplicate-detection logic — all deterministic, no network calls.

## Architecture

- **`src/flow_diagram.py`** — count validation and local diagram rendering (matplotlib)
- **`src/build_tables.py`** — builds HTML tables/appendix content directly from CSVs (the AI's job is placement, never authorship of the data)
- **`src/insert_content.py`** — sends a targeted edit, waits for approval, retries if the raw proposed change contains fabricated placeholder content
- **`src/superdocs_client.py`** — thin REST client, plus `verify_export_state()`: exports the current session and checks the real file for expected/forbidden/duplicated content
- **`src/checklist.py`** / **`src/page_finder.py`** — checklist definition and real PDF page-detection via `pymupdf`
- **`src/assemble_review_package.py`** — the full pipeline, with a verification checkpoint after every insertion
- **`src/prove_repagination.py`** — the re-pagination proof described above
- **`debug_scripts/`** — the isolation/diagnostic scripts used to characterize a real, intermittent content-fabrication issue in SuperDocs' chat-edit behavior (see below)

## An important, honestly-reported finding

While building this, targeted testing surfaced a genuine, intermittent issue in SuperDocs' handling of "insert this exact content verbatim" instructions: on a low but real fraction of otherwise-identical requests, the API would insert fabricated placeholder content (e.g. `"Please fill: ..."` template text, or plausible-sounding but entirely invented prose) instead of the real, supplied data — with the chat API itself reporting success. This was isolated through repeated, controlled testing (varying step order, content adjacency, and chain depth) and confirmed as non-deterministic rather than tied to any specific trigger: the identical 4-step request sequence succeeded cleanly in some runs and fabricated content in others.

This tool's verification-and-retry design exists specifically because of this finding — every insertion is checked against the real exported file, not trusted from the API's response alone. Full investigation notes, including the isolation methodology and a documented wrong hypothesis that was caught and corrected along the way, are in `PROGRESS.md`.

## Known limitations

- Checklist anchor text must be unique within the document; if source content happens to repeat a checklist item's anchor phrase elsewhere, page detection will report the first occurrence, which may not be the intended one.
- The verification-and-retry pattern adds real cost — each insertion step performs a full export for checking, not just the final one. This trade-off (correctness over speed) is deliberate given the confirmed intermittency above.
- Heading-only gaps (the real data lands correctly, but its introductory heading text is occasionally omitted) are logged as non-fatal notes rather than triggering a retry, since the underlying data integrity is unaffected — see `PROGRESS.md` for the reasoning.

## Credit

Built for the SuperDocs engineering task by Ujjwal Sharma.