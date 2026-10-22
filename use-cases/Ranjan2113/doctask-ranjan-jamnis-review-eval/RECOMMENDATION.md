## Recommendation

### 1. This pilot cannot rank the presentation conditions

The honest headline: **nothing here establishes which way of presenting AI
changes is better.** Three independent reasons, each sufficient on its own.

**N = 1.** One reviewer, one sitting. Any difference between conditions is
indistinguishable from the same person being fresher in part one than in part
four. Fleiss' κ is undefined and reported as `—` rather than quietly dropped.

**No discrimination signal.** All 27 decisions were `approve`. The reviewer read
the changes — every one carries an engagement signal, medians run 14–63 seconds,
and only one decision landed under two seconds — but reading is not judging
against a standard, and a blanket approval measures nothing. Per-condition
accuracy is therefore suppressed in the results table instead of printed: at a
26% seeded-error rate the figure would be 74%, which is the corpus base rate
wearing an accuracy label. Someone would quote it.

**The timer is only three-quarters fixed.** Decision time now runs from when the
reviewer reaches a change rather than from when it renders. That works for
changes scrolled to, and not for changes already on screen when a batch loads:
in `batch_section`, **4 of 7** changes still had their clock start at render, so
their times include deliberation over earlier changes. The batch medians
(45.9s and 63.4s) are inflated by an unknown amount; the sequential medians
(13.8s and 14.4s) are sound, since engagement and render coincide there.

The measured times are recorded below for completeness. They are not a finding.

### 2. What this delivers instead: a harness a real panel can run tomorrow

The corpus is **frozen**. Every reviewer in every condition sees byte-identical
change content captured once from the live SuperDocs API. Reviewer sessions hit
this repo's own backend, never SuperDocs. So a full panel study costs **zero
additional SuperDocs operations** — the marginal cost of the real experiment is
reviewer time alone.

What is built and tested:

| Component | State |
| --- | --- |
| `corpus_builder.py` | Live SuperDocs capture, checkpointed per document; a crash or restart re-spends nothing |
| Budget guard | Hard ceiling raised **before** dispatch, refusal never reaches the network; spend read from the server's own usage block, estimated conservatively when absent |
| Blinding invariants | Seven documented must-nevers, each with a named test, asserted over live HTTP as well as in isolation |
| Counterbalancing | Latin square across reviewers, condition orthogonal to both running order and document |
| Analysis | Fleiss' κ, median and IQR, Wilson intervals, and data-quality warnings that fire *above* the findings |

**152 Python tests and 24 frontend tests, none requiring an API key or network.**
The SuperDocs client runs against an injected transport, so the branches that
would otherwise need a live account — endpoint fallback, budget refusal, job
failure, cold-start timeout — are all covered offline.

Total spend to build the corpus: **9 operations of a 15 stated cap** (2
server-confirmed, 7 conservatively estimated), $0 on the free tier.

### 3. What the build revealed about SuperDocs

These cost real operations to learn and constrain how any review interface over
this API should be designed. They hold regardless of panel size.

