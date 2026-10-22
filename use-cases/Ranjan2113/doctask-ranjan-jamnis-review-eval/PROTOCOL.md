# PROTOCOL — human review-cost evaluation

**Written and committed before any reviewer data was collected.** That ordering
is the whole point: analysis choices fixed after seeing results are not
findings, they are selections. `study_data/raw_events.jsonl` did not exist when
this file was written.

Status at time of writing (2026-08-14): corpus built, backend and UI built,
**zero reviewers run**.

---

## 1. Question

How does the way an AI's proposed document changes are presented affect the
cost and reliability of human review? Cost is measured as decision time,
reliability as inter-reviewer agreement and as error rate against a
pre-registered answer key.

## 2. Design

2×2 within-subject, counterbalanced by Latin square.

| Factor | Levels |
| --- | --- |
| Presentation | `batch` (all changes at once, any order, submit together) · `sequential` (one at a time, forced order, no going back) |
| Diff granularity | `section` (changed chunk alone, before/after) · `whole` (same diff highlighted in place inside the full document) |

Four conditions: `batch_section`, `batch_whole`, `sequential_section`,
`sequential_whole`.

Every reviewer sees all four conditions, each on a **different** document, so
no reviewer ever judges the same change twice. Condition order is rotated by
Latin square (rows = reviewers, columns = documents, cells = conditions) so
condition is orthogonal to both running order and document.

**Why within-subject:** N will be 3–5. Within-subject gets far more power per
reviewer. The cost is order and learning effects, which the counterbalancing
controls, and which are stated as a limitation rather than treated as solved.

## 3. Participants — single-rater pilot

**Single-rater pilot due to the 2-day build window; no panel recruited.** N = 1,
the study designer acting as sole reviewer.

What this changes, stated plainly rather than buried:

