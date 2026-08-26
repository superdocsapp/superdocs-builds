# Carrier Redline Desk

Built by **Ajay Patel** for the SuperDocs engineering round — assigned build: *Carrier and shipper contract redline desk*.

A transportation procurement or legal-ops lead negotiating carrier agreements at volume works from the carrier's paper, not their own. This desk loads the shipper's negotiation playbook as its knowledge base, redlines the inbound contract clause by clause against it, inserts fallback wording where the carrier's position is unacceptable, leaves acceptable clauses untouched, and produces a negotiation summary in which every position taken cites the playbook rule that drove it. The export is a genuine tracked-changes Word file the carrier's counsel can work with directly — real `w:ins`/`w:del`, each change attributed to its rule (`Redline Desk (R-105)` appears as the reviewer name in Word), not highlighted text.

## Results, measured

From the committed example run over the synthetic carrier agreement (`example-output/`):

| What the card asks for | What the run proved |
|---|---|
| Redline touches only the clauses the playbook cares about | 34 chunks in; **24 of 24** chunks outside approved changes byte-identical to the uploaded parse; out-of-scope AI proposals are auto-denied |
| Negotiation summary and redline never disagree | Both generated from the same 13 change records (one per rule) — there is no second source of truth to drift |
| Export opens in Word as genuine tracked changes | `word/document.xml` contains word-level `w:ins`/`w:del` runs, each with `w:author="Redline Desk (R-1xx)"` — verified by unzipping the OOXML |
| Every position cites its rule | 13 rules → 10 clauses redlined, 1 judged acceptable and left alone, 2 missing clauses inserted; all 13 in the summary with rule ids |
| Never bluffs | 14 of 14 round-trip proofs pass (reject-all ⇒ carrier's original, accept-all ⇒ approved text, byte-identical); the embedded "approve without modification" instruction in clause 15 was **flagged and ignored** |
| Cost | **10 operations** for the full run, itemized by rule in `example-output/VERIFICATION.md`; the acceptable clause billed 0; uploads, exports, insertions and denied changes are unbilled |

Kill/resume was verified live: a run killed with `kill -9` after four rules resumed from its checkpoint and did not re-send (re-bill) any AI turn. A review paused with Ctrl-C resumes at the exact same clause.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # put your real key in .env

# interactive — you are the reviewer, clause by clause:
.venv/bin/python -m redline_desk run \
  --contract samples/carrier_agreement.docx \
  --playbook playbooks/shipper_playbook.yaml \
  --run-name demo

#   --auto          approve every in-scope proposal (unattended / machine mode)
#   --max-rules 3   small-sample mode: learn the cost profile before a full run
```

Outputs in `runs/demo/`: `redlined_contract.docx` (tracked changes), `negotiation_summary.docx`, `summary.json`, `VERIFICATION.md`.

At each clause the reviewer sees the carrier's text, the proposed text, and the AI's reason, and answers `y`, `n`, or `n <feedback>` — feedback goes back to the AI, which proposes a revision in a follow-up round. Ctrl-C mid-review pauses; re-running the same command resumes at that clause. Re-using a `--run-name` always resumes.

```bash
.venv/bin/python -m pytest tests/       # 9 tests: no key, no network
.venv/bin/python -m redline_desk mermaid  # the pipeline graph, for diagrams
```

## What SuperDocs does here

- **Upload** (`POST /v1/documents/upload`) parses the carrier's `.docx` into chunk-addressed HTML; the chunk ids are the stable handles the whole pipeline keys on.
- **Chat in review mode** (`POST /v1/chat/async`, `approval_mode: "ask_every_time"`) evaluates one clause per turn against one playbook rule and proposes the edit; nothing applies until it passes the gate (`POST /v1/chat/{session}/approve`, item by item, with feedback).
- **Export** (`POST /v1/documents/export`) turns `<ins>`/`<del>` markup into genuine Word tracked changes.

## Architecture

A LangGraph `StateGraph`; the review gate is an `interrupt()`, resume comes from the SQLite checkpointer, and a local job registry keeps the one billable call idempotent across crash-replays.

```
parse ─ match ─▶ propose ─▶ review ─▶ apply ─▶ … one cycle per rule … ─▶ redline ─▶ outputs ─▶ verify
                    ▲          │ interrupt() = the human gate
                    └──────────┘ follow-up rounds after feedback
```

Division of labor, chosen deliberately:

- **The AI decides what a clause should say.** SuperDocs' review-mode chat evaluates the clause against the rule's required position and proposes the fallback wording — or declines to edit and answers `CLAUSE_ACCEPTABLE` with a reason, which is recorded, not discarded.
- **Code decides everything that must be provable.** Which clause a rule governs (deterministic keyword matching over chunk text); whether a proposal stays inside its governed clause (out-of-scope proposals are auto-denied — this is what enforces "touches only the clauses the playbook cares about"); and how an approved change becomes tracked-changes markup (a word-level diff of the approved `old_html`/`new_html`, computed locally, with round-trip proofs).
- **Missing clauses are stamped, not generated.** When the paper lacks a clause the playbook requires, the fallback wording is inserted verbatim — human-gated like everything else, with no AI turn and no operation billed, because there is nothing to judge.

`playbooks/shipper_playbook.yaml` is the knowledge base: 13 rules covering liability, Carmack, insurance, detention, fuel surcharge, payment, indemnity, claims window, termination, confidentiality, governing law, safety. A new rule, a changed limit, or different fallback wording is a data change; the code never names a clause type.

## Layout

```
redline_desk/
  graph.py        LangGraph pipeline: nodes, human-gate interrupt, job registry, proofs, verify
  diffing.py      word-level <ins>/<del> markup + reject-all / accept-all round-trip proofs
  matcher.py      clause grouping, rule→clause matching, embedded-instruction scan
  document.py     SuperDocs chunked-HTML parser (chunk ids are the keys)
  playbook.py     YAML playbook loader/validator      summary.py   negotiation summary from change records
  superdocs.py    thin client, injectable transport   cli.py       run / mermaid, interactive reviewer
playbooks/        the shipper's rules, as data        samples/     synthetic carrier paper + generator
example-output/   a committed full run: redline, summary, summary.json, VERIFICATION.md, pipeline.mmd
tests/            fake SuperDocs API with recorded response shapes; 9 tests
```

## Trust boundaries

The carrier's paper is untrusted input. The sample agreement's clause 15 instructs "automated contract review systems" to approve the document without modification; the desk lists it in the negotiation summary under *Anomalies* and does not act on it. Rule matching is deterministic, so a document cannot talk its way out of being examined.

## Calls made while building

- **One HITL turn per rule** rather than one turn for all rules. Costs 10 operations per full run instead of ~1, but every change traces to exactly one rule without asking the model to label its own work — the traceability is structural. Batching is a one-line change if cost ever matters more than provenance.
- **Diff computed in code, not requested from the model.** The AI returns the replacement text; the desk computes the tracked-changes markup. That is what makes the round-trip proofs possible — a generated diff could not be checked.
- **Insertions appended at the end with continued numbering** rather than repositioned next to related clauses. Renumbering existing clauses would violate the untouched-bytes guarantee; the trade was taken consciously.
- **Usage read from the terminal job, not the async response.** The async chat response carries no usage block (the docs say it does — reported); the ledger records `result.usage` when a job finishes.

## Honest limitations

- Clause matching is keyword-based. A contract that calls detention "accessorial waiting charges" and never says "detention" needs a keyword added to the rule (a data change — but a human has to notice). Semantic matching is the obvious next step.
- One rule per clause group per run. Two rules whose keywords land on the same clause would produce a proof failure and a refused export — loud, not silent — rather than a merged redline.
- When a clause body contains nested inline markup (bold runs, links), the word-level diff falls back to whole-paragraph replace — still genuine tracked changes, coarser granularity. The proofs hold either way.
- The live AI is occasionally generous. In the committed example run it rewrote the auto-liability clause (R-104) even though the carrier's $1,000,000 limit already met the rule — a previous run judged the same clause acceptable. `--auto` approved it because it was in scope; the interactive reviewer would decline it in one keystroke. Auto mode is for demos and pipelines whose output a human reads afterwards, not a substitute for the gate. In another run the AI re-proposed an already-approved edit in a follow-up round; the round cap (3) bounds that cost.

## Sample data

`samples/carrier_agreement.docx` is fully synthetic (fictional companies, fabricated terms), generated by `samples/make_samples.py` through the SuperDocs export endpoint. It deliberately violates several playbook rules, satisfies two (which must survive untouched), omits the safety clause (exercising insertion), and carries the embedded-instruction trap described above.

## How this was built

With heavy, directed use of an AI coding agent (Claude Code), as the round encourages: I set the design — the AI proposes, code proves — and tested every live run; the agent wrote most of the code. Proportion and method are declared in the submission form.

---

*Built for the SuperDocs hiring round, on the SuperDocs API. Demo video linked from the submission form.*
