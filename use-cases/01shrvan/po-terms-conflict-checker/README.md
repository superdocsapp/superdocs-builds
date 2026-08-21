# Purchase-order Terms Conflict Checker

Built by **Shrvan Benke** for the SuperDocs Round 2 engineer task.

A purchase order carries the buyer's terms. The supplier's acknowledgement carries theirs. Nobody
reads either until something goes wrong. This compares the two **clause area by clause area**,
quotes both sides on every contested point, says which document is likely to govern given what
actually happened, and drafts the letter that preserves the buyer's position.

## What it does

**Compares by substance, not by heading.** A clause titled *"Limitation of Liability"* and one
titled *"Maximum Recoverable Amount"* are the same subject and are compared as such. The bundled
`corpus/pile-b` shares **none** of `pile-a`'s headings — "Liability Ceiling", "Mobilisation and Site
Access", "Forum for Disputes" — and every clause area still resolves.

**Reports silence as its own finding.** If one document addresses a topic and the other does not,
that is `silence`, and it gets its own band in the interface and its own heading in the memo. It is
never listed among the conflicts, because a reader skimming a conflicts list and not finding
warranty there will reasonably conclude warranty is agreed. It is not agreed — nobody said anything.

**Says which document is likely to govern** — from the recorded sequence of events and a named
doctrine, never from a model's opinion. See below.

**Drafts the letter.** An objection reserving rights when anything is outstanding, a confirmation
only when nothing is. The two are not an interchangeable pick: confirming while a conflict is open
would waive the buyer's position.

### On the two bundled piles

```
pile-a   4 contested · 2 where the supplier is silent · 0 agreed · 1 addressed by neither
pile-b   0 contested · 3 silent · 4 agreed
```

A checker that always finds conflicts would look excellent on `pile-a` and be worthless. `pile-b`
exists to catch that.

## Run it

```bash
cd backend
python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
PYTHONPATH=. ./.venv/Scripts/python.exe -m uvicorn app.api:app --port 8000

# in a second shell
cd frontend && npm install && npm run build
```

Then open <http://localhost:8000>, pick a pile, and press **Compare**.

```bash
cd backend && PYTHONPATH=. ./.venv/Scripts/python.exe -m pytest    # 43 tests
```

**No API key is needed** for anything above. Set `SUPERDOCS_API_KEY` (copy `.env.example` to `.env`)
only to draft the letter through SuperDocs and export DOCX or PDF.

## Which document governs — how this avoids pretending

This is the part of the brief where a build most easily starts making things up. The tempting
version hands both documents to a model and prints whatever it says about which terms prevail: a
confident legal conclusion with no reasoning, on a question where being confidently wrong costs a
buyer real money.

**No model decides it.** Instead:

1. **The sequence is explicit input** — who sent what, when, and whether it was objected to. Facts a
   contract manager knows, not inferences from prose.
2. **The doctrine is data.** [`rules/last-shot-england.json`](rules/last-shot-england.json) holds
   the named rules and their conditions. Another jurisdiction, or a firm's house view, is a new
   file — not a code change. There is a test that swaps the file and watches the conclusion swap.
3. **The analysis names what it relied on**, and reports INCONCLUSIVE rather than reaching for the
   nearest rule.

```
Likely to govern: The supplier's terms      Rule matched: LS-1

Facts this depends on:
  - The last set of terms was sent by the supplier on 2026-02-12
  - Performance followed those terms, first on 2026-02-26
  - The buyer did not object before performance

This is a triage position ... not legal advice. Confirm with counsel before relying on it.
```

Adding **one objection event** before performance flips the answer to the buyer. An objection dated
*after* delivery does not — timing is the whole doctrine. Both are tests.

## SuperDocs features used

- **Multi-document** — buyer and supplier documents opened into one session
- **Chat** — `POST /v1/chat/async` with `approval_mode: "ask_every_time"` to draft the letter
- **Review** — every proposed change approved or rejected individually before it lands
- **Export** — the finished memo and letter

⚠️ The published quickstart shows `POST /v1/chat` followed by an approve call using `job_id` and
`change_id`. That endpoint returns neither and applies edits immediately, so approval is impossible
on it. The async endpoint above is what actually supports a human gate. Reported as a bug.

## Honest limitations

- **`/api/export` renders locally and produces HTML only.** Asking it for `docx` returns `501`
  naming where DOCX is available, rather than handing back HTML bytes under a `.docx` name. A
  capability may be honestly absent from a path; it should never be present and broken.
- **Clause matching is a phrase table plus a position heuristic**, not a model. It scores an area by
  how many of its phrases appear and how early they appear, because a clause states its subject
  first and cross-references other subjects later. It is inspectable and editable by someone who
  knows procurement but not Python — and it will miss phrasings the table has never seen.
- **The governing analysis covers one doctrine.** `last-shot-england` only. UCC §2-207 and the
  "knock-out" approach are different files that do not exist yet.
- **Two documents, one per side.** Amendments and prior master agreements are not folded in.
- **Not legal advice**, and every rendering says so.

## Sample data

Everything in [`corpus/`](corpus) is synthetic and describes fictional companies. No real supplier
paperwork appears here.
