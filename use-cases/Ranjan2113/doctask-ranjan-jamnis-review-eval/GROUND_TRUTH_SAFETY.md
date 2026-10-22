# Ground-truth safety invariants

Written **before** the labelling code, per the convention in Task 1's
`TASK.md`: state what the system must never do, then the test that proves it,
then the code.

Why this file exists: the entire error-rate measurement is worthless if a
reviewer can tell, by any route, which changes are seeded-bad. A leak does not
announce itself — it shows up as suspiciously high accuracy that reads like a
finding. These are the leak routes I can think of, and each has a test.

Tests live in `tests/test_ground_truth_safety.py`. Invariant IDs are cited in
the test names so the mapping stays honest.

---

## GT-1 — The label must never reach a reviewer-facing payload

No object served to the reviewer UI may contain `should_approve`,
`ground_truth`, `gt_reason`, or anything computed from them.

**Enforced by construction, not by filtering.** The reviewer view is built by
an explicit field **whitelist**. A blacklist would mean that any field added to
the ground-truth record in future leaks by default until someone remembers to
censor it. The whitelist fails closed: a new field is invisible until
deliberately published.

*Test:* build a reviewer payload from a batch whose ground-truth records carry
a deliberately-named `should_approve` plus a novel `secret_future_field`, then
assert neither appears anywhere in the serialized JSON, at any nesting depth.

## GT-2 — Presentation order must never correlate with the label

If seeded-bad changes cluster (all last, or alternating), a reviewer learns the
pattern within one batch and their later decisions stop being independent
judgments.

Order is a deterministic seeded shuffle, recorded in the batch so a session can
be reproduced exactly.

*Test:* across many seeds, the mean rank of `should_reject` changes must not sit
at an extreme of the distribution; and a fixed seed must reproduce a fixed
order.

## GT-3 — Identifiers must never encode the label

No `change_id`, DOM id, CSS class, array index, or filename may be derived from
the label. `bad_003` in the markup is a leak that survives every other
precaution, because a curious reviewer reads the page source.

Reviewer-facing ids are opaque and assigned **after** shuffling.

*Test:* assert reviewer-facing ids are drawn from an opaque alphabet and that
partitioning ids by ground-truth label yields no separating prefix, suffix, or
ordering.

## GT-4 — Ground truth must never be edited after reviewer data exists

The labels are a pre-registration. Editing one after seeing that reviewers
disagreed with it converts the measurement into a post-hoc rationalisation,
which is exactly the failure mode pre-registration is supposed to prevent.

The batch file records a `pre_registered_at` timestamp and a SHA-256 over the
canonical ground-truth block. `analysis.py` recomputes that hash and refuses to
report if it has drifted.

*Test:* mutate one label in a written batch file, re-verify, and assert the
verification raises rather than warns.

## GT-5 — The base rate must never be inferable from the reviewer's view

Telling a reviewer "3 of these 7 are wrong" turns the task into a constrained
assignment problem and inflates measured accuracy. Neither the count nor the
ratio of seeded-bad changes may appear in reviewer-facing data, instructions,
or UI copy.

The number of bad changes per batch also varies between batches, so a reviewer
cannot learn a constant from their first condition and apply it to the rest.

*Test:* assert no reviewer payload carries a bad-count/ratio field, and that
the corpus's per-batch bad counts are not all identical.

## GT-6 — Ground truth must never be written to the event log

`raw_events.jsonl` is append-only, published with the study, and read by
analysis. Scoring joins events to ground truth **at analysis time** by
`change_id`. The event record itself stores only what the reviewer did.

If ground truth were denormalized into the event log, GT-4 would be
unenforceable — there would be two copies to keep honest — and the published
raw timings would hand the answer key to anyone who read them.

*Test:* assert a constructed decision event contains no ground-truth-derived
key, and that scoring still works via join.

## GT-7 — A label must never be pre-registered without being confirmed against the change it labels

Added 2026-08-14, after the live pilot produced a wrong label. This is the
invariant the original six missed: GT-1 to GT-6 all guard the answer key's
*secrecy* while silently assuming its *correctness*.

The corpus asks SuperDocs for a specific edit and pre-labels it from the
intent. The pilot showed execution can diverge from intent far enough to flip
the label. `g_wordiness` asked for a concise rewrite "without changing any
obligation" and was pre-labelled `should_approve`; what came back replaced the
Vendor's entire performance obligation with "The parties agree to the terms
herein." The right label for the change that actually arrived is
`should_reject`.

A wrong key does not fail loudly. It yields a plausible accuracy number that is
quietly wrong, and scores every reviewer who correctly rejected that change as
having made an error — inverting the exact measurement the study exists to
produce.

So an intent-derived label is **provisional**. Promotion to pre-registered
requires a human to have compared the label against the change's real
`old_html` and `new_html`. `build_batch` refuses to build from provisional
labels rather than falling back to the intent.

*Test:* assert `build_batch` raises on any unconfirmed label; assert a
confirmed label carries a `confirmed_at` stamp and the reviewer's verdict, not
the intent's; assert confirmation can *change* a label and that the change is
recorded rather than silently overwriting.

---

## Deliberately *not* an invariant

**Reviewers may be told the study measures accuracy.** Informed consent
requires it, and it does not reveal which changes are bad. What they are not
told, until debriefing, is the base rate (GT-5).

**Ground truth is the designer's judgment, not an independent expert's.** That
is a stated limitation of the study (`PLAN.md.pdf` §3), not something these
invariants can fix. Keeping it secret from reviewers is still necessary; it
just is not sufficient to make the labels authoritative.
