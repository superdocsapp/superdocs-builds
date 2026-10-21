# SuperDocs Builds: DocIntel

A combined implementation of the two assigned SuperDocs hiring-round builds:

1. **Tariff Classification Memo Builder**
2. **Screenplay Formatter**

Both builds are implemented inside the same application and share the same workflow, review, evidence, persistence, and SuperDocs integration infrastructure.

> **DocIntel is the name of the combined implementation in this submission, not a separate product being submitted independently.**

---

## Submission Overview

This repository contains my implementation for the assigned SuperDocs builds.

The goal was not simply to generate documents with an LLM. I built the workflows around the actual document lifecycle:

```text
Source Documents
      ↓
Document Understanding
      ↓
Structured Facts / Parsing
      ↓
Evidence & Knowledge Retrieval
      ↓
Workflow Reasoning
      ↓
Generated / Proposed Document Changes
      ↓
Quality & Grounding Checks
      ↓
SuperDocs Editing
      ↓
Human Review
      ↓
Approval
      ↓
DOCX / PDF Export
````

The two assigned builds use different domain-specific workflows while sharing the underlying infrastructure.

---

# Assigned Builds

## 1. Tariff Classification Memo Builder

### Objective

Build a workflow that takes product information and supporting customs material and produces a defensible tariff-classification memorandum.

### Inputs

The workflow can work with:

* Product specification documents
* Product photographs
* Customs / tariff rulings
* Supporting reference documents

### Workflow

```text
Product Specification
        +
Product Images
        +
Customs Rulings
        ↓
Document Discovery
        ↓
Product Facts
        ↓
Ruling Facts
        ↓
Knowledge / Evidence Retrieval
        ↓
Classification Analysis
        ↓
Alternative Classification Analysis
        ↓
Memo Generation
        ↓
Grounding / Quality Checks
        ↓
SuperDocs Document Editing
        ↓
Human Review
        ↓
Approval
        ↓
DOCX / PDF Export
```

### Generated Memo

The final memo can contain structured sections such as:

* Executive Summary
* Product Overview
* Product Description
* Technical Characteristics
* Material / Physical Composition
* Product Images
* Applicable Classification Rules
* Relevant Previous Rulings
* Classification Analysis
* Alternative Classifications Considered
* Reasons for Rejecting Alternatives
* Supporting Evidence
* Final Classification Recommendation

The generated memo is designed to connect its reasoning back to the source material rather than treating an LLM response as the authority.

### Tariff-specific approach

The workflow separates:

```text
Source Material
      ↓
Facts
      ↓
Evidence
      ↓
Claims
      ↓
Classification Reasoning
      ↓
Final Recommendation
```

This makes the classification reasoning inspectable and gives the reviewer visibility into why a classification was recommended.

---

# 2. Screenplay Formatter

## Objective

Build a document workflow that takes loosely formatted screenplay content and converts it into properly structured screenplay formatting while preserving the actual writing.

### Inputs

* Raw screenplay documents
* Loosely formatted screenplay text
* Fountain-style screenplay content where applicable

### Workflow

```text
Raw Screenplay
      ↓
Document Parsing
      ↓
Scene / Element Detection
      ↓
Structure Classification
      ↓
Formatting Rules
      ↓
Proposed Formatting Changes
      ↓
Content-Difference Validation
      ↓
Human Review
      ↓
Approval
      ↓
DOCX / PDF Export
```

### Supported screenplay elements

* Scene headings
* Action
* Character cues
* Dialogue
* Parentheticals
* Transitions

### Core principle

The formatter is intentionally designed to change:

**formatting, not writing.**

The original screenplay content is treated as source material. Formatting operations are applied to the structure of the document rather than rewriting the author's content.

The workflow also performs content-drift checks so that formatting changes do not silently become writing changes.

---

# Shared SuperDocs Workflow

Although the two assigned builds solve different problems, they use a shared document workflow architecture.

```text
                    USER
                      │
                      ▼
              DOCINTEL APPLICATION
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
   TARIFF WORKFLOW       SCREENPLAY WORKFLOW
          │                       │
          └───────────┬───────────┘
                      ▼
             SHARED SERVICES
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
    Evidence       Workflow       Review
    Retrieval      State          State
        │             │             │
        └─────────────┼─────────────┘
                      ▼
               SuperDocs
                      │
          Upload → Edit → Review
                      │
                      ▼
                  Approval
                      │
                      ▼
                DOCX / PDF
