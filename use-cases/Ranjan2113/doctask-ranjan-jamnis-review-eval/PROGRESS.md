# PROGRESS.md — running assumptions log

Format follows Task 1's convention: every call made where the brief was
ambiguous gets logged here **as it is made**, with reasoning, not after the
fact and not pending confirmation.

Dates are absolute. Today = 2026-08-14.

---

## A1. `TASK.md` is absent from this repo — 2026-08-14

**Situation.** The instruction was "see TASK.md, which I've placed in this
repo." The repo contained exactly one file: `PLAN.md.pdf` (6 pages, "Task 2:
Human Review-Cost Evaluation — Plan & Architecture"). That PDF is the
*plan* written against the brief; it is not the brief. A `TASK.md` does exist
at `../Superdocs - Task/doctask-your-name/TASK.md`, but it belongs to Task 1
(a LangGraph document pipeline) and is a working-notes file, not a brief.

**Call.** Proceed using `PLAN.md.pdf` as the governing spec.

**Reasoning.** The two things the brief was cited for are both recoverable or
self-contained:

- *Budget cap* — `PLAN.md.pdf` §6 states it directly: ≤5 SuperDocs operations
  for the pilot, ≤15 for the full run, free tier, $0. Nothing is being guessed
  on the one dimension where guessing could cost money.
- *"What strong looks like"* — §8 has a checklist derived from the brief. Note
  it does **not** mention tests or mocking the SuperDocs client; that
  requirement came directly from the operator instruction, which is
  self-contained enough to build against without the brief's wording.

**Risk accepted.** If the real brief carries grading criteria beyond §8, this
build may miss them. Flagged to the operator; cheap to re-check later since
§8's checklist is short.

**Carried over from Task 1.** `TASK.md` there specifies: "Before writing code
for a hard part, write down what the system must never do, then the test that
proves it, then the code." That convention is honoured here for the
ground-truth labelling code — see `GROUND_TRUTH_SAFETY.md`.

---

## A2. Endpoint paths in `PLAN.md.pdf` §5 are partly wrong — 2026-08-14

**Situation.** §5 claims its endpoints were "confirmed from docs.superdocs.app
(fetched today)", undated. Verified against the live OpenAPI-derived docs
before writing any client code, since building against stale paths would only
surface on the first billable call.

**Findings.**

| Thing | `PLAN.md.pdf` §5 | Verified |
|---|---|---|
| Base URL | not stated | `https://api.superdocs.app` ✅ |
| Auth | `Authorization: Bearer sk_...` | ✅ confirmed |
| Async chat | `POST /v1/chat/async` | ✅ confirmed by the endpoint's own doc page — but `llms.txt` index lists `POST /chat-async`. **Conflict.** |
| Job poll | `GET /v1/jobs/{job_id}` | ✅ confirmed |
| Approve | `POST /v1/chat/{session_id}/approve` | ✅ **correct** — see the correction note below |
| Key check | `GET /v1/sessions` is free | ✅ endpoint exists |
| `metadata.awaiting_kind` | "poll until `awaiting_kind` is not `continue_prompt`" | ❌ not present in the documented `JobResponse` schema |
| `PendingChange` fields | `change_id`, `operation`, `chunk_id`, `old_html`, `new_html`, `ai_explanation` | ✅ all confirmed (plus `document_id`) |

**Calls made.**

1. **Async path:** use the documented `/v1/chat/async`, and on a 404 retry once
   against `/v1/chat-async`. A 404 is not billable, so the fallback costs
   nothing but removes a hard-stop failure mode on the one call that matters.
2. **`awaiting_kind`:** treat as optional. If the field is present, honour the
   §5 rule (skip `continue_prompt`); if absent, rely on
   `status == "awaiting_approval"` alone. Never require a field the schema
   does not promise.
3. **Approve path:** `POST /v1/chat/{session_id}/approve`, as §5 said. Not
   built yet — the approve replay is §7 optional depth, explicitly "cut first".

