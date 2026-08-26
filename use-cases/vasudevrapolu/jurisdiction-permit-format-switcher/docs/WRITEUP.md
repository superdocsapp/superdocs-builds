# Engineer Round 2 — Write-up

## What I built

I built two connected document workflows. The first is an agentic document analyst: it ingests related documents, extracts facts, detects conflicts, checks user-supplied rules, prepares a grounded deliverable, and stops for explicit human decisions before commit. The second is the assigned Jurisdiction Permit-Format Switcher for a solar permitting coordinator.

## Why this architecture

The brief's preferred stack is Python/FastAPI, an agent orchestration framework, PostgreSQL/vector search, React and MCP. I followed that shape so the system is directly comparable to the role. The workflow is staged rather than a single prompt because the important behaviors are visible decisions, recovery, human gating and grounded output.

For the permit switcher, jurisdiction differences live in configuration. Adding a new authority should add data rather than another branch in the generator. This is deliberately important because a permitting product becomes unmaintainable if every new authority requires code changes.

## What is proven locally

- Five automated tests pass without a live key.
- Two synthetic jurisdictions produce different form sets and packet structures from the same project record.
- Missing license data becomes an explicit blocking gap.
- Instruction-like text in a source document is treated as data, not a command.
- Conflicting source facts stop at the review stage.
- The machine interface exposes the same core workflow and approval boundary.

## Live integration boundary

The SuperDocs API adapter is server-side and uses the documented HTML-in/HTML-out contract. A configured key enables the live path. The local demo intentionally falls back to a deterministic adapter when no key is available; the UI says which mode is active.

## What I cut

I did not implement authoritative real-world permit rules or live government submission. That would create false confidence without verified authority documents. I also kept the first retrieval layer small rather than pretending a production-grade semantic index exists when the demo data is tiny. The PostgreSQL/pgvector dependency and repository boundary are present so the retrieval layer can be expanded with real permitted source documents.

## Honest limitations

- The sample jurisdictions are synthetic and not legal/compliance advice.
- A live SuperDocs account/key is needed to demonstrate the external round-trip.
- The local compatibility path is intentionally deterministic.
- Production deployment would add authentication, object storage, migrations, audit retention, stronger document parsing and a full vector retrieval index.

## Measurement plan

The key measurements are stage latency, resume time after interruption, number of facts with source provenance, number of conflicts surfaced, approval/rejection counts, and packet completeness against the jurisdiction configuration. The method should be recorded before reporting results.