```

The important distinction is:

### My application handles

* Workflow orchestration
* Stage execution
* Persistent run state
* Document discovery
* Domain reasoning
* Evidence retrieval
* Claims
* Quality checks
* Human review state
* Knowledge
* Lineage
* Recovery
* Resume / replay behavior
* Run history

### SuperDocs handles

* Document upload/session
* In-document editing
* Proposed document changes
* Approval operations
* Final document export

This keeps the implementation aligned with the SuperDocs document-editing model rather than attempting to build a separate document editor.

---

# Additional Engineering I Implemented

Beyond the core assigned workflows, I built several pieces of workflow infrastructure to make the implementations behave like reliable document agents rather than simple sequential scripts.

These were additional engineering decisions made during implementation.

## 1. Persistent workflow state

Each workflow is represented as a sequence of observable stages.

For example:

```text
Upload
   ↓
Discover Documents
   ↓
Load Product Content
   ↓
Load Ruling Content
   ↓
Knowledge Retrieval
   ↓
Product Facts
   ↓
Ruling Facts
   ↓
Reconcile Documents
   ↓
Evidence Retrieval
   ↓
Memo Generation
   ↓
SuperDocs Editing
   ↓
Review
   ↓
Approval
   ↓
Export
```

The state of the run is persisted instead of existing only inside a single request.

This allows the application to know:

* Which stages completed
* Which stage is running
* Which stage failed
* Which checkpoint can be recovered
* What evidence was retrieved
* What review decisions were made
* What outputs were generated

---

# 2. Kill, Resume and Replay

I implemented explicit workflow lifecycle controls.

### Kill / Cancel

A running workflow can be stopped intentionally.

The completed stages remain recorded.

### Resume

If a workflow was interrupted after reaching a valid checkpoint, it can continue from the unfinished portion rather than starting over.

```text
Stage 1 ✓
Stage 2 ✓
Stage 3 ✓
Stage 4 ✓
Stage 5 ✕  ← interrupted
Stage 6
Stage 7
```

Resume:

```text
Stage 1 ✓
Stage 2 ✓
Stage 3 ✓
Stage 4 ✓
Stage 5 → continue
Stage 6
Stage 7
```

### Replay

Replay is intentionally different from resume.

Replay starts the workflow again from the beginning.

The UI therefore distinguishes between:

* **Resume Run** for recoverable interrupted runs
* **Replay Run** for starting the workflow again

The action selection is based on persisted run state and checkpoint availability rather than simply checking whether a run is not completed.

---

# 3. Idempotent Resume Behavior

Resuming a workflow should not duplicate work that has already completed successfully.

The workflow runner therefore restores the latest valid checkpoint and skips completed stages where appropriate.

This was particularly important for long-running document workflows because restarting every stage after an interruption would unnecessarily repeat:

* Document processing
* Retrieval
* LLM calls
* Evidence generation
* Document mutations

---

# 4. Concurrent Workflow Isolation

The workflow system supports multiple runs at the same time.

Each run maintains its own:

* Run ID
* Workspace
* Stage state
* Checkpoints
* Evidence
* Claims
* Review state
* Outputs
* Lineage

This prevents one workflow from accidentally consuming another workflow's intermediate state.

Concurrent runs were specifically tested during the implementation.

---

# 5. Transient Failure Recovery

External AI and document services can fail temporarily.

For example, concurrent workflow testing exposed a `429` response during memo generation, indicating an external rate-limit condition.

The workflow state remained recoverable and the affected workflow was able to continue once execution capacity became available.

The system therefore treats transient external failures differently from terminal workflow completion.

---

# 6. Human-in-the-loop review

The workflows do not treat generated output as automatically final.

The system provides a review stage where proposed changes and generated results can be inspected before approval.

For Tariff:

```text
Generated reasoning
       ↓
Claims / evidence
       ↓
Proposed memo
       ↓
Human review
       ↓
Approval
```

For Screenplay:

```text
Parsed screenplay elements
       ↓
Formatting changes
       ↓
Content validation
       ↓
Human review
       ↓
Approval
```

The final document is therefore the result of an explicit approval path.

---

# 7. Evidence, Claims and Lineage

The implementation maintains relationships between source material and generated reasoning.

```text
Source Documents
       ↓
Facts
       ↓
Evidence
       ↓
Claims
       ↓
