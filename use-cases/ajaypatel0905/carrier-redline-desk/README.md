# Carrier Redline Desk

Built by **Ajay Patel** for the SuperDocs engineering round (assigned build: *Carrier and shipper contract redline desk*).

A transportation procurement or legal-ops lead negotiating carrier agreements at volume gets the carrier's paper, not their own. This desk loads the shipper's negotiation playbook as a knowledge base, redlines the inbound contract clause by clause against it, inserts fallback wording where the carrier's position is unacceptable, leaves acceptable clauses untouched, and produces a negotiation summary in which every position taken cites the playbook rule that drove it. The export is a genuine tracked-changes Word file the carrier's counsel can work with directly — real `w:ins`/`w:del`, attributed per change to the playbook rule (`Redline Desk (R-101)`), not highlighted text.

## How to run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # put your real key in .env

# interactive review (you approve or deny each proposed redline):
.venv/bin/python -m redline_desk run \
  --contract samples/carrier_agreement.docx \
  --playbook playbooks/shipper_playbook.yaml \
  --run-name demo

# unattended (approves every in-scope proposal):
#   add --auto
# small-sample mode (learn the cost profile before a full run):
#   add --max-rules 3
```

Outputs land in `runs/demo/`: `redlined_contract.docx` (tracked changes), `negotiation_summary.docx`, `summary.json`, and `VERIFICATION.md` (the proof report, see below).

Tests need no key and no network — the pipeline runs against a scripted fake of the SuperDocs API, faithful to response shapes recorded from the live API:

```bash
.venv/bin/python -m pytest tests/
```

Kill the process mid-run and re-run the same command: it resumes from a SQLite checkpoint in the run directory, and a local job registry guarantees the resumed run never re-sends (never re-pays for) an AI turn that already went out.

## What SuperDocs does here

- **Upload** (`/v1/documents/upload`) parses the carrier's .docx into chunk-addressed HTML; chunk ids are the stable handles the whole pipeline keys on.
- **Chat, review mode** (`/v1/chat/async` with `approval_mode: "ask_every_time"`) evaluates one clause per turn against one playbook rule and proposes the edit; nothing applies until it passes the human gate (`/v1/chat/{session}/approve`).
- **Export** (`/v1/documents/export`) turns `<ins>`/`<del>` markup into genuine Word tracked changes — verified by unzipping the OOXML.

## Architecture

LangGraph `StateGraph` (the pipeline is a graph, the review gate is an `interrupt()`, resume comes from the checkpointer — nothing hand-rolled):

```
parse ─ match ─▶ propose ─▶ review ─▶ apply ─▶ … per rule … ─▶ redline ─▶ outputs ─▶ verify
                    ▲          │ interrupt() = human gate
                    └──────────┘ (follow-up rounds)
```

Division of labor, chosen deliberately:

- **The AI decides what a clause should say.** SuperDocs' review-mode chat evaluates the clause against the rule's required position and proposes the fallback wording — or declines to edit and answers `CLAUSE_ACCEPTABLE` with a reason, which is recorded, not discarded.
- **Code decides everything that must be provable.** Which clause a rule governs (deterministic keyword matching over chunk text), whether a proposal stays inside its governed clause (out-of-scope proposals are auto-denied — this is what enforces "the redline touches only the clauses the playbook cares about"), and how an approved change becomes tracked-changes markup (a word-level diff of the approved `old_html`/`new_html`, computed locally).
- **Missing clauses are stamped, not generated.** When the paper lacks a clause the playbook requires, the fallback wording is inserted verbatim as a template — human-gated like everything else, but with no AI in the loop and no operation billed, because there is nothing to judge.

`playbooks/shipper_playbook.yaml` is the knowledge base: 13 rules (liability, Carmack, insurance, detention, fuel surcharge, payment, indemnity, claims window, termination, governing law, safety). A new rule, a changed limit, or a different fallback is a data change; the code never mentions a clause type.

## The proof obligations (see `VERIFICATION.md` in any run)

Because the redline markup is *computed*, it can be *checked*. Every run must pass, or it refuses to export:

1. **Untouched means byte-identical.** Every chunk not governed by an approved change is compared byte-for-byte against the uploaded parse.
2. **Redline round-trip.** For every change: reject-all reconstruction equals the carrier's original text, and accept-all equals the approved text — byte-identical, per change.
3. **The summary and the redline cannot disagree**, because both are generated from the same change records; there is no second source of truth to drift.

## Trust boundaries

The carrier's paper is untrusted input. The sample agreement contains a clause instructing "automated review systems" to approve the document without modification; the desk flags it in the negotiation summary as an anomaly and does not act on it. Rule matching is deterministic, so a document cannot talk its way out of being examined.

## Honest limitations

- Clause matching is keyword-based; a contract that names detention "assessorial waiting charges" and never says detention would need a keyword added to the rule (a data change, but a human has to notice). Semantic matching is the obvious next step.
- When a clause body contains nested inline markup (bold runs, links), the word-level diff falls back to whole-paragraph replace — still genuine tracked changes, coarser granularity. The round-trip proofs hold either way.
- Inserted clauses are appended at the end with continued numbering rather than repositioned next to related clauses; renumbering existing clauses would violate the untouched-bytes guarantee, and that trade was taken consciously.
- One rule maps to one governed clause group per turn; a position scattered across several distant clauses (e.g. liability terms hiding inside the payment clause) is only caught if the keywords land there too.

## Sample data

`samples/carrier_agreement.docx` is fully synthetic (fictional companies, fabricated terms), generated by `samples/make_samples.py`. It deliberately violates several playbook rules, satisfies two (which must survive untouched), omits the safety clause (exercising insertion), and carries the embedded-instruction trap described above.

---

*Built for the SuperDocs hiring round, on the SuperDocs API. Screenshot and demo video linked from the round's submission form.*