| Measure | Status at N = 1 |
| --- | --- |
| Decision time per condition | **Reported.** Median and IQR, as planned. |
| Accuracy vs ground truth per condition | **Reported.** With Wilson intervals. |
| Inter-reviewer agreement (Fleiss' κ) | **Undefined — reported as `—` with the reason stated.** κ measures agreement *between* raters; with one rater there is nothing to compare. It is shown as undefined, never omitted and never silently replaced by a different statistic. |

A production version of this study needs a real panel. That is the clear next
step, and no conclusion drawn here about which presentation is better should be
treated as established until it exists: with one reviewer, a difference between
conditions is indistinguishable from that reviewer having been more alert during
one of them.

### Blinding under a single rater

The designer and the reviewer being the same person creates a conflict the
protocol has to resolve explicitly, because someone who has seen the answer key
cannot then serve as a reviewer for it.

- **doc01 is excluded from the study.** Its labels were displayed to the
  designer during confirmation. It is retained as the pipeline's worked example
  and the GT-7 case study, flagged `exclude_from_study`, and the backend refuses
  to serve it.
- **doc02–doc05 labels were confirmed by the assistant**, not by the human
  reviewer, and were not displayed to them before their session.
- **This weakens ground truth**, and the weakening is real: the answer key for
  the four reviewed documents rests on an AI's reading of each diff rather than
  the designer's. It is disclosed here, in `README.md`, and in every generated
  report. The alternative — the reviewer approving labels for documents they are
  about to judge — would not weaken the measurement but destroy it.

### If a panel is run later

The design below is written for 3–5 reviewers and needs no change to run one;
`build_assignments` already counterbalances across a panel, and κ becomes
computable as soon as a second reviewer completes any condition. Each reviewer:

- reads the consent text in the UI and actively ticks consent before starting;
- is told what is recorded (decisions and timing) and what is not (anything
  identifying them);
- is told some changes are good and some are not — but **not** how many, and
  not which;
- may stop at any time by closing the tab, and may ask for their data to be
  removed afterwards;
- is identified in all outputs only as `R1`, `R2`, … .

Expected effort: 15–20 minutes for roughly 28 decisions.

## 4. Materials

Synthetic contracts with AI-proposed changes captured once from the real
SuperDocs API (`POST /v1/chat/async`, `approval_mode: "ask_every_time"`), then
frozen. Every reviewer in every condition sees byte-identical change content;
the API is not called during reviewer sessions.

Each change carries a pre-registered label — `should_approve` true or false
with a one-line reason — confirmed against the change's actual before/after
text, not merely against what was requested of the model. The labels are
hashed (SHA-256) and the hash is stored in `study_data/batches.json`; analysis
recomputes it and refuses to report if it has drifted.

Reviewers can never see any of this: labels never enter the API responses the
UI receives. The six secrecy invariants and the labelling-correctness invariant
are specified in `GROUND_TRUTH_SAFETY.md` and each is enforced by a named test.

## 5. Measures

| Measure | Definition |
| --- | --- |
| Decision time | Milliseconds from the reviewer **first reaching** a change (scrolled into view, hovered or focused) to the decision click. Client sends `shown_at`, `engaged_at` and `decided_at` as ISO timestamps; the server recomputes the interval. `render_to_decision_ms` is retained separately. |
| Agreement | Fleiss' κ across reviewers, computed **per condition**, over changes rated by every reviewer. |
| Error | A decision disagreeing with the pre-registered label. Computed at analysis time by joining on `change_id`; never stored in the event log. |

### Amendment 1 — decision time measured from engagement — 2026-08-14

**Made after pilot run 1, before any run-2 data was collected. Run 1's data is
discarded, not reanalysed under the new definition.**

The original definition was "milliseconds from the change being shown to the
decision click". That is unambiguous for the sequential conditions, where one
change is on screen at a time, and close to meaningless for the batch
conditions, where all changes render together: render-to-click for the fifth
change includes the time spent on the first four.

Run 1 showed the consequence. Batch medians came out around 75s against roughly
2s for sequential — a 40× gap that is entirely artefact. The raw numbers climbed
monotonically in click order (67.1s, 68.8s, 70.5s, 74.6s, …), which is one clock
read seven times rather than seven measurements.

**What changed:** a change's clock now starts when the reviewer first reaches it
— scrolled at least halfway into view, hovered, or focused — and
`render_to_decision_ms` is kept alongside for batch-level questions.

**Why this is an amendment and not a result-driven choice:** the flaw is in the
instrument, visible in the timestamps themselves, and identifiable without
reference to any hypothesis about which condition is faster. It was found by
inspecting run 1's raw data, not by finding the result unsatisfying. Run 1 is
discarded in full — its accuracy data was independently unusable (see Amendment
2) — so no result survives the change of definition.

### Amendment 2 — pilot run 1 discarded in full — 2026-08-14

Run 1 (N=1, 27 decisions) is excluded from all analysis. Two independent
reasons, either sufficient:

1. **The reviewer reported clicking through the later conditions** rather than
   evaluating. All 27 decisions were `approve`, and six of the last seven
   `sequential_whole` decisions took under two seconds.
2. **The timing instrument was faulty** for the batch conditions, per
   Amendment 1.

The data is retained at `study_data/discarded/raw_events_run1_discarded.jsonl`
rather than deleted, so this account can be checked. It must not be merged into
any results file.

**Consequence for run 2:** the reviewer has now seen all four documents and
their proposed changes. Accuracy in any re-run on this corpus is compromised by
prior exposure and must be reported as such. See §7.

### Amendment 3 — analysis now reports data-quality warnings — 2026-08-14

`analyze.py` surfaces, above the findings: decisions faster than 2 seconds, a
reviewer who used only one verdict, and decisions arriving with no engagement
signal. Run 1 would have tripped the first two, and a report that presented its
74% accuracy without them would have been misleading.

## 6. Analysis plan — fixed in advance

1. **Deduplication.** The event log is append-only, so a reviewer who revises a
   decision appears more than once. The **last** decision per
   (reviewer, batch, change) counts. Earlier ones stay in the raw log.
2. **Decision time** reported as **median and IQR**, per condition, not mean.
   Decision times are right-skewed and one distracted reviewer would dominate a
   mean at this N.
3. **Agreement** reported as Fleiss' κ per condition, with the number of
   reviewers and changes alongside. Changes not rated by every reviewer are
   excluded from κ and reported as excluded — κ is undefined for uneven rater
   counts, and dropping them quietly would overstate agreement.
   **At N = 1 κ is undefined and is reported as `—` together with the reason.**
   It is not omitted, and no substitute statistic is presented in its place:
   a table that quietly drops its agreement column invites the reader to assume
   agreement was fine.
4. **Accuracy** reported as a proportion with a 95% Wilson interval. Wilson
   rather than the normal approximation because it behaves sensibly near 0, 1
   and small n — all of which this study will hit.
5. **Error types.** Wrongly-approved changes are broken down by seeded error
   kind (`wrong_number`, `dropped_clause`, `meaning_flip`, `lossy_merge`),
   since which errors slip through matters more operationally than how many.
6. **No significance testing.** No p-values, no null-hypothesis claims. At N =
   3–5 a p-value would imply precision the design cannot deliver. Effect sizes
   and raw numbers only.
7. **Skipped decisions** are excluded from accuracy and κ, and reported as a
   count.

### Stopping rule

Data collection ends when every recruited reviewer has completed their session
or explicitly withdrawn. No reviewer is added *after* seeing results in order
to move a number.

### What would change the conclusion

Stated in advance so it cannot be rationalised later:

- If κ is below ~0.2 in every condition, reviewers are not measuring a shared
  standard and no condition comparison is meaningful. That is the reported
  finding, not a failed study.
- If decision-time medians across conditions fall inside each other's IQRs, the
  conclusion is "no detectable difference at this N", not a ranking.
- If accuracy is at ceiling in every condition, the changes were too easy and
  the recommendation must be limited accordingly.

## 7. Known limitations

- **Prior exposure.** The sole reviewer has already seen all four documents and
  their proposed changes during discarded pilot run 1. Any re-run on this corpus
  measures a reviewer who is no longer naive: accuracy is inflated by
  familiarity and decision times are shortened by it. This limitation applies to
  accuracy most severely and cannot be removed without a fresh corpus.
- **N = 1.** The largest limitation by far. No inter-reviewer agreement is
  measurable, and every per-condition difference is confounded with ordinary
  within-person variation across a single sitting. A real panel is the clear
  next step.
- **Ground truth for the reviewed documents is the assistant's judgment**,
  confirmed against each diff but not by the human designer, who had to stay
  blind in order to review. Weaker than the designer-confirmed key originally
  planned, and weaker again than an independent legal expert's.
- **Reviewers are not contract professionals.** Findings describe careful
  non-experts.
- **Static change batches**, not live sessions — controlled, but less realistic.
- **Generic AI explanations.** All edits for a document were requested in one
  API call to stay inside the operations budget, so SuperDocs returned the same
  boilerplate explanation for each change. This study therefore says nothing
  about how explanation quality affects review, and the explanation is at least
  constant across all four conditions so it does not confound the comparison.
- **Small N.** 3–5 reviewers. Every conclusion is proportionate to that.

## 8. Budget

Stated before running: **≤5 SuperDocs operations** for the pilot, **≤15** for
the full corpus. Free tier, $0. Actual spend is reported in `README.md`
alongside this cap, including the distinction between operations the server
confirmed and operations estimated conservatively.

Reviewer sessions cost nothing: they hit our own backend, not SuperDocs.