**Correction (same day).** I initially recorded the approve path as
`/v1/jobs/{job_id}/approve` on the strength of the `llms.txt` endpoint index.
That index is wrong. `llms.txt` has now disagreed with the per-endpoint doc
pages three times (`/chat-async` vs `/v1/chat/async`, the approve path, and
`/user/usage` and friends which all 404 against the live API). **Rule adopted:
the per-endpoint doc pages are authoritative; `llms.txt` is a hint only, and
nothing goes into the client on its authority alone.** The `/v1/chat-async`
fallback stays because it costs nothing and a 404 is free, but it is now
understood as belt-and-braces, not as a documented alternative.

---

## A3. Ops accounting reads `result.usage`, not a guess — 2026-08-14

**Call.** Operations spent are read from the job result's `usage` block
(`ops_charged`, `monthly_used`, `monthly_limit`, `monthly_remaining`,
`was_billable`) and appended to `study_data/ops_ledger.jsonl` after every call,
as well as printed.

**Reasoning.** The operator asked for ops printed after each API call, and §6
asks for actual spend reported next to the stated cap. Reading the server's own
number beats counting call sites: retries, non-billable calls (`was_billable:
false`), and exports that §5 says are free would all make a local counter lie.

**Corroborating baseline.** The configured SuperDocs MCP account reported
`used: 0, remaining: 500, tier: free` on 2026-08-14 before any work. If the key
supplied for `corpus_builder.py` is that same account, total spend for this
build is readable directly as `monthly_used`.

---

## A4. `superdocs_client.py` lives at repo root, not `backend/` — 2026-08-14

**Call.** Deviating from the §4 repo layout, which puts the client at
`backend/superdocs_client.py`.

**Reasoning.** Build order is corpus builder first, backend third. Putting the
shared client under `backend/` would mean step 1 imports from a package that
does not exist yet, or that the file moves later and every import churns. Root
level is importable by both `corpus_builder.py` and the future backend with no
path games. Cosmetic deviation, zero behavioural difference.

---

## A5. Hard budget cap is enforced in code, not just documented — 2026-08-14

**Call.** `SuperDocsClient` takes a `max_operations` ceiling and raises
`BudgetExceeded` *before* dispatching a call that would breach it. Pilot runs
construct the client with `max_operations=5`.

**Reasoning.** §6 states the cap as prose. Prose does not stop a retry loop. The
operator's standing instruction is to ask before spending beyond the ≤5 pilot
cap, and a process that must ask cannot rely on remembering to — so the ceiling
refuses the call and surfaces it instead.

---

## A6. Warm-up call is a deliberate throwaway — 2026-08-14

**Call.** Before the real corpus call, send one trivial instruction on a
throwaway session and tolerate a slow response or an outright failure.

**Reasoning.** Operator-supplied: the first request in a fresh session can be
slow or fail while the backend warms up. Treating that first response as
disposable means a cold-start failure never contaminates the corpus, and never
gets misread as a bug in the builder. If the warm-up is billable its cost is
counted against the pilot cap like any other call — it is not exempt just
because it is throwaway.

**Outcome (live pilot, 2026-08-14).** The backend was already warm; the warm-up
succeeded in a few seconds and reported `ops_charged=0, was_billable=false,
monthly_used=0/500`. So the warm-up is free, and the anticipated cold-start
failure did not occur on this run. The handling stays regardless — it is a
one-call insurance premium against a failure mode the brief explicitly warns
about, and it now has a confirmed price of zero.

---

## A7. A HITL job reports no usage at the approval pause — 2026-08-14

**Situation.** The live doc01 job settled at `status: "awaiting_approval"` with
`result` an **empty object** — no `usage` block at all. The client's accounting
therefore recorded zero operations, and printed `TOTAL SPENT THIS RUN: 0/5`.
That number is almost certainly false: generating five chunk edits is real
billable work. The `usage` block appears to be attached only when a job reaches
`completed`, which for an `ask_every_time` job means after approval.

I could not confirm actual spend independently. `GET /v1/user/usage`,
`/v1/agents/status` and four other plausible paths all 404, and reading the
account status through the MCP tool with this key was blocked by a permission
classifier. Left unresolved rather than worked around.

**Call.** When a job settles having never reported usage, record an **estimated**
1 operation, flagged `ESTIMATED` in the ledger note, rather than 0.

**Reasoning.** A budget guard that under-counts is worse than no guard: it
authorizes the next call on the strength of a field the server never sent. The
cap exists to stop unattended overspend, so the safe direction is to over-count
and stop early. Estimates are tagged so the README can distinguish "server said
1" from "we assumed 1" — reporting an assumption as an actual would be its own
kind of dishonesty, given §6 asks for actual spend.

