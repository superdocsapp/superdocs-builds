# INVARIANTS — `builds/poa-generator/`

Written **before** the tests, and the tests before the code (TASK.md hard rule
7). Every invariant names the test that proves it. An invariant with no test is
an intention, not an invariant.

This is legal-adjacent output and **we are not lawyers.** That sentence is the
whole reason this file is longer than the last one.

The thesis this app has to make true:

> **Every clause in the draft was selected by the intake from a data library, no
> clause text is ever authored by a model, and the document is not exportable
> until the counsel-review notice and the external-execution notice have been
> read back out of the live document verbatim.**

---

## Section A — what this app must never say (the legal-adjacency list)

This section comes first because it is the one that matters if everything else
works. A power of attorney that is well engineered and quietly claims to be
executed is worse than one that fails loudly.

A1. **Never present the draft as legal advice.** Every draft carries the
counsel-review notice, verbatim, from the moment it is assembled — it is in the
uploaded skeleton, not added later — and no code path can remove it.
*Proved by* `test_notices.py::test_every_assembled_draft_carries_both_notices_verbatim`.

A2. **Never claim the document is executed, signed, witnessed, notarised,
valid, binding or in force.** A phrase list is scanned over the rendered
document and any hit is a hard error naming the phrase and the clause. The list
is data (`config/forbidden-phrases.csv`), so adding a phrase is a data edit.
*Proved by* `test_notices.py::test_a_forbidden_phrase_anywhere_in_the_draft_is_a_hard_error`
and `test_the_forbidden_phrase_list_is_data_not_code`.

A3. **Never imply notarisation happened.** The external-execution notice states
in as many words that signing, witnessing and notarisation happen outside this
product, and the signature block is emitted with every signature and date cell
empty. A signature cell that is not empty is a hard error.
*Proved by* `test_notices.py::test_the_signature_block_leaves_every_signature_and_date_blank`.

A4. **Never state a jurisdiction's execution requirements as fact.** The
jurisdiction library carries language that defers to counsel; it does not assert
how many witnesses a jurisdiction requires. A jurisdiction row whose text
asserts a requirement without deferring is refused at load time.
*Proved by* `test_library.py::test_a_jurisdiction_row_that_asserts_a_requirement_is_refused`.

A5. **Never let a model author clause text.** SuperDocs is never asked to draft,
create, add, rewrite or improve a clause. Every instruction is a replacement
whose complete post-state we computed from the library before sending. Measured
on 2026-08-09: asked for one section, the product produced six, four of them
invented in confident, domain-appropriate prose. In a power of attorney an
invented clause is a power nobody granted.
*Proved by* `test_editplan.py::test_no_step_uses_a_creating_verb` and
`test_editplan.py::test_every_step_sends_a_post_state_computed_from_the_library`.

A6. **Never grant a power the intake did not select.** The powers that reach the
document are exactly the ids in the intake, resolved against
`config/powers.csv`. An id the catalogue does not have is a hard error naming
the catalogue; it is never dropped and never approximated.
*Proved by* `test_intake.py::test_an_unknown_power_id_is_a_hard_error` and
`test_two_drafts.py::test_neither_draft_carries_the_other_s_powers`.

---

## Section B — the export gate (hard constraint 1)

B1. **The document is not exportable until read-back confirms both notices are
present verbatim.** The gate is structural, not a check somebody remembered to
call: `export()` requires a `NoticeReceipt`, and a `NoticeReceipt` can only be
constructed by `check_notices()` against a live read-back. There is no other
constructor and no default argument.
*Proved by* `test_notices.py::test_export_cannot_be_called_without_a_receipt`
and `test_a_receipt_cannot_be_forged`.

B2. **A missing notice refuses the export.** Removing either notice chunk from
the document leaves the export path raising, with no file produced.
*Proved by* `test_notices.py::test_export_refuses_when_a_notice_is_missing`.

B3. **An altered notice refuses the export.** One word changed, one word
dropped, or the notice paraphrased is the same failure as removing it. This is
the case that matters: a rewrite plausibly paraphrases.
*Proved by* `test_notices.py::test_export_refuses_when_a_notice_is_altered`.

B4. **No notice block is ever an edit target.** Notices are structure, uploaded
verbatim, and the plan is refused before anything is sent if a step names one.
*Proved by* `test_editplan.py::test_no_step_targets_a_notice_block`.

---

## Section C — structure is ours