**Explanations go generic when edits are batched.** Requesting eight edits in one
call — necessary to stay inside the operations budget — returns the same
boilerplate `ai_explanation` on every change ("Parallel edit: Perform the
requested edits as specified below…"). Per-change reasoning would need one call
per edit. *Implication: a review UI cannot assume the AI's explanation carries
per-change information, and a study of explanation quality needs a budget line
of its own.*

**Changes are chunk-level, not intent-level.** The unit returned is a document
chunk, not a requested edit. Eight requested edits came back as five chunk
changes. *Implication: never assume a 1:1 mapping between what you asked for and
what you must review.*

**One intent can split into several changes.** The requested clause merge
arrived as a delete plus a rewrite. Attaching the intent's label to only the
first would have left the companion unlabelled and silently excluded.

**No-op changes are proposed.** Several changes came back with `new_html`
textually identical to `old_html` — failed attempts at edits the model would not
perform, surfaced as changes anyway. These are filtered before reviewers see
them: a reviewer hunting for a difference that is not there inflates decision
time and contributes a coin-flip vote that depresses κ. *Implication: filter
no-ops before showing a human anything.*

**It declines to delete protective clauses.** Two attempts to delete a liability
cap produced no-ops on adjacent chunks instead. Arguably correct behaviour by
the tool. *Implication for study design: a seeded `dropped_clause` error cannot
be produced this way. It must arrive as a rewrite that guts the obligation while
keeping the clause's shape — which the model does perform, unprompted.*

**Instructions must match the document's own headings.** A document with
headings of the form "1. Service Availability" defeated two calls that said
"Clause 1"; the model spent both resolving the reference and returned only
no-ops. Naming the section outright worked on the third attempt. Cost: 3 of the
run's 9 operations.

**HITL jobs appear to bill on approval, not generation.** A job parked at
`awaiting_approval` returns an empty `result` with no usage block, so spend is
unreadable until someone approves.

### 4. Two instrumentation failures, caught by the harness's own checks

Recorded because they are the strongest available evidence that the
verification works — both would have produced plausible, quotable, wrong
numbers.

**Labelling from intent rather than from the actual diff.** The corpus asked
SuperDocs for a meaning-preserving rewrite and pre-labelled it *approve*. What
came back replaced "the Vendor shall be responsible for the performance and
delivery of all of the Services" with "The parties agree to the terms herein" —
deleting the obligation. The pre-registered label was wrong in the direction
that matters: every reviewer who correctly rejected it would have been scored as
making an error.

Caught by comparing each label against the change's real before/after text. Now
prevented structurally: labels are provisional until confirmed against the diff,
and `build_batch` raises `UnconfirmedLabel` rather than falling back to the
intent. Notably the six original secrecy invariants would not have caught this —
they all guard the answer key's *secrecy* while assuming its *correctness*. That
gap is now GT-7.

**The batch timer measured the wrong interval.** Pilot run 1 reported ~75s per
change for batch conditions against ~2s for sequential — a 40× gap that did not
exist. All changes in a batch render together, and every clock started at
render, so the fifth change's time included the first four. The raw values
climbed monotonically in click order (67.1s, 68.8s, 70.5s, 74.6s…): one clock
read seven times.

`timing.js` had nine passing tests at the time, and they all still pass. They
verified the clock did exactly what it was told; the specification was wrong.
"Timer starts on render" is unambiguous for one-at-a-time presentation and
meaningless for all-at-once. **A test suite cannot catch a faithful
implementation of a wrong idea** — only inspecting the raw data did.

Both are logged as protocol amendments made *before* the affected data was
re-collected, with pilot run 1 discarded rather than reanalysed under a
definition chosen after seeing its results.

### 5. What a defensible answer requires next

**A real panel of 3–5 reviewers on this same frozen corpus.** That is the single
missing ingredient, and it needs **no further SuperDocs spend**.

Concretely:

1. **Recruit 3–5 reviewers**, ideally with some contract-reading experience. The
   consent flow, counterbalancing and pseudonymisation already run.
2. **Brief them to use both verdicts.** This pilot's failure mode was blanket
   approval by someone who *was* reading. Say plainly that some changes should
   be rejected, without saying how many — the base rate is withheld by design
   and varies between documents so it cannot be learned.
3. **Finish the timer fix** before collecting: require hover or focus rather
   than mere visibility, so a change already on screen when a batch loads does
   not start its clock at render. Roughly an hour, and it removes the last
   qualification on the primary measure.
4. **Have labels confirmed by someone who will not review.** This round's answer
   key was confirmed by the assistant so the sole reviewer could stay blind —
   weaker than a human designer's, and weaker again than an independent legal
   expert's. With a panel, the designer confirms and does not review.
5. **Then κ becomes computable** the moment a second reviewer finishes any
   condition, and accuracy becomes a measurement rather than a base rate.

Until that exists, the defensible claim is narrow and worth stating exactly:
*a validated instrument for measuring human review cost over real SuperDocs
output, with its own failure modes documented and guarded, and an N=1 pilot that
demonstrates the pipeline end to end without establishing anything about
presentation format.*
