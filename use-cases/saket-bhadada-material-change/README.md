# Material-Change Analysis Between Versions

## Use Case

**Legal & Procurement** — Automated detection of substantive contractual
changes between two versions of an agreement.

## What it does

This tool helps **legal and procurement teams** quickly understand what
actually changed between two versions of a contract, without manually
redlining every clause. Given two versions of an agreement, it:

- Uploads both versions to SuperDocs
- Asks the AI to **separate substantive/material changes from pure
  formatting or stylistic edits**
- Identifies **which party each material change favors**, and why
  (liability shifts, indemnification scope, payment terms, etc.)
- Produces a list of concrete **pushback points** a reviewer on the
  disadvantaged side could raise during negotiation
- Exports the final analysis as a shareable document

The goal is to cut down the time a reviewer spends hunting for the clauses
that actually matter in a long redline.

## How it works

The script (`main.py`) makes exactly four calls to the SuperDocs API, in order:

1. **Upload** — sends both contract versions as documents
2. **Chat** — instructs the AI to run the material-change comparison
3. **Approve** — programmatically approves the returned findings
4. **Export** — exports the final analysis document

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# then fill in SUPERDOCS_API_KEY in .env
```

Drop two **synthetic or public** contract versions (never real, confidential
paperwork) into `sample_data/` as `contract_v1.txt` and `contract_v2.txt`,
then run:

```bash
python main.py
```

`SMALL_SAMPLE_MODE` and `MAX_OPERATIONS` in `.env` cap how many API calls the
script will make in a single run, so you don't burn through your API budget
while debugging.

## Known API quirks handled here

- **JSON-in-JSON:** the findings/changes payload sometimes comes back as a
  JSON-encoded string nested inside the response, so the script runs a
  second `json.loads()` pass on it.
- **Long processing times:** deep comparisons on large documents can take
  30 seconds to several minutes with no visible progress. The script polls
  patiently instead of timing out early.
- **Budget control:** `SMALL_SAMPLE_MODE` + `MAX_OPERATIONS` act as a hard
  cap on API calls during development to prevent runaway usage.

## SuperDocs API Steps

| Step | Endpoint | Purpose |
|------|----------|---------|
| 1 | `POST /documents/upload` | Upload both contract versions |
| 2 | `POST /chat` | Send comparison instruction |
| 3 | `POST /approve` | Approve the AI findings |
| 4 | `POST /export` | Export the final analysis |
