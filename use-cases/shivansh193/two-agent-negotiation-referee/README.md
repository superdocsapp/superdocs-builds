# Two-Agent Document Negotiation with a Human Referee

Built by Shivansh Kalra for the SuperDocs task.

Two agents, TechFlow Solutions (Vendor) and Meridian Retail Group
(Customer), negotiate two terms of a Master Services Agreement -- Payment
Terms and Limitation of Liability -- by alternately proposing changes to
one shared document. Every round is a real, reviewable proposed change
(`approval_mode: "ask_every_time"`, never `auto-apply`); nothing is ever
silently rewritten. The loop is bounded by construction, not by hope, and
escalates to a human referee with a complete memo when the two sides
genuinely can't agree.

All content is synthetic: two fictional companies negotiating a
fictional contract.

## What makes each agent's position real, not scripted

Each agent's opening ask, walk-away limit, and step size per round lives
entirely in its own playbook -- an HTML data file
(`content/playbook_vendor.html`, `content/playbook_customer.html`), never
in `build.py`. `parse_playbook()` reads those six numbers back out of the
files at runtime and uses them for this build's own independent
convergence check too, so the check is data-driven, not hardcoded to one
scenario. `content/playbook_customer_escalation.html` is the same file
with exactly one number changed -- proof the playbooks are genuinely
swappable, not decorative, is in [Verified result](#verified-result).

## What it does

1. Uploads the MSA terms (focused) plus both playbooks (background).
2. **Pre-round test**: generates a real proposed change, then deliberately
   *rejects* it, and confirms the document is byte-for-byte unchanged
   afterward -- proof a denied round leaves no residue.
3. **Negotiation rounds** (up to `MAX_ROUNDS = 6`): vendor opens, then the
   two sides alternate counters. Each round either leaves an
   already-acceptable term untouched or moves it by exactly the
   playbook's step size, never past that side's own walk-away limit.
   Stops early the moment this build's own check -- using both playbooks'
   real numbers, not the model's say-so -- confirms both terms are within
   both parties' limits.
4. If `MAX_ROUNDS` passes without agreement: writes
   `output/escalation_memo.json` with the full round history and both
   playbooks' positions, and stops. No further rounds are attempted.
5. **Export**: builds a redline HTML with real `<ins>`/`<del>` tags from
   the original anchor values to the final negotiated values, and exports
   *that* directly via the API's `html` field.

## How to run it

```bash
python -m venv .venv
.venv/Scripts/activate    # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env      # then set SUPERDOCS_API_KEY
python build.py --dry-run                                        # convergent case, zero API calls
python build.py                                                  # convergent case, for real
python build.py --customer-playbook playbook_customer_escalation.html   # escalation case, for real
```

## SuperDocs features used

- **Multi-document sessions** (`open_mode: "replace"` / `"background"`) --
  the negotiated document plus both playbooks open together
- **Chat / async edit** (`POST /v1/chat/async`) with
  `approval_mode: "ask_every_time"`, including explicit denial
  (`approved: false` with feedback) as a first-class, tested path
- **Export** (`POST /v1/documents/export`) with hand-built `<ins>`/`<del>`
  HTML passed via the `html` field -- see Honest limitations for why

## Verified result

Two real negotiation runs, plus one earlier run that surfaced a real bug
in this build's own prompts before either of these (full trace in
[`PROGRESS.md`](PROGRESS.md)).

**Convergent case** (`playbook_customer.html`, default): AGREED after 5
rounds. Final state: Payment Terms 30 days, Liability Cap 2x -- exactly
vendor's floor and customer's ceiling on both terms, confirmed by this
build's independent check against both playbooks' real numbers.

**Escalation case** (`playbook_customer_escalation.html`, one number
changed from the default): Payment Terms resolved cleanly to 30 days by
round 2. Liability Cap never converged -- a real, deliberately designed
gap between vendor's 2x floor and customer's 3x ceiling. Ran its full
6-round cap and escalated, with a complete memo (`payment_terms_resolved:
true`, `liability_cap_resolved: false`, full round history, both
playbooks' actual limits) for a human referee to act on.

**The four pass-bar items, checked against direct evidence:**

| Requirement | Evidence |
|---|---|
| Every round auditable and reversible | `audit_trail.json` captures every round's real proposed `old_html`/`new_html`. The reject-test proposes and denies 4 real edits and proves byte-for-byte no residue in the document afterward. |
| Export carries real tracked changes | Unzipped both the AGREED and ESCALATED `.docx` and read `word/document.xml` by hand: real `<w:ins>`/`<w:del>` with proper `<w:delText>` children, both old and new text present (`Net 45 days` -> `Net 30 days`, `four (4) times` -> `two (2) times`). |
| Non-converging case escalates, not loops | Constructed on purpose, run for real, hit its 6-round hard cap (a bounded `for` loop, not a hope), escalated with a complete memo. |
| Playbooks are genuinely swappable | `parse_playbook()` reads every number from the HTML at runtime. Two real runs of the same unmodified `build.py`, differing only in which `--customer-playbook` file was passed, produced the correct different outcome each time. |

**A real, honest observation, not smoothed over**: the customer agent's
step-discipline was looser than vendor's in both real runs -- one round
jumped straight to its full preferred value instead of one step, another
moved a term that already satisfied its own ceiling and didn't need to
move at all. Neither broke correctness (both runs still converged
exactly where they should have, or correctly failed to), but it's a real
difference in how faithfully the two sides followed the same instruction
template with only the playbook name and direction word substituted.

## Honest limitations

- SuperDocs' export does not carry tracked changes for a session's
  pending, unapproved edits -- tested directly before this build was
  designed (see PROGRESS.md): exporting a session with a pending change
  silently returns the pre-change document. Genuine `w:ins`/`w:del` only
  comes from constructing `<ins>`/`<del>` HTML directly and exporting via
  the `html` field, which is what this build does for its final export --
  it does not reflect the platform's own approval history natively.
- The reject-test and negotiation share one session; the negotiation's
  own instructions are written defensively (explicit document naming,
  explicit "do not edit the playbook" clauses) after an earlier run
  showed how easily an ambiguous "this document" reference goes wrong --
  see PROGRESS.md for the full failure and fix.
- `output/` is gitignored; run `python build.py` (and the escalation
  variant) to regenerate everything, including both `.docx` exports and
  both JSON audit trails.

## Files

- `build.py` -- upload -> reject-test -> negotiation rounds (playbook-
  driven, independently verified convergence) -> escalation-or-export ->
  tracked-changes verification flow, plus `--dry-run` and
  `--customer-playbook`
- `content/msa_terms.html` -- the two-term MSA excerpt being negotiated
- `content/playbook_vendor.html`, `content/playbook_customer.html` --
  each side's real negotiating position, as data
- `content/playbook_customer_escalation.html` -- the customer playbook
  with exactly one number changed, proving both swappability and the
  escalation path
- `PROGRESS.md` -- full diagnostic trace, including the wrong-document
  bug this build's own instructions caused and how it was found and fixed