Analysis
       ↓
Generated Document
       ↓
Human Decision
       ↓
Final Artifact
```

This allows the workflow to answer questions such as:

* Where did this fact come from?
* What evidence supports this claim?
* Which documents were used?
* What reasoning led to the recommendation?
* What was reviewed?
* What was approved?
* Which output was generated from the run?

This is especially important for the Tariff workflow, where the final classification needs to be defensible rather than merely plausible.

---

# 8. Knowledge Reuse

The implementation also includes a knowledge layer that allows useful information from completed work to be retained and retrieved in later workflows.

The purpose is not to blindly reuse previous answers.

Instead, previously derived information can become additional retrieval context that can be evaluated alongside the current source documents.

---

# 9. Quality and Grounding Checks

The workflows include quality gates before final output.

The checks are intended to catch issues such as:

* Unsupported claims
* Missing evidence
* Invalid structure
* Content drift
* Incomplete workflow state
* Invalid document output

The exact checks differ between the Tariff and Screenplay workflows because the two domains have different correctness requirements.

---

# 10. Observable Workflow Execution

Rather than hiding the entire operation behind a single loading indicator, the UI exposes workflow stages.

A run can show:

```text
✓ Upload to SuperDocs
✓ Discover Documents
✓ Load Product Content
✓ Load Ruling Content
✓ Knowledge Retrieval
✓ Product Facts
✓ Ruling Facts
✓ Reconcile Documents
→ Evidence Retrieval
○ Memo Generation
○ SuperDocs Editing
○ Review
○ Export
```

This makes long-running document operations understandable to the user.

---

# Implementation Approach

The overall implementation follows a few principles.

## Source-first

Source documents are the starting point for reasoning.

The model does not receive authority simply because it generated an answer.

---

## Structured intermediate state

Important information is represented as structured workflow state rather than being passed between stages only as free-form text.

---

## Evidence before conclusion

For the Tariff workflow, reasoning is grounded in:

```text
Product facts
+
Ruling facts
+
Retrieved evidence
+
Classification rules
      ↓
Classification reasoning
```

---

## Formatting instead of rewriting

For Screenplay, the workflow is deliberately constrained to document structure and formatting.

The author's actual writing should remain unchanged.

---

## Human approval before finalization

Generated or proposed document changes are not treated as final until they pass through the review/approval path.

---

## Persistent recovery

Workflow progress is persisted so that interruption does not automatically mean starting again from zero.

---

## Separation between workflow intelligence and document editing

The application performs the reasoning and orchestration.

SuperDocs performs the document mutation and export operations.

---

# SuperDocs Integration

The implementation uses the SuperDocs document surface for the document operations required by the builds.

The core flow is:

```text
1. Upload document
        ↓
2. Send document/edit instruction
        ↓
3. Inspect proposed changes
        ↓
4. Review / approve
        ↓
5. Export final document
```

The integration is used by both assigned builds.

### Tariff

SuperDocs is used for:

* Source document handling
* Memo editing
* Proposed changes
* Review
* Final DOCX/PDF export

### Screenplay

SuperDocs is used for:

* Source document handling
* Formatting instructions
* Proposed formatting changes
* Review
* Final document export

---

# Architecture

The implementation is organized around a shared workflow engine with two domain-specific workflow implementations.

```text
                         USER
                           │
                           ▼
                 React + TypeScript UI
                           │
                           ▼
                      FastAPI API
                           │
                           ▼
                Workflow Orchestration
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       Tariff Workflow          Screenplay Workflow
              │                         │
              └────────────┬────────────┘
                           ▼
              Shared Workflow Services
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      Retrieval         Evidence         Quality
      / Knowledge       / Claims         Gates
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                     Human Review
                           │
                           ▼
                    SuperDocs API
                           │
                           ▼
                    DOCX / PDF Export
                           │
                    ┌──────┴──────┐
                    ▼             ▼
                Knowledge      Lineage
