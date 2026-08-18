# Live Doc Agent (`live-doc-agent`)

> An intelligent synchronization agent that keeps engineering wikis and handbooks up-to-date with newly made decisions by generating **surgical section-level edits** via SuperDocs, guarded by an interactive **human approval gate**.

---

## 1. What It Does

When engineering policies or architectural decisions change, updating documentation with standard AI tools often rewrites entire pages, causing silent hallucinatory edits and destroying unchanged sections.

`live-doc-agent` reads the canonical wiki, uploads a snapshot to SuperDocs to propose targeted edits, strictly validates the proposal, presents the diff to a human reviewer for approval, and applies **only the approved surgical edits** back to the source wiki.

```text
Decision ──► Safety Filter ──► Fetch Wiki ──► SuperDocs Chat ──► Proposal Validation ──► Human Approval Gate ──► SuperDocs Approve ──► Optimistic Version Check ──► Deterministic Patch ──► Invariant Verification
```

---

## 2. Why SuperDocs?

* **Authoritative Source vs. AI Surface**: The external wiki (e.g., Nuclino) remains the authoritative source of truth. SuperDocs acts as the dedicated AI analysis and human review surface.
* **Granular Diffing**: SuperDocs analyzes document context against new decisions to propose surgical paragraph-level replacements rather than full-page rewrites.
* **Defensive Contract**: Safely handles SuperDocs response formats, including double-encoded/stringified JSON payloads.

---

## 3. The Core Invariant

```text
Before:
A
B  <-- stale paragraph
C
D

After:
A
B' <-- surgically updated
C
D
```

The patch engine mathematically enforces:
$$\text{unchanged\_sections}(\text{before}, \text{after}) == \text{all sections not explicitly approved}$$

---

## 4. Evaluator Quickstart (Zero Credentials)

Run the entire test suite and the interactive demo out of the box without any external API keys:

```bash
# 1. Run all automated tests
pytest -q

# 2. Run the deterministic evaluator demo
python -m live_doc_agent.cli demo
```

### Evaluator Demo Output:

```text
==================================================
 Live Doc Agent — Evaluator Demo (Zero-Credential)
==================================================

Decision:
  All deployments must now use the automated CI/CD pipeline.

Proposed changes:
  [1] Section: [Deployment]
      - Deployments happen manually.
      + Deployments must use the automated CI/CD pipeline.

Human Approval Gate:
  -> APPROVED

Result Status:
  APPLIED

Changed sections:
  - Deployment

Untouched sections:
  ✓ Authentication
  ✓ On-call

Document Version:
  1 → 2

==================================================
 Invariant Verified: Untouched sections preserved
==================================================
```

---

## 5. Running with Live Adapters

### Setup Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

```env
# SuperDocs API Configuration
SUPERDOCS_API_KEY=your-superdocs-api-key
SUPERDOCS_BASE_URL=https://api.superdocs.app/v1

# Wiki Host Configuration (Nuclino)
NUCLINO_API_KEY=your-nuclino-api-key
NUCLINO_BASE_URL=https://api.nuclino.com/v0
```

### Interactive CLI Mode

```bash
# Interactive review with [y]es / [n]o / [e]dit manual override:
python -m live_doc_agent.cli \
  --doc-id "handbook-1" \
  --decision "Starting August 18, production deployments will happen daily."

# Production mode with Nuclino:
python -m live_doc_agent.cli \
  --adapter nuclino \
  --doc-id "your-nuclino-item-id" \
  --decision "Incident acknowledgement SLA is now 15 minutes."
```

---

## 6. End-to-End Reproduction Example

This section shows a **complete reproducible run** against the real SuperDocs API using the built-in in-memory wiki (no Nuclino account required).

### Prerequisites

