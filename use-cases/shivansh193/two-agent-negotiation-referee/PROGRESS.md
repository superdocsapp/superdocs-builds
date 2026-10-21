# Progress log -- Two-Agent Document Negotiation with a Human Referee

## Before designing the build: tracked changes needed a real answer, not an assumption

The pass bar requires the export to carry real, Word-readable tracked
changes. Checked the `ExportOptions` schema first -- no `track_changes` or
`redline` flag exists. Two cheap, targeted experiments before writing any
negotiation logic:

1. Uploaded a tiny document, proposed one edit (`ask_every_time`, left
   pending, never approved), and exported the *session* while that change
   was still pending. Result: the export silently ignored the pending
   diff and returned the pre-change document -- no tracked changes, no
   sign the edit was ever proposed.
2. Constructed `<del>Net 45 days</del><ins>Net 30 days</ins>` HTML by
   hand and exported it via the `html` field directly (not `session_id`).
   Result: genuine Word tracked changes -- `<w:del w:id="1"
   w:author="Unknown" w:date="...">` wrapping a proper `<w:delText>`
   element, and a matching `<w:ins>`, both text values present. Verified
   by unzipping the docx and reading `word/document.xml` directly.

This settled the design: track each negotiated term's original anchor
value and final value, build a redline HTML with real `<ins>`/`<del>`
tags for just those two terms, and export *that* HTML directly rather
than exporting the session.

## Playbook parsing validated before any API call

`parse_playbook()` reads six numbers out of each playbook's own HTML
text at runtime -- nothing about either party's position is hardcoded in
`build.py`. Checked against all three playbook files with zero API cost:
correct extraction from `playbook_vendor.html`, `playbook_customer.html`,
and `playbook_customer_escalation.html`. Also caught a real design bug
here, for free: the escalation playbook was first written by *lowering*
the customer's liability floor from 2x to 1x, which actually *widens*
the customer's acceptable range and leaves the zone of agreement intact
at 2x -- the opposite of the intended effect. Fixed by *raising* it to
3x instead (above the vendor's ceiling of 2x), which creates a real,
unbridgeable gap. An exhaustive check across liability values 0-9
confirmed no integer satisfies both playbooks under the fixed version.

## Run 1 (convergent playbook): six rounds, zero real progress

The negotiation never moved off the anchor values (`Net 45 days`, `four
(4) times`) across all 6 rounds, despite several rounds reporting
genuinely approved edits. Diagnosed by reading `audit_trail.json`'s
captured `old_html`/`new_html` per round rather than trusting the
round-by-round snapshots alone: every edit had landed on
**`playbook_vendor.html`'s own content**, not `msa_terms` -- the model
was editing its own reference playbook, not the document being
negotiated, in every single round.

Root cause was in this build's own prompt, not the platform: both
instruction templates named `playbook_vendor` (or the customer playbook)
first, told the model to "read it," and then said "**This document's**
Section 4..." -- an ambiguous pronoun reference that most naturally
resolves to the document just named, not the actually-focused
`msa_terms`. Fixed by naming `msa_terms` explicitly, every time, in both
`opening_instruction()` and `counter_instruction()`, and by adding an
explicit "do not edit `{playbook_doc}` itself" clause. This is the same
family of lesson as everything else found by name-based instructions
tonight: an LLM will resolve an ambiguous "this document" to whatever
was mentioned most recently, not to what a human reader would obviously
intend from context.

## Run 2 (convergent, fixed instructions): converged for real

Rewired instructions, re-ran. Vendor's opening landed correctly on
`msa_terms` (`Net 15 days`, `one (1) times` -- its own preferred
position). Customer's round 2 counter jumped straight to its own
preferred liability figure (`five (5) times`) rather than moving by the
playbook's stated one-step increment, and left the clearly-violating
payment term (`15 days`, well outside its own ceiling) untouched. Not a
bug worth chasing -- the pass bar doesn't require every round to be
letter-perfect, and the imperfection didn't derail anything (the *audit
trail* is the design goal, and it caught this precisely). This run's
`reject-test` round also turned out to be a degenerate case: the job
completed with zero pending changes, so the "no residue" check passed
trivially rather than proving anything about an actual denied proposal.

## Run 3 (convergent, reject-test hardened): real evidence, real convergence