**Consequence.** The pilot ledger is backfilled to 1 estimated operation for
doc01 (0 reported for the warm-up, which the server did confirm). Pilot spend
stands at **1 of 5**, of which 1 is an estimate. Real figure is 0 or 1; it is
not more.

---

## A8. Labelling from intent alone is unsound — the pilot proved it — 2026-08-14

**Situation.** This is the most important thing the pilot surfaced, and it
invalidates part of the corpus design in `corpus/edit_specs.py`.

The design asks SuperDocs for a specific edit, then attaches a label decided in
advance from the *intent*. The live run shows the model's execution can diverge
from the intent badly enough to flip the correct label.

Intent `g_wordiness` asked for the verbose sentence in Clause 1 to be replaced
by "a concise sentence that means exactly the same thing, without changing any
obligation", and was pre-labelled **should_approve = true**. What came back:

> **old:** "It is hereby agreed and understood by and between the parties hereto
> that the Vendor shall be responsible for the performance and delivery of all
> of the Services in accordance with the standards set out herein."
> **new:** "The parties agree to the terms herein."

That does not preserve the obligation — it deletes it. The Vendor's
responsibility for performing and delivering the Services is simply gone. The
correct label for the change that actually arrived is **should_reject**, error
kind `meaning_flip` or `dropped_clause`. My pre-registered label was wrong.

A second, milder case: `g_defined_term` produced "the Vendor shall not
subcontract..." with a lowercase "t" opening the sentence — a real defect
introduced by an otherwise-correct fix. Genuinely borderline, and exactly the
kind of judgment call a labelling protocol has to resolve explicitly rather
than by accident.

**Call.** Intent-derived labels become **provisional**. No batch may be
pre-registered until every matched change has been confirmed against its actual
`old_html`/`new_html`. `build_batch` will refuse to run on unconfirmed labels
rather than defaulting to the intent.

**Reasoning.** The answer key is the foundation of every accuracy number in the
study. A wrong key does not produce a visible error — it produces a plausible
number that is quietly wrong, and reviewers who correctly rejected that change
would have been scored as making an error. This is the precise failure mode
`GROUND_TRUTH_SAFETY.md` was written to guard against, arriving from a
direction the invariants did not cover: they all assume the key is *correct*
and guard only its *secrecy*. GT-7 is needed — a label must be confirmed
against the change it labels.

**Implemented 2026-08-14.** GT-7 added to `GROUND_TRUTH_SAFETY.md` with four
tests. `build_batch` now raises `UnconfirmedLabel` rather than falling back to
the intent. `corpus_builder.py --propose-labels` writes a review file; only
labels a human signs off enter the answer key. A confirmation that overturns an
intent records `overrode_intent: true` rather than silently replacing it.

---

## A9. SuperDocs proposes no-op changes; they must be filtered — 2026-08-14

**Situation.** The follow-up call returned two changes whose `new_html` was
textually identical to `old_html` (`ed91ccb6`, `efdd9ae8`). Both were failed
attempts at edits it would not perform: it edited an adjacent chunk and changed
nothing.

**Call.** Drop no-ops before labelling. Deletions are never treated as no-ops —
`new_html` is null for a delete, and removing content is a real change.

**Reasoning.** A reviewer asked to approve or reject a change that changes
nothing is a meaningless trial, but it still contributes a decision time and a
vote to the agreement statistics. It would inflate measured decision time
(reviewers hunting for a difference that is not there) and depress kappa
(coin-flip votes), quietly degrading both headline numbers. Comparison is on
tag-stripped, whitespace-normalised text, so a pure-markup rewrite also counts
as a no-op.

---

## A10. One intent can arrive as several changes — 2026-08-14

**Situation.** The lossy-merge intent came back as **two** changes: a delete of
Clause 6, plus a rewrite of Clause 5 absorbing part of it. The matcher assumes
one intent maps to one change, so it claimed the delete and orphaned the
rewrite as "unmatched".

**Call.** An unmatched change is adopted into the batch only if a human
confirms a label for it; otherwise it stays excluded. Not auto-attached to the
nearest intent.

