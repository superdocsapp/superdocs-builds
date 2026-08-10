# Apparel Technical Pack Generator

Generates a factory-ready technical pack (graded measurement spec, bill of
materials, construction notes, flat sketches) for an apparel style, built on
the SuperDocs API.

## What it does

1. Loads a style definition (`styles/*.json`) containing points of measure,
   grade rules, materials, and construction notes.
2. **Grades every measurement point deterministically in code** — the AI
   never computes sizing math. `techpack/grading.py` applies
   `value = base_value + grade_rule × steps_from_base_size` per point, so
   correctness across sizes is guaranteed by arithmetic, not by trusting a
   model.
3. Builds an initial HTML document with the graded table already baked in,
   sends it to SuperDocs for formatting polish and AI-generated flat
   sketches, and **re-verifies the measurement table against the source
   data after every edit** (`techpack/verification.py`) — the pipeline
   never trusts a chat response's own claim that numbers are unchanged.
4. Exports the final result as a `.docx` via SuperDocs' export endpoint.

## Setup

    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt -r requirements-dev.txt
    cp .env.example .env   # add your SUPERDOCS_API_KEY

## Run

    python3 main.py

Output lands in `output/<style_id>_techpack.docx`.

## Tests

    python3 -m pytest tests/ -v

17 tests, all mocked — grading correctness, JSON-string-in-JSON response
parsing, and table-verification logic, none requiring a live API key.

## Design decisions & assumptions (logged as I went)

- **Grading is code, not AI.** The task brief notes that where a build
  handles figures it can't independently verify, it's graded on whether it
  *detects and surfaces* problems, not whether numbers happen to be right.
  Rather than ask the model to grade sizes, the math is deterministic and
  the AI is only used for formatting and imagery — removing the risk
  entirely rather than trying to catch it after the fact.
- **`export` endpoint path was undocumented for the Bearer-key API.**
  Found the real payload shape (`POST /v1/documents/export`, full HTML in
  the body, raw file bytes back) by inspecting the web app's own network
  traffic in DevTools. Confirmed working from `api.superdocs.app` with a
  Bearer key in this build.
- **`approve`/`pending_changes` never triggered in testing.** Every edit
  sent during development — including a full 6-section rewrite — came back
  `auto_approved`. `approve_changes()` is implemented and wired into
  `main.py`'s flow but is unverified against a live response, since no
  instruction sent during this task ever produced `requires_approval: true`.
  Logged as an open gap rather than assumed correct.
- **Sessions are stateful and persist edits.** Reusing a `session_id`
  continues editing the same in-progress document; a repeated,
  already-satisfied instruction correctly returns a no-op
  (`document_changes: null`) rather than reapplying itself.

## Known bugs found while building

- A tested edit's `response` field claimed a formatting-only change while
  the returned HTML contained an entirely fabricated, unrelated
  "Operational Correspondence" letter with invented reference numbers and
  unfilled placeholder fields — reported as success despite being wrong.
- Requesting a single front/back flat sketch pair sometimes inserted two
  duplicate pairs into the document instead of one.
- An early response's `response` field returned a generic "wasn't able to
  put together a safe reply" fallback message despite the underlying edit
  succeeding correctly.

## Project structure

    styles/            style definitions (POMs, materials, construction)
    techpack/
      grading.py        deterministic size grading
      generator.py       builds initial document HTML
      superdocs_client.py  API wrapper (chat, approve, export)
      verification.py    post-edit correctness checks
    tests/              pytest suite, no live key required
    main.py             orchestrates the full pipeline