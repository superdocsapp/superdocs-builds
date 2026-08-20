# Numeric & Date Consistency Auditor

## SuperDocs Round 2 — Assigned Build

This project contains the focused **Numeric and Date Consistency Auditor** implementation extracted from the DocuCheck engineering project.

The auditor is designed for financial/legal documents and detects inconsistencies in numbers and dates while preserving source evidence for review.

## What it does

### Numeric consistency

- Revenue / expense / profit arithmetic
- Totals and subtotals
- Percentage and margin consistency
- Repeated numeric values
- Numeric normalization
- Cross-document numeric conflicts
- Table-aware arithmetic where parsed tables are available

### Date consistency

- Invalid or reversed date ranges
- Deadline/date relationships
- Conflicting date values
- Cross-document date inconsistencies

### Evidence

Findings contain explanations and citations pointing back to the parsed source block/page/section where the value was found.

The implementation deliberately uses deterministic code for arithmetic and date comparison rather than asking an LLM to perform basic calculations.

## Architecture

```text
Document
   |
   v
Parser
   |
   v
Deterministic Fact Extraction
   |
   +----------------------+
   |                      |
   v                      v
Numeric Engine        Date Engine
   |                      |
   +----------+-----------+
              |
              v
       Conflict Detection
              |
              v
       Findings + Evidence
```

## Example

Given:

```text
Revenue: $5,000,000
Expenses: $3,000,000
Net Income: $2,500,000
```

the arithmetic engine calculates:

```text
Expected Net Income = $5,000,000 - $3,000,000
                   = $2,000,000
```

and produces a finding for the $500,000 difference.

For dates:

```text
Effective Date: 20 August 2026
Expiry Date: 10 August 2026
```

the date engine flags the invalid ordering.

## Demo data

`backend/demo_data/` contains synthetic documents with intentionally planted inconsistencies.

No confidential or personal documents are used.

## Running the focused auditor tests

From the `backend` directory:

```bash
pip install -r requirements.txt
pytest tests/test_auditor_demo.py -q
```

The demo test exercises:

```text
parse
  -> deterministic fact extraction
  -> arithmetic audit
  -> date audit
  -> cited findings
```

## Important submission note

This folder represents the **auditor implementation already present in the DocuCheck project**.

The original uploaded repository did not contain a separate SuperDocs-facing adapter/PR package. If the SuperDocs submission requires an API/MCP integration and public `superdocs-builds` PR, that integration still needs to be added around this auditor.

## Design principle

Use deterministic validation for facts that can be mathematically or chronologically verified. Use an LLM only for tasks where semantic reasoning is useful, such as enrichment/explanation.

## License / submission

This code is being prepared as part of the SuperDocs Round 2 engineering task.