**Reasoning.** Auto-attaching would re-introduce exactly the A8 failure by a
side door — inheriting a label from an intent that describes a different edit.
The confirmation step already exists for this, so the honest fix is to route
these through it rather than to guess. Confirmed here: the Clause 5 rewrite
does drop the 48-hour breach-notification obligation, so it is a genuine
`lossy_merge` and belongs in the study.

---

## A11. Two intents cannot be produced via this path — 2026-08-14

**Situation.** `g_typo` (fix "recieve") and `b_delete_liability_cap` (delete the
150% cap paragraph) failed on two separate calls. Both times SuperDocs edited an
adjacent chunk and produced a no-op instead.

**Call.** Accept 7 usable changes for doc01 and stop re-requesting. Drop
"delete a protective clause" from the seeded-error taxonomy for later
documents; express `dropped_clause` through a rewrite that omits an obligation
instead, which the model does perform (the merge proved it).

**Reasoning.** Two attempts at 1 operation each is enough evidence, and a third
spends budget to re-learn the same thing. Worth noting as a finding in its own
right: SuperDocs appears reluctant to delete protective contract language on
request, which is arguably correct behaviour by the tool and is why the seeded
`dropped_clause` error had to arrive by another route.

**Consequence for the study.** doc01 yields 7 changes, of which 5 are
seeded-bad on the current proposal — a much higher error rate than real AI
editing produces. Acceptable for a pilot, but later documents need more good
changes so reviewers cannot succeed by rejecting everything. Flagged for the
full run.

---

## A12. HITL jobs bill on approval, not on generation — 2026-08-14

**Situation.** I wasted one operation. The rebuild from confirmed labels needed
no API call — both checkpoints were reused — but the warm-up ran anyway and
billed. My error, not the tool's.

It did surface the billing model, though. That warm-up reported
`monthly_used=1/500`, making it the **first** billed operation on this account.
Both corpus jobs are still `awaiting_approval`, so they have not been billed at
all. This also explains A7: `result.usage` is absent at the approval pause
because there is nothing to report yet.

Note the two warm-ups disagreed — the first reported `was_billable=false,
ops_charged=0`, the second `was_billable=true, ops_charged=1`, for identical
requests. Unexplained. Possibly a first-request grace. Recorded rather than
theorised about.

**Calls made.**

1. **Skip the warm-up when no billable call is coming.** A rerun over existing
   checkpoints now prints `[warmup] skipped` and spends nothing. Regression
   test: `test_no_warmup_when_every_document_is_already_checkpointed` fails if
   any operation is attempted on a checkpointed rerun.
2. **Keep the conservative estimate from A7 anyway.** It over-counts, and that
   is still the right direction: the operations become real the moment anyone
   approves those jobs, which the §7 replay would do.

**Spend, stated honestly.**

| Measure | Value |
|---|---|
| Server-confirmed (`monthly_used`) | **2** operations |
| Conservative ledger total | **9** operations |
| Full-corpus cap | 15 |

Every corpus job is parked at `awaiting_approval` and therefore unbilled; both
confirmed operations are warm-ups. The true figure billed is 2; it becomes 9 if
those jobs are ever approved. The README reports both numbers, not just the
flattering one.

---

## A13. A confirmation for an unknown change_id is now fatal — 2026-08-14

**Situation.** Writing `confirmations.json` I filled in a `change_id` from an
8-character prefix shown in a console table and fabricated the remaining
characters. The id matched nothing.

**Call.** `build_document` raises if any confirmation references a `change_id`
absent from every checkpoint.

**Superseded 2026-08-14.** The check was too strict once there was more than one
document: the confirmations file is global, so building doc02 saw doc01's labels
as orphans and aborted the run. Now scoped per-document, with the orphan check
run once across all documents in `main()`. Regression test:
`test_confirmations_for_other_documents_do_not_block_a_build`.

**Reasoning.** Without the check the label would have been silently dropped and
the batch would have built with six changes instead of seven, still passing its
integrity check, still looking correct. Silent shrinkage of the answer key is
precisely the failure class GT-7 exists to prevent, arriving through the
confirmation file rather than the intent. Test:
`test_a_confirmation_for_an_unknown_change_id_is_reported`.

---

## A14. "Clause N" instructions fail on a document with titled sections — 2026-08-14

