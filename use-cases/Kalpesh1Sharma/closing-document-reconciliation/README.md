# Closing Document Reconciliation Memo

SuperDocs Round 2 — Assigned Build 1 (S3)

This build opens a five-document mortgage closing file in one SuperDocs session, extracts supported values from the processed document HTML, reconciles the file against its own underwriting rules, generates a side-by-side variance memo and correction request, supports read-only search/chat, sends edits through SuperDocs Review with an explicit approval gate, and exports DOCX artifacts.

## What the build reconciles

The workflow compares:

- loan amount
- interest rate
- loan term
- escrow
- title / settlement fees
- cash to close
- borrower names
- property address

A finding is classified as **tolerable** or **curable only when a rule inside the uploaded file supports that classification**. The build does not apply external mortgage law or infer missing values.

## Product surfaces

The Streamlit UI exposes the requested surfaces:

1. **Documents** — upload exactly five DOCX/PDF files into one shared SuperDocs session and inspect grounded extraction evidence.
2. **Reconciliation** — side-by-side values, evidence, file rule, explanation, classification, and recommended action.
3. **Memo & Correction** — generated reconciliation memo plus a separate correction request containing only curable findings.
4. **Search & Chat** — deterministic local search over SuperDocs processed HTML plus read-only SuperDocs chat. Chat is exploratory and never controls reconciliation decisions.
5. **Review** — upload a generated artifact to SuperDocs, request a surgical edit with `approval_mode="ask_every_time"`, inspect pending changes, then explicitly approve or reject.
6. **Export** — download generated DOCX files and export the approved reviewed artifact from SuperDocs.

## Architecture

```text
5 uploaded documents
        |
        v
SuperDocs /v1/documents/upload
(one shared multi-document session)
        |
        +--> processed HTML + document_id
                 |
                 v
        core/html_extraction.py
        deterministic label/value mapping
                 |
                 v
        core/extraction.py
        canonical normalization
                 |
                 v
        grounding validation
        unsupported evidence => hard stop
                 |
                 v
        core/workflow.py
        reconciliation + file rules
                 |
        +--------+---------+
        |                  |
        v                  v
reconciliation memo   correction request
        |                  |
        +--------+---------+
                 |
                 v
        SuperDocs Review
        ask_every_time approval gate
                 |
                 v
               export
```

### Why deterministic extraction?

During integration testing, `/v1/chat` sometimes routed structured extraction requests inconsistently even when a target `document_id` was supplied. Because unsupported extraction would be worse than a visible failure, the production path uses the **processed HTML returned by SuperDocs upload** and deterministic field-label aliases instead of depending on chat for numeric/file-rule extraction.

SuperDocs chat remains available as a visible **read-only exploratory surface**, and SuperDocs Review is used for the human-approved editing workflow.

## Grounding and safety behavior

- Every non-null extracted raw value must be present in the processed HTML for its source document.
- Evidence/rule quotes are checked against the source document.
- Grounding warnings stop the workflow instead of silently continuing.
- Missing values remain missing; the build does not invent them.
- File rules are treated as fictional file-specific instructions for the synthetic demo, not legal or regulatory rules.
- The correction request includes **curable findings only**.
- Reconciliation is deterministic; chat responses do not alter classifications.

## Scenario A proof

The synthetic Scenario A contains deliberately different labels across documents and three seeded differences:

| Field | Expected result |
| --- | --- |
| Loan amount | Match |
| Interest rate | Curable variance — 6.625% closing disclosure vs 6.500% approved rate |
| Loan term | Match |
| Escrow | Match |
| Title / settlement services | Tolerable variance — $150 difference, within $250 file-rule tolerance |
| Cash to close | Curable variance — $1,350 difference, above $500 file-rule threshold |
| Borrower names | Match under middle-initial rule |
| Property address | Match under abbreviation rule |

Expected summary:

```text
Matches:     5
Tolerable:   1
Curable:     2
Unresolved:  0
```

The two curable items are the only items included in the revised disclosure / correction request.

## Setup

From the build directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env` locally and add the SuperDocs API key expected by `superdocs/client.py`.

Do **not** commit `.env`.

Recommended `.gitignore` entries:

```gitignore
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
outputs/*
```

## Run tests

```powershell
pytest -v
```

The HTML extraction regression tests specifically cover:

- Underwriting Approval not being misclassified because a rule mentions "Loan Estimate".
- Table-cell boundaries being preserved.
- `Loan Terms` not being mistaken for the `Loan Term` field.
- `Applicants and Property` not being mistaken for a borrower value.
- The actual SuperDocs Closing Disclosure labels `Property` and `Escrowed Property Costs`.
- The seeded Closing Disclosure values remaining intact after the parser fixes.

## Run the app

```powershell
streamlit run app.py
```

Recommended demo sequence:

1. Upload the five Scenario A documents.
2. Confirm the shared SuperDocs session shows all five document types.
3. Confirm summary: **5 match / 1 tolerable / 2 curable / 0 unresolved**.
4. Open the rate, title-fee, and cash-to-close findings and show their evidence/rules.
5. Show that the correction request contains only rate and cash-to-close.
6. Use Search to locate a grounded value.
7. Ask a read-only chat question. If the router cannot answer an all-document query, choose a specific document; the workflow does not depend on the chat answer.
8. In Review, request a surgical edit such as changing `Executive Summary` to `Reconciliation Summary`.
9. Inspect the proposed change before approving it.
10. Approve, complete the job, and export the reviewed DOCX.

## API / operation behavior

The build intentionally keeps expensive operations bounded:

- 5 upload operations for the mortgage file.
- Deterministic extraction/reconciliation runs locally after upload.
- Search runs locally over processed HTML.
- Chat is user-triggered only.
- Review/edit operations are user-triggered only.

Uploaded document IDs and source HTML are reused within the Streamlit session instead of re-uploading for every reconciliation step.

## Known SuperDocs integration rough edges

1. Structured extraction through chat showed intermittent routing behavior, so chat is not used as the source of truth for reconciliation.
2. Pending Review changes may arrive either as a normal list or as a JSON-encoded string. `parse_pending_changes()` defensively handles both representations.
3. Large edit requests may produce a `continue_prompt`. The demo asks users to make smaller surgical edits rather than spending unbounded operations.

These failures are surfaced to the user; the build does not fabricate a successful result.

## Key files

```text
app.py
core/
  html_extraction.py
  extraction.py
  models.py
  normalize.py
  reconcile.py
  rules.py
  corrections.py
  memo.py
  workflow.py
superdocs/
  client.py
  parser.py
  polling.py
tests/
  test_html_extraction.py
  fixtures/
    closing_disclosure_superdocs.html
```

## Disclaimer

All sample borrower, property, lender, and transaction details are synthetic. This project is a software demonstration and does not provide legal, lending, compliance, or regulatory advice.
