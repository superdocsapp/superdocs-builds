# Crash-Resume Durability Demo

Built by **Ashutosh** for the SuperDocs engineering task, selected S2 crash-resume durability card.

This dependency-free proof runs the required failure at the hardest boundary:

1. a child process starts an async provider-shaped document job and checkpoints its SuperDocs-style
   session ID, job ID, original document, two proposals and audit event in SQLite;
2. the orchestrator persists approval of the first item while the sibling is still pending;
3. it kills that process with no graceful shutdown;
4. an entirely fresh Python process opens only the durable database, restores the saved identifiers,
   fetches and reconciles the durable provider job, observes the pending sibling, rejects it with
   feedback, and resumes the mixed decision batch;
5. the provider applies exactly one idempotent update and completes;
6. the recovered process exports a DOCX, reparses its ZIP/XML structure and proves that the accepted
   claim survived while the rejected claim did not; and
7. a second fresh recovery process replays the same checkpoint and proves zero duplicate logical
   effects.

## Run

```powershell
python demo.py
python -m pytest -q
```

The JSON proof must report `fresh_recovery_process=true`, restored session and job IDs, preserved first
decision, pending second decision after restart, both pre/post-crash audit events, a valid final export,
`provider_document_updates=1`, `duplicate_logical_effects=0`, and `resumed_status=COMPLETE`. Any failed
invariant makes the command exit non-zero.

## SuperDocs contract represented

The transport mirrors the exact durable operations used by the real integration: `get_job(job_id)`,
item-level `approve_change` with a stable idempotency key, and `export_document`. The offline transport
is deliberately deterministic so CI can kill an operating-system process on every run without a live
key or billed call. The state being recovered is not invented: local and provider records are distinct,
and reconciliation reads the provider record by the persisted job ID before any new decision is sent.

## Deliberate boundary

SQLite and a local provider double keep the demonstration small and repeatable. Multi-instance
production code should use PostgreSQL with the same unique-key and transactional-outbox invariants and
the real SuperDocs transport. An expired/missing provider job fails explicitly into manual recovery; the
demo never fabricates completion.

## Automation disclosure

Ashutosh used AI-assisted coding, research, and test orchestration while building
this candidate project. Ashutosh is the sole applicant and is responsible for
source verification, security decisions, final review, submission, demo, and
live discussion. AI-assisted tooling prepared this project and, on Ashutosh's
explicit instruction, opened its GitHub contribution. It did not contact
prospects, send email or bug reports, submit the application, or impersonate a
human.
