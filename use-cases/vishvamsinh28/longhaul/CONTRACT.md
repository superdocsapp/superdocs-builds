# The durability contract

Written before the implementation, on purpose. Each invariant names the test that proves it.
If an invariant and the code ever disagree, the invariant is right and the code is a bug.

## What this system must never do

1. **It must never apply the same edit twice.** A crash at the worst possible instant — after the
   request left the process, before the answer was durably recorded — must not turn into a second
   edit against the document.
2. **It must never silently skip a step.** A step that was never executed must never be reported
   as done.
3. **It must never guess.** When the evidence for "did this land?" is genuinely inconclusive, the
   run halts and says so. Guessing wrong in either direction is worse than stopping.
4. **It must never take instructions from the documents it edits.** Source content is data to
   report on, never commands to obey.
5. **It must never report success for work that is not in the state it claims.**

## The five invariants

### I1 — at-most-once issuance

No step's edit instruction reaches SuperDocs more than once, across any number of crashes at any
point in the step lifecycle.

> Proven by `tests/test_at_most_once.py` and by the per-kill-point commit-log equality assertion in
> `tests/test_kill_points.py`. The fake server counts every chat turn it receives and the assertion
> is on that count, not on anything the runner reports about itself.

### I2 — no step is skipped

Every planned step reaches a terminal state (`DONE`, `REJECTED`, `FAILED`, `ADJUDICATE`) before the
run reports completion. A run that cannot reach a terminal state for some step reports `blocked`,
never `completed`.

> Proven by `tests/test_at_most_once.py::test_no_step_is_skipped` and by the commit-log equality
> assertion across every kill point.

### I3 — a restart is invisible in the output

Given a deterministic backend, the document exported after an interrupted-and-resumed run is
byte-identical to the document exported by the same run completed without interruption.

> Proven by `tests/test_kill_points.py` across every checkpoint a real run traverses (>=20 required
> by the brief; the suite generates ~70). Each kill is a real `SIGKILL` to a real subprocess.
>
> **Scope of this claim.** Determinism is a property of the runner, not of a language model. The
> proof runs against a deterministic fake so that the only variable is the runner. Against the live
> API the provable claim is I1, not I3 — see README, "What is proven and what is not".

### I4 — the resume point is recoverable from durable state alone

The decision about what to do next is computed from the ledger and from SuperDocs' own server-side
state. Nothing carries over in memory, because after a `SIGKILL` there is no memory to carry.

> Proven by `tests/test_reconcile.py::test_cold_resume_uses_no_in_memory_state`, which resumes from
> nothing but a database path in a process that never saw the first run, and by every kill point in
> the proof suite being a real process death.

### I6 — the ledger may be behind the server, and that must not cause a second edit

A step can read ``PLANNED`` while its turn has already been issued: the ledger was lost,
restored from an older backup, or rolled back, while SuperDocs kept everything. Every step
therefore checks the session transcript for its own token *before* issuing — not only the
steps the ledger admits were in flight.

> Proven by `tests/test_ledger_behind_server.py`.
>
> **This invariant was added after a live run, not before it.** Killing a process leaves
> the ledger intact, so no number of kill points can reach this case; the proof suite was
> structurally blind to it. A real interrupted run against api.superdocs.app left changes
> staged for review, the ledger was replaced, and the next instruction came back
> `409 session_busy`. The gap was real, the tests that now cover it fail without the fix,
> and the honest record is that the offline proof did not find it.

### I5 — the report is honest

Every step in the run report carries the disposition that actually applied and the evidence that
decided it:

| Disposition | Meaning |
|---|---|
| `executed` | issued during this attempt |
| `skipped: already-done (ledger)` | already terminal in the ledger before this attempt |
| `skipped: already-done (reconciled)` | found to have landed on the server; adopted, never re-issued |
| `adjudicate` | evidence inconclusive; run halted for a human |

A step is never reported as done without a durable record of the commit that made it so.

> Proven by `tests/test_report.py`.

## The two dangerous windows

Both live inside a single step, and they are not symmetrical.

**W1 — `ISSUING -> ISSUED`.** The chat turn has been sent; the `job_id` has not been recorded. This
is the unsafe window: a blind retry here applies a second edit to the document. Closing it is what
`reconcile.py` exists for.

**W2 — `COMMITTING -> COMMITTED`.** The approve call has been sent; the outcome has not been
recorded. This window is safe to retry, because an approve names an existing `job_id` and existing
`change_id`s — replaying it cannot create an edit that did not already exist as a proposal.

Treating these two as if they were the same problem is the mistake this design exists to avoid.

**W3 — the whole ledger.** Not a window inside a step but underneath all of them: the ledger
itself can be behind the server. See I6. This one does not come from a crash at all, which is
why an offline proof built entirely on killing processes could never have found it.

## Order of work

Contract, then the test, then the code. In that order, for the hard part.