C1. **Never ask SuperDocs to create.** One verb, and it is `replace`
(Decision 28).
*Proved by* `test_editplan.py::test_no_step_uses_a_creating_verb`.

C2. **Never issue a mid-document insertion.** The entire final document
structure — which clauses exist for this intake, in what order, at what
numbers, with every cross-reference already pointing at the right number — is
computed here and uploaded verbatim (Decision 29).
*Proved by* `test_editplan.py::test_no_step_targets_a_heading_block`.

C3. **Never let a clause number be inferred, remembered or asked for.** Numbers
come from one pass over our own ordered clause list, and the two required drafts
number differently because the healthcare draft has a clause the financial one
does not.
*Proved by* `test_assemble.py::test_clause_numbers_come_from_the_selected_set`.

C4. **Never leave a cross-reference pointing at the wrong clause.** Every
`clause N` reference is resolved through the same numbering pass, and the
assembled document is re-scanned for a reference that does not resolve.
*Proved by* `test_assemble.py::test_every_cross_reference_resolves_in_both_drafts`.

C5. **A cross-reference is structure, so it is identical in the skeleton and in
the target.** If a reference differed between the two, an edit would be
renumbering, and renumbering is the thing this design exists not to delegate.
*Proved by* `test_editplan.py::test_no_step_changes_a_clause_reference`.

---

## Section D — the library is data

D1. **Adding a power type, a clause, or a jurisdiction is a data edit.** No
clause text, no power label, no jurisdiction name and no notice text appears as
a string literal in any `.py` file in this package.
*Proved by* `test_library.py::test_no_clause_text_is_hardcoded_anywhere_in_the_package`.

D2. **A clause condition that cannot be parsed stops the run; it never reads as
"this clause does not apply".** A silent `False` drops a clause from a power of
attorney, which is the failure mode with no symptom.
*Proved by* `test_library.py::test_an_unparseable_condition_is_a_hard_error`.

D3. **A placeholder with no resolver stops the run.** It is never left in the
document and never silently emptied.
*Proved by* `test_library.py::test_an_unresolved_placeholder_is_a_hard_error`.

---

## Section E — the wire, copied from Phase 4 as an idea and rebuilt

E1. **Never batch, and never approve a change we did not compute** (Decision 35,
and Decision 41 for what comes back).
*Proved by* `test_client.py::test_a_batch_is_split_into_ours_and_everything_else`.

E2. **Never use the synchronous chat route for a gated change** (Decision 32).
*Proved by* `test_client.py::test_gated_changes_go_to_the_async_route`.

E3. **Never send feedback on a denial** (Decision 34).
*Proved by* `test_client.py::test_denials_carry_no_feedback`.

E4. **Never treat the job as the decision record** (Decision 33).
*Proved by* `test_orchestrator.py::test_the_decision_row_is_written_before_the_actuator_is_called`.

E5. **Never believe the chat reply, the `changes_summary`, or a 200.** The only
evidence is `GET /v1/documents/{id}?include_html=true`.
*Proved by* `test_verifier.py::test_a_reply_claiming_success_does_not_make_a_step_ok`.

---

## Section F — the failure path

F1. **Never report an edit applied without reading the whole document back.**
Three classes, all detected: **not applied**, **applied wrong**, **collateral
damage**.
*Proved by* `test_verifier.py`, one test per class, each driven by a recorded
response from `docs/evidence/`.

F2. **Never run a downstream step after a failed one.** The queue halts.
*Proved by* `test_orchestrator.py::test_a_failure_halts_the_queue_and_downstream_steps_never_run`.

F3. **Never export after a failure** — which here means two independent
refusals, the halt and the notice gate.
*Proved by* `test_orchestrator.py::test_no_export_after_a_failure`.

F4. **Never re-plan.** At most one narrow retry of the same instruction, and a
retry diffs the whole document.
*Proved by* `test_orchestrator.py::test_at_most_one_narrow_retry_and_never_a_replan`.

---

## Section G — the boundary

G1. **Never import from `system/`, and never speak its vocabulary.** This tree
answers *what must the document say, and did SuperDocs actually say it*.
*Proved by* `tests/test_isolation.py` and `tests/test_domain_boundary.py`.

---

## What it may do, stated so the boundary is not accidentally wider

- Say what a clause library row says, because a human wrote that row and it is
  under version control in this repository.
- Say that a draft is incomplete — a limited power of attorney with no stated
  limitation is refused rather than drafted around.
- Leave every signature, witness and notarisation field empty and say why.