Added a hard check: if the reject-test proposes zero real edits, the
script now raises rather than silently accepting a degenerate pass. Ran
again for real:

- **Reject-test**: 4 real proposed edits, all explicitly denied
  (`approved: false` with feedback), document confirmed byte-equivalent
  before and after (`{'payment_days': 45, 'liability_mult': 4}` both
  times). This is now a genuine test of a real rejected proposal, not a
  no-op.
- **Negotiation**: 5 real rounds. Vendor opened at its preferred position
  (15 days, 1x). Customer moved liability in one uneven jump (1x -> 5x,
  its full preferred ask, not a single step) and left payment untouched
  despite violating its own ceiling. Vendor's every move was disciplined
  -- exactly one step, only when its own floor was violated. By round 4,
  customer corrected payment to exactly 30 days (one correct 15-day
  step) but also nudged liability down from 4x to 3x -- a term that
  already satisfied its own ceiling (>=2x) and didn't need to move at
  all, an unprompted, unrequired concession. Vendor's round 5 (3x -> 2x,
  its final permitted step) landed exactly on the true zone of
  agreement, and this build's own independent check -- using both
  playbooks' actual numbers, not anything the model claimed -- confirmed
  it: **AGREED after round 5, final state 30 days / 2x, exactly matching
  vendor's floor and customer's ceiling on both terms.**

Customer's step-discipline was looser than vendor's throughout both real
runs (overshoots, one unprompted move on an already-satisfied term), but
never in a way that broke correctness -- the negotiation still converged
on the objectively correct point both times it had a real zone of
agreement to find. Worth naming as an honest observation, not smoothed
over: the two agents did not follow their playbooks with equal
discipline, even though both started from the same instruction template
with only the playbook name and direction word substituted.

## Escalation run (`--customer-playbook playbook_customer_escalation.html`)

No code changes from Run 3 -- only the `--customer-playbook` flag
differs, pointing at a file that's identical to the default customer
playbook except for one edited number. Payment terms resolved cleanly to
30 days by round 2 and correctly stayed there for the rest of the run
(both sides recognizing it as already-settled). Liability cap never
converged, for the deliberately designed reason: vendor's floor is 2x,
customer-escalation's ceiling is 3x, no integer satisfies both. The loop
ran its full `MAX_ROUNDS = 6` and stopped -- a `for` loop over
`range(1, 7)` with an early `break` on convergence cannot run past 6
iterations by construction, agreement or not. `output/escalation_memo.json`
was written with the full round history, both playbooks' actual limits,
the final state, and an explicit per-term resolved/unresolved flag
(`payment_terms_resolved: true`, `liability_cap_resolved: false`) -- a
human referee gets everything needed to make the actual call.

## Direct verification against the four pass-bar items

1. **Every round genuinely auditable and reversible.** `audit_trail.json`
   captures every round's actual proposed `old_html`/`new_html`, not
   just a summary. The reject-test proposes and denies 4 real edits and
   proves byte-for-byte no residue -- checked directly, not assumed.
2. **Export carries real tracked changes, readable in Word.** Verified
   by unzipping both the AGREED and the ESCALATED `.docx` and reading
   `word/document.xml` directly: real `<w:ins>`/`<w:del>` elements with
   proper `<w:delText>` children, both the original and final text
   present (`Net 45 days` -> `Net 30 days`, `four (4) times` -> `two (2)
   times`). Not inferred from the automated check alone -- read by hand
   a second time, same result.
3. **A deliberately non-converging case escalates instead of looping.**
   Constructed on purpose (one number changed in one playbook file),
   run for real, ran its full 6-round hard cap, escalated with a
   complete memo. Confirmed via an exhaustive check that no integer
   liability value could have satisfied both playbooks under that file.
4. **Both playbooks are genuinely swappable data files.** `parse_playbook()`
   reads every number from the HTML at runtime. Two full real runs used
   the same unmodified `build.py`, differing only in which
   `--customer-playbook` file was passed, and produced the correct,
   different outcome each time (AGREED vs. ESCALATED) -- not asserted,
   run.

All four hold up under direct evidence, not just the rendered output.
Committed and pushed to PR #115 per the standing instruction that a
build clearing all four bars doesn't need a check-in first.
