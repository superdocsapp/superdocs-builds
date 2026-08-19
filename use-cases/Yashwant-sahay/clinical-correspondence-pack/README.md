# Clinical Correspondence Pack - SuperDocs MCP Demonstration

A demonstration project that uses the SuperDocs MCP API to generate a structured clinical correspondence pack from a completely fabricated encounter record.

> IMPORTANT: This project uses synthetic demonstration data only. It is not a real patient record, does not provide medical advice, and is not intended for use as a clinical decision-making or production healthcare system.

## Overview

This project demonstrates an end-to-end document-generation workflow for a clinical correspondence use case.

A fabricated outpatient encounter is supplied to SuperDocs through its MCP interface. The system asynchronously generates exactly four correspondence sections:

1. Referral Letter
2. Discharge Summary
3. Results Letter to Patient
4. Prior-Authorisation Letter

The generated document is validated locally against explicit requirements before a human reviewer is asked to approve the document for DOCX export.

The clinician signature is deliberately kept as:

**Pending human approval**

throughout the generated correspondence.

## Key Features

- Synthetic clinical encounter input
- SuperDocs MCP integration
- Asynchronous job submission
- Unique session handling
- Job polling with progress reporting
- Structured JSON-RPC communication
- Strict source-data constraints
- Local document validation
- Cardiology referral validation
- Outpatient follow-up validation
- Fabricated-data safety notice validation
- Pending human approval validation
- Human approval before DOCX export
- A4 portrait DOCX export
- Runtime job and result tracking

## Workflow

The application follows this workflow:

```text
synthetic_encounter.json
        |
        v
Load fabricated encounter
        |
        v
Build constrained correspondence instruction
        |
        v
SuperDocs MCP chat_async
        |
        v
Receive job_id
        |
        v
Poll get_job until completion
        |
        v
Extract generated document
        |
        v
Local validation
        |
        +---- Validation failed ----> Stop
        |
        v
Human approval prompt
        |
        +---- Rejected ----> Stop
        |
        v
SuperDocs export_document
        |
        v
DOCX export
