# Collective Agreement Redliner

Redlines a collective bargaining agreement against each side's position, tracking every
open item accurately across many negotiation rounds.

Built **on** SuperDocs — the editing engine, the AI reasoning, the diff generation and the
approve/deny mechanics are all theirs. This is the labour-relations layer on top.

![Review round: proposed clause changes as diff chips, each independently approvable](docs/screenshot-round.png)

**Demo video:** _(link)_

---

## What it does

Labour negotiations run in rounds. A draft agreement moves back and forth, each side files
a position, clauses get contested, reconciled, and re-opened, and the thing that actually
matters — which items are still open — drifts out of sync with the document almost
immediately.

1. Load a CBA draft as the working document, and each side's position paper (union,
   employer) as read-only reference attachments.
2. Run a **redline round**: SuperDocs proposes changes reconciling the draft against both
   positions, with `approval_mode: ask_every_time` so nothing lands unreviewed.
3. Review each proposed clause change as a diff chip — approve or reject item by item.
4. Repeat across rounds as positions evolve. The **open-items tracker** stays accurate.
5. Export the current agreement state at any point.

## What SuperDocs features it uses

- **Multi-document sessions** — the CBA as the editable document, union and employer
  position papers as attachments (`upload_document`, `upload_attachment`)
- **Chat editing with human-in-the-loop review** — `approval_mode: ask_every_time`
- **Per-item approve/reject** on proposed changes, batched per round
- **Export** to `.docx`
- **Job history** — `GET /v1/sessions/{id}/jobs`, which is the load-bearing one; see below

---

## The actual engineering: reconciliation, not duplication

The obvious way to build an open-items tracker is a local table of clause states, updated
as decisions come in. That builds a second source of truth alongside SuperDocs' own, and
the two drift the first time anything is decided out-of-band, retried, or interrupted.

SuperDocs already persists a durable audit trail per session — every round, every proposed
change, every decision. So the tracker doesn't own state; it **reconciles** against that
history.

- **SuperDocs owns:** the document, the AI reasoning, diff generation, approve/deny
  mechanics, per-job history.
- **This layer owns:** the domain semantics SuperDocs has no way to know — which side's
  position drove a proposal, and whether a clause is still contested *across* rounds.
  SuperDocs' history is job-scoped; a negotiation needs clause-scoped.

**Tested property:** wipe the local database entirely and the tracker rebuilds correct
clause states from SuperDocs' job history alone. That test is `@pytest.mark.live` — it runs
against the real API, because a mocked version of it would prove nothing.

**What this costs:** coupling to SuperDocs' job-history response shape, and to `chunk_id`
remaining stable for a clause across a session's lifetime. Both are documented behavior.
The trade buys a materially smaller and more reliable build than re-deriving change
tracking from scratch.

---

## Six API discrepancies found and worked around

Found by building against the live platform rather than reading docs. All reported to
SuperDocs separately, per the task brief. The three with the largest blast radius:

1. **Batch-approve rejects the documented request shape** with a 422. The working shape
   differs from the reference.
2. **The `jobs` endpoint wraps its list** rather than returning it bare, so the documented
   response shape needs one more unwrap than expected.
3. **`ask_every_time` does not reliably force review on identical inputs** — resubmitting
   the same instruction against the same document can resolve without producing a review
   step, which matters a great deal for a build whose entire premise is that a human gates
   every change.

Point 3 shaped the design: the round flow polls to resolution server-side and treats
"nothing to review" as a real, rendered state rather than an error, because it genuinely
happens.

---

## Stack, and why

**FastAPI + SQLite, sync SQLAlchemy.** Not Postgres: there is no vector search here, and
nothing in this build needs it. Sync deliberately — the recurring bug class in my Task 1
build was async-engine-per-event-loop issues, and this build sidesteps that category
entirely rather than re-fighting it.

**React** for the review UI, styling carried over from Task 1 for consistency.

**REST, not MCP.** The assigned card's surfaces (Review, Multi-document, export) are all
REST-shaped, and the brief's own guidance is to build against the four core calls first
with everything else as optional depth. An MCP server here would be surface area the card
does not ask for. My Task 1 build ships a real MCP server, so this is a scoping decision,
not an avoidance.

---

## What's cut, and why

**No `GET /negotiations` list endpoint exists on the platform**, so the Negotiations tab
lists only negotiations created in the current browser session. This is a real limitation,
not a design choice — it is surfaced in the UI rather than hidden, and a persistent list
would need either local storage of session ids or an endpoint that does not exist.

**No cross-session memory.** SuperDocs offers opt-in cross-session memory; a negotiation
spanning weeks would plausibly want it. Out of scope for the assigned card.

**No auth, no multi-user.** Single-operator tool. Two negotiators working simultaneously is
a real thing labour relations does, and this build does not address it.

**REOPENED status is not verified live.** APPROVED and REJECTED were both confirmed against
real API data in a browser. REOPENED renders through the identical code path and is covered
by two passing automated tests, but I could not reproduce it live in the time available and
will not claim I saw it.

---

## Verified in a real browser, against the real API

Not "it compiles." What was actually observed, end to end:

- Negotiation created with a real `upload_document` and two real `upload_attachment` calls
- A real two-item pending-changes round: diff chips rendered correctly, per-item
  approve/reject toggles worked, batch submit applied both decisions
- The "nothing to review" empty state hit four times — renders as an intentional state, not
  a broken screen
- Open Items showed APPROVED and REJECTED matching what had just been decided, read live
  from the real endpoint
- Export produced a valid 37KB `.docx`, verified outside the browser
- Zero JavaScript console errors throughout

**Three real UI bugs found and fixed during that walkthrough**, none of which were visible
from reading the code: a failed round displayed two contradictory messages simultaneously;
"nothing to review" and "just finished deciding everything" collapsed into the same
misleading state; and there was no way to start a second round after submitting decisions —
which, in a tool whose entire purpose is multi-round negotiation, was the worst of the
three.

---

## Getting started

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env        # add SUPERDOCS_API_KEY
python scripts/init_db.py
python scripts/seed_documents.py  # synthetic CBA + two position papers
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Tests — offline by default, no API key needed:

```bash
cd backend && source .venv/bin/activate
pytest tests/ -v                  # 24 passing
```

One test is `@pytest.mark.live` and exercises the DB-wipe reconciliation property against
the real API. It needs a key:

```bash
pytest tests/ -v -m live
```

All seed documents are synthetic. No real collective bargaining agreement, and no real
party's paperwork, appears anywhere in this repository.

---

Built by Aditya Medidala for the SuperDocs Round 2 engineering task.