# RFE Response Builder

**Family:** Vertical mini-app
**Industry / document type:** Immigration law — Request for Evidence (RFE) responses
**Surfaces used:** API, Export, Review, Search (multi-document, keyword)

## What it does

Given (1) a USCIS-style RFE notice, (2) the arguments the original petition
already made, and optionally (3) a catalog of new evidence and free-text
supporting documents, this app:

1. Parses the officer's notice into individually addressable numbered
   requests.
2. Matches each request against what the petition already argued, citing
   the exact source (never inventing a citation).
3. Identifies new evidence that speaks to unmatched requests, and flags
   anything with no match at all for attorney attention.
4. Drafts a response section per request via SuperDocs, **held for human
   approval** before it counts as answered or reaches the exported
   document.
5. Assembles a numbered, deduplicated exhibit list.
6. Produces a coverage checklist mapping every request in the notice to
   the exact section of the response that answers it — or explicitly
   marks it NOT ANSWERED, never silently.
7. Exports the finished response as a `.docx`.

## Where the real code lives

This folder is a pointer, not a copy of the app — the actual
implementation lives at the repo root:

- `rfe_response_builder/` — domain logic (parsing, matching, drafting
  instructions, coverage checklist, human-review orchestration)
- `webapp/` — the Flask UI (upload → review → export)
- `tests/` — 64 offline tests, no live SuperDocs calls required
- `README.md` (repo root) — full setup, architecture, and honest
  "what's cut / what broke" notes

Run it locally with `python webapp/app.py` (see repo root README for
setup) or deploy with the included `render.yaml`.

## Sample inputs (in this folder)

- `sample_rfe_notice.txt` — a synthetic RFE notice with 3 numbered
  requests (bona fide marriage evidence, financial commingling,
  cohabitation)
- `sample_petition_arguments.json` — the original petition's arguments,
  with page-level source references
- `sample_new_evidence.json` — a catalog of new evidence available to
  cite

All data is synthetic; no real case information.

## Buyer / user profile

Solo and boutique immigration law practices that handle RFE responses
by hand today — see the repo root README's growth-research notes for
named example firms and the reasoning behind targeting that segment
over large full-service immigration firms.

## Honest scope boundaries

- Prior-petition matching is deterministic keyword overlap over
  uploaded documents, not embeddings/semantic search — every citation
  this produces traces to a real paragraph in a real uploaded document,
  which is the property that matters most for a legal-filing tool; see
  `rfe_response_builder/rfe.py`'s `arguments_from_free_text` docstring
  for the reasoning.
  - Physical exhibit files aren't assembled into the final packet yet —
  the exhibit list is a manifest (number, label, description,
  which request it supports), not the attached documents themselves.
- This tool assists with drafting and organization. It is not legal
  advice and every section must be reviewed by an attorney before
  filing — enforced in the product itself via the review gate, and
  stated directly in the app's UI.