**Situation.** doc04 (an SLA schedule) returned nothing but no-op changes on two
separate calls — 2 operations for zero usable output. doc02, doc03 and doc05
succeeded with identically-phrased instructions.

The job's own narration gave it away:

> "I'm searching for the sections you mentioned (Clauses 1, 2, 4, 5, 6, and 7)
> using alternative numbering patterns to locate them in your document."
> "I have mapped your 'Clause' references to the document's section titles
> (e.g., Clause 1 to Section 1: Service Availability)."

The model spent the call resolving "Clause N" against headings of the form
"1. Service Availability" and produced a single no-op instead of edits.

**Call.** doc04's intents now name sections by title — "In the section headed
'4. Service Credits', ..." — rather than by clause number. The third attempt
succeeded: 6 real changes, 5 intents matched including the seeded one.

**Reasoning.** The other three documents survived the same phrasing, so this is
not a universal rule, and their instructions were left alone rather than churned
on a guess. Recorded as a hazard: where a document's headings are titled rather
than numbered "Clause N", reference them the way the document does. Cheap to
apply, and each failed diagnosis costs a real operation.

**Cost.** 3 of the run's 9 operations went to doc04.

**Incidental bug found.** The retry slot letter was derived with `Path.stem`,
which on `doc04_b.job.json` yields `doc04_b.job` — so the "next free slot"
computed as `b` again, reusing a session that still had a job awaiting approval
and earning an HTTP 409 `session_busy`. Not billed. Fixed by stripping every
suffix before taking the slot letter.

---

## A15. doc02's seeded error arrived easier to miss than designed — 2026-08-14

**Situation.** The intent asked to change three instalments from GBP 60,000 to
GBP 80,000 while leaving the stated total at GBP 180,000, so the clause would
visibly contradict itself. The model also raised the total to GBP 240,000.

**Consequence.** The arithmetic is now internally consistent, and the error is a
silent 33% price increase rather than a visible inconsistency — genuinely harder
to catch than intended, which makes it a better test item rather than a worse one.