| Requirement | Where to get it |
|---|---|
| SuperDocs API key | [superdocs.app](https://superdocs.app) → Settings → API Keys |
| Python 3.11+ | `python --version` |
| Activated venv | `source .venv/bin/activate` |

### Step 1 — Clone & install

```bash
git clone https://github.com/Nishanth307/superdocs-builds.git
cd superdocs-builds/extensions/nishanth-prabhu/live-doc-agent

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Step 2 — Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

`.env` contents:

```env
SUPERDOCS_API_KEY=sk_your_key_here
SUPERDOCS_BASE_URL=https://api.superdocs.app/v1
```

### Step 3 — Run the zero-credential evaluator demo (no API keys needed)

```bash
python -m live_doc_agent.cli demo
```

Expected output:

```text
==================================================
 Live Doc Agent — Evaluator Demo (Zero-Credential)
==================================================

Decision:
  All deployments must now use the automated CI/CD pipeline.

Human Approval Gate:
  -> APPROVED

Proposed changes:
  [1] Section: [Deployment]
      - Deployments happen manually.
      + Deployments must use the automated CI/CD pipeline.
      Explanation: Switch from manual deployment to automated CI/CD pipeline.

Result Status:
  APPLIED

Changed sections:
  - Deployment

Untouched sections:
  ✓ Authentication
  ✓ On-call

Document Version:
  1 → 2

==================================================
 Invariant Verified: Untouched sections preserved
==================================================
```

### Step 4 — Run against the real SuperDocs API (auto-approve)

This makes a live call to SuperDocs and applies two surgical patches:

```bash
set -a && source .env && set +a

python -m live_doc_agent.cli \
  --doc-id "handbook-live" \
  --decision "Production deployments will now happen daily instead of every Friday. The incident acknowledgement SLA is now 15 minutes." \
  --auto-approve
```

Expected output:

```text
Running Live Doc Agent for document 'handbook-live'...

Result Status: APPLIED
Successfully applied 2 surgical patches.

--- Updated Document Content ---
# Engineering Handbook

## Deployment
Production deployments happen daily.

## Database
Production uses PostgreSQL on AWS RDS.

## Incident Response
The on-call engineer must acknowledge incidents within 15 minutes.
```

Note: `## Database` is **untouched** — the agent only edits sections affected by the decision.

### Step 5 — Interactive human approval gate

Run without `--auto-approve` to step through the approval UI:

```bash
set -a && source .env && set +a

python -m live_doc_agent.cli \
  --doc-id "handbook-interactive" \
  --decision "Production deployments will now happen weekly on Mondays. The on-call rotation is now biweekly."
```

The agent will pause at each proposed change and prompt:

```text
=======================================================
 Human Approval Gate: 2 Proposed Surgical Changes
 Document: 'Engineering Handbook' (Version 1)
=======================================================

[1/2] Section: [Deployment]
  Old Snippet : "Production deployments happen every Friday."
  New Snippet : "Production deployments happen every Monday."
  Explanation : Deployment schedule changed from Friday to Monday.
Approve this change? [y/n/e(dit)]: y
  -> Approved.

[2/2] Section: [Incident Response]
  Old Snippet : "The on-call engineer must acknowledge incidents within 30 minutes."
  New Snippet : "The on-call rotation is now biweekly."
  Explanation : On-call rotation frequency has changed.
Approve this change? [y/n/e(dit)]: n
  Reason for rejection (optional): not the right section
  -> Rejected.

Result Status: APPLIED
Successfully applied 1 surgical patches.
```

Approve, reject, or type `e` to provide your own replacement text for any change.

### Step 6 — Run the automated test suite

```bash
pytest -q
```

All 13 test files run in under 5 seconds with zero credentials.

---

## 7. Safety Guarantees & Edge Cases

| Scenario | Behavior / Status | Guarantee |
| :--- | :--- | :--- |
| **Relevant Decision** | `APPLIED` | Updates only stale paragraphs; unapproved sections remain byte-for-byte identical. |
| **Irrelevant Decision** | `NOOP` | No changes proposed; document left unmodified. |
| **Partial Approval (A/B/C)** | `APPLIED` | Approving A & C while rejecting B commits only A and C, leaving B untouched. |
| **Ambiguous / Missing Target** | `VALIDATION_FAILED` | Rejects proposals if target section is missing or target snippet matches 0 or >1 times. |
| **Duplicate Change IDs** | `VALIDATION_FAILED` | Rejects duplicate IDs returned by the model before entering the human approval gate. |
| **Concurrent Wiki Edit** | `CONFLICT` | Optimistic locking checks `contentVersion` before writing; aborts without overwriting remote collaborator edits. |
| **Prompt Injection Attempt** | `ERROR` | Filters adversarial instructions (e.g. `SYSTEM OVERRIDE`, `Ignore previous instructions`) before reaching the model. |
| **Idempotency** | `NOOP` on run 2 | Re-running the agent on an already synchronized document produces 0 modifications. |
| **External Service Failure** | `ERROR` | External API errors are caught and converted to structured `RunResult` without uncaught crashes. |

---

## 8. Limitations & Honest Engineering Choices

1. **Source of Truth**: The host wiki remains authoritative. SuperDocs is used for AI proposal generation and human review.
2. **Sequential Multi-Patch Application**: Patches are applied sequentially with optimistic version verification on each step. If a race condition occurs midway, the operation halts with `CONFLICT` and reports previously applied patches rather than silently clobbering.
3. **Defensive Filtering**: The regex-based prompt injection guard is a defensive first layer; critical policy isolation relies on strict structural validation of snippets and the human approval gate.

---

## 9. Repository Structure

```text
live-doc-agent/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/
│   └── live_doc_agent/
│       ├── __init__.py
│       ├── agent.py               # Main agent lifecycle orchestrator
│       ├── cli.py                 # Interactive human review CLI & demo runner
│       ├── models.py              # Data models & typed exceptions
│       ├── patcher.py             # Deterministic surgical patch engine & invariant verifier
│       ├── superdocs/
│       │   ├── __init__.py
│       │   └── client.py          # SuperDocs client with defensive JSON decoding
│       └── wiki/
│           ├── __init__.py
│           ├── base.py            # WikiAdapter ABC interface
│           ├── memory.py          # Fast in-memory adapter for zero-credential testing
│           └── nuclino.py         # Nuclino REST API adapter with 409 conflict handling
└── tests/
    ├── test_byte_for_byte.py          # Strict raw byte preservation (formatting, code blocks, tabs)
    ├── test_phase_c_evaluator_demo.py # Canonical evaluator demo acceptance contract
    ├── test_agent_lifecycle.py        # Phase B acceptance test, override text, default gate
    ├── test_surgical_edits.py         # Invariant verification & partial approval ABC pattern
    ├── test_proposal_validation.py    # Pre-gate validation (missing sections, ambiguity, duplicate IDs)
    ├── test_conflicts.py              # Optimistic locking & human-gate race condition aborts
    ├── test_external_failures.py      # Network/503/timeout error boundaries
    ├── test_noop.py                   # Irrelevant decision -> NOOP
    ├── test_prompt_injection.py       # Direct and disguised prompt injection defense
    ├── test_idempotency.py            # Double execution produces clean NOOP
    ├── test_superdocs_parsing.py      # Double-encoded JSON string decoding
    ├── test_nuclino_adapter.py        # Nuclino fetch, patch, and version gating
    └── test_end_to_end.py             # Full deterministic integration cycle
```

---

## License

MIT. Authored by Nishanth Prabhu for the SuperDocs Builds repository.
