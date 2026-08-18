# Game Press Kit Builder

A grounded, resumable Game Press Kit Builder built on the SuperDocs API for the SuperDocs Round 2 **Game Press Kit Builder** assignment.

## What it does

Given a structured synthetic game dataset and its supplied press assets, the system:

1. ingests and validates source facts,
2. generates a complete English press kit,
3. validates the generated kit against the source,
4. renders HTML,
5. can upload/review the document through SuperDocs,
6. creates an explicit human approval checkpoint for proposed changes,
7. applies approvals/rejections item-by-item before export,
8. localizes narrative content while preserving protected factual sections, and
9. exports the approved HTML through SuperDocs as DOCX.

The deterministic stages save checkpoints, so a stopped run does not require regenerating completed work.

## Requirements

- Python 3.11+
- `pip`
- SuperDocs API key only for live upload/review/approval/export stages

Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure live API access:

```powershell
Copy-Item .env.example .env
```

Then set `SUPERDOCS_API_KEY` in `.env`. Never commit `.env`.

## One-command local demonstration

The complete deterministic pipeline can be run without a live API key:

```powershell
python -m backend.pipeline --input sample-data\emberfall.json
```

It generates:

```text
output/emberfall_press_kit.json
output/emberfall_press_kit.html
output/emberfall_press_kit_es.json
```

Run it on the second synthetic dataset to demonstrate that the generator is not Emberfall-specific:

```powershell
python -m backend.pipeline --input sample-data\ashvale.json --output-dir output\ashvale
```

## Live SuperDocs flow

After the local pipeline has produced HTML:

```powershell
python -m backend.upload_press_kit --input output\emberfall_press_kit.html --session-id emberfall-final
python -m backend.review_press_kit
```

Review creates:

```text
output/emberfall_review_response.json
output/emberfall_approval_checkpoint.json
```

### Human gate

The export is intentionally blocked until the approval checkpoint is explicitly approved:

```powershell
python -m backend.approve_press_kit
```

The approval script handles each proposed change independently. Rejecting one change does not discard approved changes. The final HTML is reconstructed from the original HTML plus **only approved edits**.

For a local/demo run without an API approval call:

```powershell
python -m backend.approve_press_kit --yes --no-api
```

Then export:

```powershell
python -m backend.export_press_kit
```

The export client handles both JSON and binary DOCX responses.

## Source grounding

`backend.fact_validator.validate_press_kit()` checks:

- Studio
- release date
- platforms
- price
- availability
- asset index
- verbatim quote
- history/inspiration
- feature list
- all three descriptions contain the canonical source core description

The generator composes narrative text only from `GameFacts`; it does not contain Emberfall-specific game facts.

The generated JSON also contains a `provenance` map identifying the source field for each major section.

If a narrative string has no verified Spanish translation, localization fails loudly instead of silently returning English.

## Assets

`sample-data/assets/` contains synthetic placeholder JPEGs matching every declared asset. `asset_validator.py` verifies that every source-declared asset exists before generation.

The placeholders are intentionally synthetic; the metadata in `sample-data/*.json` is the authoritative caption/type/credit source for the press kit.

## Localization invariants

Spanish localization changes:

- descriptions,
- features,
- history, and
- inspiration.

It preserves exactly:

- fact sheet,
- asset index,
- quote,
- awards, and
- coverage.

`validate_localization()` checks both preservation and actual narrative translation.

## Tests

Run:

```powershell
python -m pytest -v
```

The suite does **not** require a live SuperDocs API key.

It covers:

- required press-kit structure,
- fact corruption detection,
- narrative drift detection,
- source-backed descriptions,
- asset existence and missing-asset detection,
- localization invariants,
- unsupported translation detection,
- HTML escaping,
- item-by-item human approval/rejection,
- resumable local pipeline behavior, and
- a second synthetic game dataset.

## Project structure

```text
game-press-kit-builder/
├── backend/
│   ├── asset_validator.py
│   ├── approve_press_kit.py
│   ├── export_press_kit.py
│   ├── fact_loader.py
│   ├── fact_model.py
│   ├── fact_validator.py
│   ├── html_renderer.py
│   ├── localizer.py
│   ├── pipeline.py
│   ├── press_kit_generator.py
│   ├── review_press_kit.py
│   ├── send_to_superdocs.py
│   ├── superdocs_client.py
│   ├── translator.py
│   ├── upload_press_kit.py
│   └── workflow.py
├── sample-data/
│   ├── assets/
│   ├── ashvale.json
│   └── emberfall.json
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── TASK.md
└── README.md
```

## Design decisions and assumptions

- **Structured synthetic source data:** the assignment's synthetic datasets are JSON because they make factual provenance deterministic and testable.
- **Deterministic localization:** Spanish translation is deliberately isolated behind a translator interface. A missing verified translation is an error rather than a fallback to English.
- **SuperDocs remains the document agent:** this project does not clone SuperDocs; it uses its upload/chat/approval/export API.
- **Human approval is local and explicit:** even if the service reports an edit as auto-approved, this workflow does not commit proposed changes to the final export until the local human gate records a decision.
- **Rejected edits are preserved:** the final HTML is reconstructed from the original HTML and approved changes only.
- **Synthetic assets:** placeholder images are used solely to prove asset synchronization without introducing copyrighted game assets.