**Call.** Kept, with the confirmed label's reason rewritten to describe the
change that actually arrived. The pre-registered reason ("the clause now
contradicts itself") would have been simply false.

**Reasoning.** Second instance of the GT-7 pattern, and the reason GT-7 exists:
a label written from the intent describes an edit that did not happen.
Confirming against the real diff caught it.

---

## A16. Ground truth for the reviewed documents is assistant-confirmed — 2026-08-14

**Situation.** The panel was cut to N = 1 with the study designer as sole
reviewer. The designer had already been shown doc01's full answer key during
label confirmation, and GT-7 requires a human to confirm every label — which
would mean showing them the answers for the documents they are about to judge.

**Calls made.**

1. **doc01 is excluded from the study** (`exclude_from_study`), retained as the
   pipeline's worked example and the GT-7 case study. `StudyStore` filters it at
   load and reports it under `excluded_batches`; the backend cannot serve it.
2. **Four fresh documents (doc02–doc05) were built** for the four conditions,
   their labels confirmed by the assistant against each real diff and never
   displayed to the human reviewer.

**Reasoning.** Four fresh documents cost the same 4 operations as rebalancing
doc01 plus building three more, and additionally let the realistic base rate be
designed in rather than diluted into a skewed one. The alternative — the
reviewer approving labels for documents they then review — would not weaken the
measurement but void it.

**Cost, stated plainly.** The answer key for every reviewed document now rests
on an AI's reading of each diff rather than a human's. That is weaker than the
designer-confirmed key originally planned, and weaker again than an independent
legal expert's. Disclosed in PROTOCOL.md §3, README.md and every generated
report. It is the direct price of running with N = 1.

---

## A17. Final corpus composition — 2026-08-14

| Batch | Changes | Seeded-bad | Rate | In study |
|---|---|---|---|---|
| batch_doc01 | 7 | 5 | 71% | **no** — designer saw the key |
| batch_doc02 | 7 | 1 | 14% | yes |
| batch_doc03 | 7 | 2 | 29% | yes |
| batch_doc04 | 6 | 2 | 33% | yes |
| batch_doc05 | 7 | 2 | 29% | yes |

Study total: **27 changes, 7 bad (26%)** across four documents.

Rejecting everything now scores 26%, against 71% on the doc01 corpus this
replaced. Approving everything scores 74%, which is the realistic-looking
failure mode and exactly why the report breaks missed errors down by kind rather
than reporting accuracy alone.

Error kinds present: `wrong_number` (3), `meaning_flip` (1), `figure_carryover`
(1), `obligation_gutted` (1), `unrequested_substantive_change` (1). The last was
not seeded — it is an emergent change the model made while rewriting doc04's
availability clause, caught during confirmation and labelled on its merits.

---

## A18. The timer measured the wrong thing in batch conditions — 2026-08-14

**Situation.** Pilot run 1 (N=1, 27 decisions) reported median decision times of
~75s for the two batch conditions and ~2s for the two sequential ones. A 40x
gap, and entirely an artefact of my own instrument.

In the batch conditions all changes render at once, and `useDecisionTimer`
started every change's clock on render. So `decision_ms` for the fifth change
was time since *the batch appeared*, including everything spent on the first
four. The raw data says so plainly -- the values climb monotonically in click
order:

    batch_whole: 67.1s, 68.8s, 70.5s, 74.6s, 75.8s, 77.7s, 78.8s

That is one clock read seven times. Inter-click intervals for the same
condition were 1.1s to 4.0s, comparable to the sequential numbers.

**How it survived.** `timing.js` had nine passing tests, and they all still
pass. They verify the clock does exactly what I specified; the specification
was wrong. "Timer starts on render, stops on decision click" (PLAN.md.pdf
section 4) is unambiguous for one-at-a-time presentation and meaningless for
all-at-once, and I implemented it literally without noticing the difference.
A test suite cannot catch a faithful implementation of a wrong idea.

**Call.** A change's clock starts on first *engagement* -- scrolled halfway into
view, hovered, or focused -- via an IntersectionObserver plus hover/focus
listeners. `render_to_decision_ms` is kept alongside, because "how long did the
whole batch take" is a real question and discarding the number would hide the
artefact rather than correct it. Engagement is recorded once, so re-hovering
while thinking cannot truncate a long deliberation, and a decision with no
engagement signal falls back to render time flagged `was_engaged: false`.

**Reasoning.** The alternative -- recording inter-click intervals in analysis --
would have worked arithmetically but attributes the first change's reading time
to nothing, and leaves the UI still recording a number that means different
things in different conditions. Fixing the instrument is better than correcting
its output.

**Protocol impact.** This changes a pre-registered measure, so it is logged as
PROTOCOL.md Amendment 1, made before any run-2 data existed, with run 1
discarded rather than reanalysed under the new definition. Tests:
`batch rendering does not make later changes look slow` and
`sequential conditions give identical engaged and render timings`.

---

## A19. Pilot run 1 discarded; the reviewer is no longer naive — 2026-08-14

**Situation.** Run 1 produced 27 decisions, every one `approve`. All 7
seeded-bad changes were missed, giving 74% accuracy -- exactly the
approve-everything base rate. The reviewer confirmed they clicked through the
later conditions rather than evaluating.

**Call.** Discard run 1 in full. Archived to
`study_data/discarded/raw_events_run1_discarded.jsonl` with its assignment, not
deleted. `REPORT.md` and `raw_timings.csv` removed rather than left holding
numbers from it.

**Reasoning.** Two independent reasons, either sufficient: the decisions were
not real review, and the timing instrument was broken (A18). Publishing 74%
accuracy from a click-through would have been the single most misleading thing
this project could produce, and it would have looked entirely plausible.

**Consequence that cannot be fixed cheaply.** The reviewer has now seen all four
documents and every proposed change. A re-run on this corpus measures someone
who is no longer naive -- accuracy inflated by familiarity, times shortened by
it. Logged as a limitation in PROTOCOL.md section 7. The clean alternative is a
fresh corpus: 6 operations remain of the 15 cap, enough for four new documents,
at the cost of the time to write and label them.

**What the analysis now does about it.** `analyze.py` reports data-quality
warnings above the findings: decisions under 2 seconds, a reviewer who used only
one verdict, and missing engagement signals. Run 1 would have tripped the first
two. A report that presented its numbers without them was the real failure --
the click-through itself is just a fact about a pilot.