```

---

# Technology

### Backend

* Python
* FastAPI
* LangGraph

### Database

* PostgreSQL
* pgvector

### Frontend

* React
* TypeScript
* Vite

### AI / Retrieval

* Configurable LLM provider layer
* Structured retrieval
* Evidence-backed generation

### Document layer

* SuperDocs API / MCP surface

### Testing

* Pytest
* Vitest

---

# Repository Structure

The public submission intentionally contains only the files necessary to understand, run, and evaluate the assigned builds.

```text
docintel/
│
├── backend/
│   ├── api/
│   ├── core/
│   ├── integrations/
│   │   └── superdocs/
│   ├── modules/
│   │   ├── tariff/
│   │   └── screenplay/
│   ├── models/
│   ├── repositories/
│   ├── services/
│   ├── tests/
│   └── ...
│
├── frontend/
│   └── src/
│       ├── features/
│       │   ├── tariff/
│       │   ├── screenplay/
│       │   ├── reviews/
│       │   ├── workflows/
│       │   ├── knowledge/
│       │   └── lineage/
│       └── shared/
│
├── examples/
│   ├── tariff/
│   └── screenplay/
│
├── screenshots/
│   ├── tariff/
│   └── screenplay/
│
├── docs/
│
├── .env.example
├── .gitignore
└── requirements.txt
```

Runtime data, generated storage, temporary exports, local logs, credentials, and development artifacts are intentionally excluded from the public submission.

---

# Testing & Verification

The implementation was tested at both the domain-workflow and shared-infrastructure levels.

## Tariff

The Tariff implementation was verified against its automated regression suite, including the workflow's document processing, reasoning, evidence, memo generation, and related behavior.

The final audit covered **100+ Tariff tests**.

---

## Screenplay

The Screenplay implementation was verified against its automated regression suite, including parsing, formatting, validation, content preservation, and workflow behavior.

The final audit covered **80+ Screenplay tests**.

---

## Workflow behavior

Additional testing covered:

* Workflow execution
* Stage persistence
* Kill/cancel
* Resume
* Replay
* Checkpoint recovery
* Failed/interrupted runs
* Concurrent runs
* Review state
* Run action selection
* Stage-level UI state
* Transient external failures

---

# Assigned Work vs Additional Implementation

One of the important distinctions in this submission is between what was directly required by the assigned builds and what I added while implementing them.

## Assigned

### Build 1

**Tariff Classification Memo Builder**

The core requirement was to process product information, supporting material and rulings into a grounded classification memorandum with appropriate reasoning, evidence and document output.

### Build 2

**Screenplay Formatter**

The core requirement was to take screenplay material, apply proper screenplay formatting and preserve the actual writing.

### SuperDocs integration

Both builds needed to use the SuperDocs document surface for document interaction and output rather than implementing an unrelated document editor.

---

# Additional Engineering I Added

The following were implementation decisions and extensions I built around the assigned workflows:

* Persistent multi-stage workflow state
* Checkpoint-based recovery
* Kill/cancel controls
* Resume from unfinished stages
* Replay from the beginning
* Dynamic Resume vs Replay action selection
* Idempotent stage execution
* Concurrent run isolation
* Retry / transient failure handling
* Stage-level execution visibility
* Evidence tracking
* Claim tracking
* Knowledge reuse
* Lineage tracking
* Human review state
* Quality gates
* Content-drift validation for screenplay formatting
* Run lifecycle state management
* Review and approval state management
* Structured workflow history

These additions were driven by the goal of making the assigned builds behave as reliable, observable document workflows rather than simple one-shot AI generation scripts.

---

# Submission Artifacts

The repository is accompanied by supporting submission material demonstrating the implementation and its architecture.

## Architecture

A production-formatted system architecture diagram shows the relationship between:

* User
* Application UI
* API
* Workflow orchestration
* Tariff workflow
* Screenplay workflow
* Retrieval/evidence
* Persistent state
* SuperDocs
* Final artifacts

## Workflow documentation

Supporting workflow documentation describes the lifecycle from source document through reasoning, review, approval and final document export.

## Demo

The demo focuses on the actual assigned builds and shows the workflows running inside the application.

---

# Demo Video

**Demo:**
[https://youtu.be/C2Q-3mjElbl](https://youtu.be/C2Q-3mjElbl)

The approximately three-minute demonstration covers the actual implementation and focuses on:

1. Tariff Classification workflow
2. Screenplay Formatting workflow
3. Workflow execution
4. Evidence / reasoning
5. SuperDocs document editing
6. Human review
7. Approval
8. Final document output
9. Workflow controls and recovery behavior

---

# Running Locally

## Requirements

* Python 3.12+
* Node.js 18+
* npm
* PostgreSQL 14+
* pgvector

For live workflow execution, the application also requires:

* An LLM provider API key
* A SuperDocs API key

---

## Environment Variables

The public repository does **not** contain secrets.

Create a local `.env` file from the provided example or configure the required variables locally.

Example:

```env
DATABASE_URL=postgresql://postgres:your-password@localhost:5432/docintel

