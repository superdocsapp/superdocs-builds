# Collective Agreement Redliner

Built for SuperDocs Round 2, Task 2 (assigned build). Redlines a collective
bargaining agreement against each side's position, tracking every open item
across many negotiation rounds.


## What this is

A domain-specific tool built ON SuperDocs (never a version OF SuperDocs — the
whole editing/AI engine is theirs, this is the labour-relations layer on top):

1. Load a CBA draft as the working document, and each side's position paper
   (union, employer) as read-only reference attachments.
2. Run a **redline round**: ask SuperDocs to propose changes reconciling the
   draft against both positions, human-in-the-loop (`approval_mode:
   ask_every_time`) so nothing lands without review.
3. Review each proposed clause change, approve or reject with feedback.
4. Repeat across rounds as positions evolve — the **open-items tracker**
   is the actual engineering here: it stays accurate as items get raised,
   contested, reconciled, or re-opened across many rounds, without drifting
   from what SuperDocs' own job history says actually happened.
5. Export the current agreement state at any point.

## Why this architecture — a thin layer, not a rebuild

SuperDocs already persists a full audit trail per session
(`GET /v1/sessions/{id}/jobs` — every round, every proposed change, every
decision). Building a second, parallel change-tracking system from scratch
would duplicate what the platform already guarantees, and risk drifting out
of sync with it. Instead:

- **SuperDocs owns**: the document, the AI reasoning, the diff generation,
  the approve/deny mechanics, the per-job history.
- **We own**: the domain semantics SuperDocs has no way to know — which
  side's position drove a given proposal, whether a specific clause is
  still contested *across* rounds (SuperDocs' history is job-scoped, we
  need clause-scoped), and the redline-specific review UI.

Cost of this choice: we're coupled to SuperDocs' job-history shape staying
stable, and to `chunk_id` remaining a stable identifier for a clause across
a session's lifetime (it is — see the API reference). Benefit: a
meaningfully smaller, more reliable build than re-deriving change tracking,
in a 2-day window where that trade-off matters.

## Stack

FastAPI + SQLite (not Postgres — no vector search needed here, and Task 1's
biggest recurring bug class was async-engine-per-event-loop issues; this
build uses sync SQLAlchemy deliberately to avoid that class of bug
entirely). React for the review UI. No self-hosted MCP server — the
assigned card's surfaces (Review, Multi-document, export) are all REST-
shaped; the brief's own guidance is build against the four core calls
first, everything else is optional depth, and an S3 card doesn't need more
surface area than the card asks for.

## Getting started

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # add your SuperDocs API key
python scripts/init_db.py
python scripts/seed_documents.py   # synthetic CBA + two position papers
uvicorn app.main:app --reload
```

```bash
cd backend && source .venv/bin/activate && pytest tests/ -v
```

Offline by default — tests mock `superdocs_client` (see `tests/README.md`),
same "real tests, no live key needed" discipline as Task 1.

## Repo map

See `CLAUDE.md` for the working agreement and `PROGRESS.md` for the current
phase and decision log — same pattern as Task 1, proven to work well there.

## What's cut, and why

(Filled in as the build progresses — see PROGRESS.md.)
