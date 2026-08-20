# INVARIANTS — `builds/statutory-statements/`

Written **before** the tests, and the tests before the code (TASK.md hard rule
7). Every invariant names the test that proves it. An invariant with no test is
an intention, not an invariant.

The thesis this app has to make true:

> **Nothing structural is ever asked of SuperDocs, every figure that reaches the
> document is traceable to a source row, and no edit is called applied until the
> whole document has been read back and compared against a post-state we
> computed before we sent it.**

---

## What this app must never do

### Structure

1. **Never ask SuperDocs to create.** One verb, and it is `replace` (Decision
   28). No `create`, no insert, no "add a section". Measured: the only operation
   that inserts is also the one that fabricated four sections nobody asked for
   (PROGRESS.md 2026-08-09).
   *Proved by* `test_edit_plan.py::test_every_step_is_a_replacement_of_an_existing_chunk`
   and `test_no_create_verb_anywhere`.
2. **Never issue a mid-document insertion.** The entire final skeleton —
   every heading at its final number, every cross-reference already repointed —
   is computed here and uploaded verbatim (Decision 29). There is no step in the
   plan that changes a heading's number.
   *Proved by* `test_edit_plan.py::test_no_step_targets_a_heading_chunk`.
3. **Never let a note number be inferred, remembered or asked for.** Numbers are
   assigned by one pass over our own ordered tree. The insertion point of a new
   note comes from the trial balance account order, not from a list of known
   note names.
   *Proved by* `test_note_tree.py::test_insertion_point_comes_from_account_order`
   and `test_no_note_title_is_hardcoded`.
4. **Never leave a cross-reference pointing at the old number.** Every
   note→primary reference and every `Note N` in prose is repointed through the
   same map that renumbered the headings, and the final document is re-scanned
   for any reference that does not resolve to a heading that exists.
   *Proved by* `test_note_tree.py::test_every_cross_reference_resolves_after_insertion`.
5. **Never let the checklist drift from the document.** Every checklist item's
   `satisfied_by_note` is remapped through the same map. After the run, every
   mapped item must name a heading that exists at the number we expect, and
   every heading must be accounted for.
   *Proved by* `test_checklist.py::test_checklist_survives_the_insertion`.

### Figures

6. **Never write a figure that does not resolve to a source.** Every money token
   in every rendered body must be one of exactly four bases — `ledger`,
   `comparative`, `document`, `derived` — and there is no fifth. A rendered body
   is re-scanned after rendering and an unaccounted token is a hard error naming
   the token and the note.
   *Proved by* `test_figures.py::test_an_unaccounted_token_is_a_hard_error`.
7. **Never store a derived total.** `Derived.value` is a property computed from
   its components on every read, so a total cannot drift from the citations that
   support it and cannot be stated apart from them.
   *Proved by* `test_figures.py::test_a_derived_total_has_no_value_field`.
8. **Never carry a prior-year figure forward under this year's heading without
   the ledger confirming it did not move.** A `comparative` basis figure is
   admissible only when the trial balance's prior-year column and the prior-year
   signed statements agree to the paisa; a disagreement is a hard error, not a
   preference for one side.
   *Proved by* `test_rollforward.py::test_a_comparative_mismatch_is_a_hard_error`.
9. **Never invent an analysis the sources do not support.** Where the trial
   balance is at caption granularity and a note needs a finer breakdown, the note
   states the tied total and names what is outstanding and where we looked. It
   never carries last year's breakdown under this year's heading.
   *Proved by* `test_bodies.py::test_no_regenerated_body_reuses_a_prior_year_breakdown`.
10. **Never resolve a disagreement between two sources.** Where the minutes and
    the ledger disagree, both are quoted and neither is preferred. There is no
    field on `Disagreement` a resolution could be written into.
    *Proved by* `test_disagreement.py::test_disagreement_has_nowhere_to_record_a_resolution`.

### The wire

11. **Never batch, and never approve a change we did not compute.** One chunk
    per job on the sending side (Decision 35). The answering side does not
    always agree — measured on this build's first live run, an instruction
    naming one chunk id came back as a two-change batch — so we approve exactly
    our change and deny every other one **bare**, and the read-back is what
    makes that safe.
    *Proved by* `test_client.py::test_a_batch_is_split_into_ours_and_everything_else`
    and `test_a_batch_that_does_not_contain_our_target_is_refused_in_full`.
12. **Never use the synchronous chat route for a gated change.** The gate takes a
    `job_id` and jobs exist only on `/v1/chat/async` (Decision 32).
    *Proved by* `test_client.py::test_gated_changes_go_to_the_async_route`.
13. **Never send feedback on a denial** (Decision 34). Feedback triggers a
    re-plan and the re-plan goes off target — measured, twice.
    *Proved by* `test_client.py::test_denials_carry_no_feedback`.
14. **Never treat the job as the decision record** (Decision 33). Our ledger row
    is written first, with the actor, and `approve` is only an actuator. The
    product's gate is write-only and cannot be read back.
    *Proved by* `test_decision_ledger.py::test_the_row_is_written_before_the_actuator_is_called`.
15. **Never believe the chat reply, the `changes_summary`, or a 200.** The only
    evidence is `GET /v1/documents/{id}?include_html=true`. Measured: the reply
    has over-claimed once and under-claimed once, and the completion sentence
    reported two numbers that were both wrong.
    *Proved by* `test_verifier.py::test_a_reply_claiming_success_does_not_make_a_step_ok`.

### The failure path

16. **Never report an edit applied without reading the whole document back.**
    Three classes, all detected: **not applied** (target chunk unchanged),
    **applied wrong** (target changed but not to the expected bytes),
    **collateral damage** (any non-target chunk moved, or the chunk set changed).
    *Proved by* `test_verifier.py`, one test per class, each driven by a recorded
    response from `docs/evidence/`.
17. **Never run a downstream step after a failed one.** The queue halts. This is
    the 2026-08-07 corrupted-document mechanism and the halt is the whole
    defence.
    *Proved by* `test_orchestrator.py::test_a_failure_halts_the_queue`.
18. **Never export after a failure.** No export, no "partial success", no
    completion sentence. Revert to the last verified-good state and surface the
    diff.
    *Proved by* `test_orchestrator.py::test_no_export_after_a_failure`.
19. **Never re-plan.** At most one narrow retry of the same instruction, and a
    retry diffs the *whole* document, because failed content has been observed
    arriving a turn later.
    *Proved by* `test_orchestrator.py::test_at_most_one_retry_and_never_a_replan`.

### The boundary

20. **Never import from `system/`, and never speak its vocabulary.** This tree
    answers *what must the document say, and did SuperDocs actually say it*. It
    never emits a finding, never quotes evidence bytes as a finding, never
    produces a report. `system/` never holds a SuperDocs document id.
    *Proved by* `tests/test_isolation.py` and `tests/test_domain_boundary.py`.

---

## What it may do, stated so the boundary is not accidentally wider

- Read `corpus/` as read-only input. Both trees do; that is shared data, not
  shared code.
- Quote a source's bytes **as the provenance of a figure it writes**. That is
  the citation discipline, rebuilt against a different substrate — not a
  finding.
- Say that a required disclosure has no note. That is the disclosure checklist
  doing its job, and it is a property of the document, not a judgement about
  the company.