SECRET_KEY=your-development-secret

LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key

SUPERDOCS_API_KEY=your-superdocs-api-key
SUPERDOCS_API_URL=https://api.superdocs.app

STORAGE_PATH=./storage
```

Never commit:

* API keys
* Tokens
* Passwords
* `.env`
* Private credentials
* Private source documents

---

## Backend

```bash
cd backend

pip install -r ../requirements.txt

alembic upgrade head

python run.py
```

The API runs on:

```text
http://localhost:8000
```

API documentation:

```text
http://localhost:8000/docs
```

---

## Frontend

```bash
cd frontend

npm install

npm run dev
```

---

# Running Tests

## Tariff

```bash
python -m pytest backend/tests/unit/modules/tariff -v
```

## Screenplay

```bash
python -m pytest backend/tests/unit/screenplay -v
```

## Shared services

```bash
python -m pytest \
  backend/tests/unit/services \
  backend/tests/unit/storage \
  backend/tests/unit/repositories \
  -v
```

## Frontend

```bash
cd frontend
npm test
```

The public repository should be evaluated using the automated tests and the included demonstration fixtures. Live AI and SuperDocs operations require the appropriate local credentials.

---

# Example Materials

The public copy can include synthetic or demonstration materials for showing the assigned workflows without exposing private source documents.

## Tariff

```text
examples/tariff/
├── product specification
├── customs ruling
├── product image
├── generated memo
└── README
```

## Screenplay

```text
examples/screenplay/
├── raw screenplay
├── formatted screenplay
├── Fountain representation
├── example proposals
└── README
```

---

# What This Submission Demonstrates

The implementation demonstrates two different document problems using a common workflow architecture.

### Tariff demonstrates

* Multi-document reasoning
* Product fact extraction
* Ruling analysis
* Evidence retrieval
* Classification reasoning
* Alternative classification analysis
* Grounded memo generation
* Human review
* SuperDocs editing
* Final document export

### Screenplay demonstrates

* Document parsing
* Structural screenplay understanding
* Element classification
* Industry-oriented formatting
* Content preservation
* Formatting validation
* Human review
* SuperDocs editing
* Final document export

### Shared implementation demonstrates

* Agentic workflow orchestration
* Persistent state
* Checkpoints
* Recovery
* Resume
* Replay
* Concurrent execution
* Evidence and claims
* Human-in-the-loop review
* Quality gates
* Lineage
* Knowledge reuse
* Observable workflow execution

---

# Design Decisions

## Grounded reasoning

Generated reasoning should be supported by available source material and retrieved evidence.

## Human control

The system proposes and prepares document changes, but the final document passes through an explicit review and approval path.

## Persistent execution

Long-running document workflows should survive interruption without unnecessarily repeating completed work.

## Recoverability

A cancelled or interrupted workflow with a valid checkpoint should be resumable.

## Replayability

Replay is intentionally separate from resume and represents a fresh execution from the beginning.

## Content preservation

The Screenplay Formatter should improve formatting without silently rewriting the screenplay.

## Clear ownership

The application owns workflow intelligence and state.

SuperDocs owns document editing and export.

---

# Known Boundaries

This submission is intentionally focused on the two assigned SuperDocs builds.

It is not intended to be a general-purpose document management platform.

Some workflow capabilities depend on external services:

* Live AI generation requires an LLM provider.
* SuperDocs document operations require SuperDocs credentials.
* Full application execution requires PostgreSQL.
* Vector retrieval requires pgvector.

The public repository contains no production secrets.

---

# Submission Scope

This repository is submitted as **one combined SuperDocs build** because both assigned builds were implemented inside the same application and share substantial infrastructure.

### Assigned Build 1

**Tariff Classification Memo Builder**

### Assigned Build 2

**Screenplay Formatter**

The shared implementation provides the workflow orchestration, persistence, evidence, review, recovery, SuperDocs integration, and export capabilities required to support both.

---

# Attribution

Built by **Anurag Jena** as part of the SuperDocs Engineer Task.

Development was performed using AI-assisted engineering alongside direct implementation, testing, debugging, workflow design, and product decisions.

Built on the public SuperDocs document/API surface.

---

# License

MIT