# LineCard

LineCard turns a long OEM manual into a reviewed two-page operator card and independently proves that its critical values, safety instructions, and page citations still match the source before allowing export.

It is for operators, maintenance leads, and safety reviewers who need a short job aid beside a machine without treating a generated summary as the authority. The card remains subordinate to the OEM manual and site procedures; LineCard does not certify machine or procedure safety.

## The safety invariant

SuperDocs can propose edits; LineCard refuses to release an operator card unless every critical claim still matches the manual. Unknown or ambiguous proposal targets, altered values, missing safety wording, dropped steps, unsupported numbers, wrong page citations, hostile markup, and impossible page budgets fail closed.

## Reviewer quick path

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
cd frontend && npm ci && cd ..
make check
make run
```

Open `http://127.0.0.1:8877` after `make run`. The served review UI uses the
same FastAPI endpoints that enforce evidence selection, source-lock
verification, PDF postflight, and download gating. The offline path uses
synthetic data and consumes zero SuperDocs AI operations.

## What is demonstrated

- A synthetic 400-page LC-100 manual, task-specific retrieval across separated sections, and exact `24 N·m ± 2 N·m` evidence with a PDF page pointer.
- A deterministic two-page card with all required safety, procedure, restart, citation, and flow-diagram content.
- Sabotage blocking for `26 N·m`, missing safety, unsupported numbers, wrong citations, manual-target edits, and hostile/prompt-injection content.
- A materially different 60-page AX-200 manual, two retrieval channels (local SQLite/FTS5 plus the SuperDocs semantic staging channel), and an isolated three-card batch manifest.
- Durable SQLite jobs, outbox/idempotency, worker lease fencing, review decisions, recovery, budget/sample gates, exact-HTML export, PDF postflight, accessibility, and normalized error handling.

## Architecture and evidence model

Local PDF ingestion freezes bytes, hash, pages, spans, and an immutable evidence ledger. FTS5 retrieval produces page-aware candidates; the SuperDocs semantic channel is reconciled into canonical evidence records only when direct synchronized chunk identity, document identity, old content, and base version agree. A typed card/staging plan then feeds the explicit human-review boundary, deterministic composition, graph/SVG rendering, two-page solver, independent verifier, exact-HTML export, and PDF postflight.

See [docs/architecture.md](docs/architecture.md), [docs/final-audit.md](docs/final-audit.md), [docs/evaluation.md](docs/evaluation.md), and [docs/safety-invariants.md](docs/safety-invariants.md).

## SuperDocs integration and known limitation

M0 live contract behavior and M4 image upload/export proof are recorded. After parsing the documented `document_sync.content` payload correctly, bounded M1 checks still found zero direct proposal-to-chunk matches: a read-only recovery saw 8 synchronized chunks and 6 proposal targets, and a fresh live run saw 8 synchronized chunks and 31 proposal targets. LineCard made no approval decision and attempted no export. This confirmed provider contract defect is documented in [docs/superdocs-live-bug-report.md](docs/superdocs-live-bug-report.md). No fuzzy matching or undocumented Mermaid wire attributes are used.

## Artifacts and status

The public-safe reviewer set is in [examples/](examples/) and [fixtures/generated/](fixtures/generated/); generated metrics and batch artifacts are described in [docs/evaluation.md](docs/evaluation.md). Frozen acceptance status: 27 rows total; 19 `OFFLINE_VERIFIED`, 6 `LIVE_VERIFIED`, 2 `BLOCKED_REAL_DEFECT`, 0 `TODO`, 0 `IMPLEMENTED`. The two blocked rows are intentionally not green.

## Demo and privacy

Follow the three-minute [demo script](docs/demo-script.md); do not present a fake live approval sequence. Only synthetic/public-safe fixtures belong in the repository. `.env`, credentials, signed URLs, cookies, provider IDs, raw live payloads, and local diagnostics are ignored or sanitized. See [docs/public-safety-checklist.md](docs/public-safety-checklist.md).

## Submission documents

[Handoff](docs/handoff.md) · [Evaluation](docs/evaluation.md) · [Architecture](docs/architecture.md) · [Task 3](docs/task3-buyers-use-cases.md) · [Task 4](docs/task4-writeup.md) · [PR description](docs/pr-description.md) · [Checklist](docs/submission-checklist.md)
