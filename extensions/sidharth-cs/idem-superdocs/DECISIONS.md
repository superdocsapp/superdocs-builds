# Decisions, and why

The task card asks for every decision documented with the reasoning. This is
that document. It records the decisions that were taken, the ones that were
rejected, and the two places the design stops short of what would be ideal.

Where a decision came from production evidence rather than from first
principles, the evidence is named.

---

## 1. Why this exists at all

I spent two weeks building ACCORD, a live Zoom document-drafting app, on the
SuperDocs API — roughly 200 real drafting runs between 2026-08-05 and
2026-08-19. The retry problem was not theoretical there:

- A request that times out client-side has an **unknown** state. Operations are
  metered, so retrying risks both a double charge and a double edit. I traced
  **eight duplicate paragraphs** in one document to retries after an ambiguous
  failure.
- `approve_changes(job_id, True)` returned success, the post-approval poll never
  reached terminal, the next `chat_async` returned **409 Conflict**, and
  `revert_session` returned **409** too. Cannot proceed, cannot roll back,
  cannot recover. My retry loop spent about six minutes there before I made it
  fail fast.
- `revert_session` failed two different ways under load: **8× 409 Conflict** and
  **7× 400 Bad Request** across runs.
- Identical input produces materially different output run to run, so "did the
  retry work?" is not answerable from a single observation.

"Idempotency keys on `chat_async`" is the top item in the "what would have
helped most" section of the bug report I sent the founder on 2026-08-22. This
is the follow-through.

## 2. Why the policy is data, and how that is enforced

ACCORD's retry policy today is scattered conditionals. In
`backend/app/drafting/session.py`: the classifier is the helper
`_is_conflict()`, and the decision it drives is written into an
`_unrecoverable` flag at four separate points inside
`_run_gated_operation_impl()` — after a failed approve, after an approve that
never settled, after a failed deny, and after a failed deny-settlement. The
reasoning for each lives in a comment beside that branch. To answer "what do we
do on a 409?" you read the helper and all four branches, and hope you found
them all. To change it, you edit all five and hope the same.

(Referenced by symbol rather than line number on purpose: ACCORD is still being
worked on, and the line numbers this paragraph originally carried were stale
within days.)

Here the same policy is one JSON file. That is the card's requirement, but the
reason it matters is narrower than "data is nicer": **the reasoning travels with
the decision**. Every rule carries its own `why`, and the loader *refuses to
start* if a non-success rule lacks one. An undocumented retry decision is not a
style problem, it is the thing that made the original bug expensive.

The claim is also checkable rather than asserted, so it is checked. A test greps
the runner and the policy loader in both languages for HTTP status literals and
for every error class name the table mentions, and fails if it finds any:
`test_nevers.py::test_policy_is_data_not_conditionals`. The runner branches on
the four abstract outcomes the table returns and on nothing else.

> That test found a real violation on its first run: the word "409" in a
> docstring in `policy.py`. I reworded the prose rather than loosening the
> check. A strict test that needs no exemptions is worth more than a lenient one
> that permits the first exception someone argues for.

## 3. Why 409 is terminal, not retryable

This is the row drawn straight from the evidence. A 409 from SuperDocs means the
session state rejects the call. Two things follow, and only the first is
obvious:

1. The identical call will be rejected identically. Retrying is pure cost.
2. It signals a session that is *already dirty* — something succeeded partially
   and left the session unusable. Retrying does not just fail, it delays the
   discovery that manual recovery is needed.

The rule also carries `requires_reconciliation: true`, so a caller can tell a
"this cannot work" terminal from a "this needs a human" terminal.

Six minutes of looping was the cost of getting this wrong the first time.

**Update, 2026-08-22.** Re-testing live separates two 409s that my original
report ran together. A second call against a session with a job still in flight
409s reliably — that is the serialization constraint, item 10 in the report, and
it is a documented constraint rather than a defect. The wedge proper, where an
approve returns success and the job never settles, **did not reproduce**: the
Review flow ran `awaiting_approval` → approve → `completed` cleanly. One clean
run is not proof of a fix, but it is enough that I will not claim the wedge is
still open. The rule is unchanged, because it is right for both shapes — 409
means this session is not accepting work, whatever put it there.

## 4. Why 5xx is unknown rather than retryable

This is the most common way a retry library double-applies a metered operation,
and it usually looks like a sensible default.

A 5xx means the server received the request. Nothing observable distinguishes
"failed before applying the edit" from "applied the edit, then failed to answer".
A library that assumes the first is guessing, and the guess is only free when
the operation is free. Document edits are not.

## 5. Why the `sent` flag is the most important field in the table

Most retry policies key off the status code. The deeper question is whether the
request ever left the client, because that alone settles whether anything can
have been applied:

| Failure | Sent? | Safe to retry? |
|---|---|---|
| connect timeout, DNS failure, connection refused | no | **yes** — nothing happened |
| read timeout | yes | **no** — the edit may have landed |
| connection reset mid-response | yes | **no** — same |

A connect timeout and a read timeout are both "a timeout" to most code, and they
are opposites here. Telling them apart is most of the value in this library.

The default when nothing attests either way is `sent: true` — fail closed. The
cost of being wrong in that direction is a refused retry the caller can
reconcile. The other direction costs a duplicate metered edit.

## 6. Why `retryable` implies "provably not applied"

An invariant the table must preserve, stated in SPEC.md R10: every rule that
classifies `retryable` does so because the request demonstrably never reached
the server, or because the server explicitly declined to process it. Anything
that merely *might* have been applied classifies `unknown` instead.

That invariant is what makes it safe to **release the key** after exhausting the
retry budget rather than leaving it wedged — no attempt can have had an effect,
so a later caller is genuinely starting fresh. A table that classified a
maybe-applied failure as retryable would break N1 through this door rather than
through the obvious one.

Terminal failures do *not* release the key: the server gave an answer, and
resubmitting the key does not get a second opinion.

## 7. Why unknown outcomes need an explicit policy choice

The card requires it, and it is the right requirement. There is no safe default
for "the edit may or may not have happened", so the default is to stop.

Three choices, deliberately not two:

| Choice | When it is right |
|---|---|
| `REFUSE` (default) | Almost always. Raise, and let a human or an operator decide. |
| `RECONCILE` | When the server can be asked what happened. |
| `RETRY_ANYWAY` | When repeating the operation genuinely cannot change the result. |

`RETRY_ANYWAY` exists because some operations really are safe to repeat, and a
library that pretends otherwise gets worked around — usually by a caller who
wraps it in their own retry loop and loses every other guarantee at the same
time. Better to provide the unsafe path, make it deliberate, and log it.

## 8. Why `RETRY_ANYWAY` takes two arguments instead of one

`on_unknown=RETRY_ANYWAY` alone is refused. The caller must also pass
`naturally_idempotent=True`.

Selecting a policy is the kind of thing that gets copied from a snippet. Making
the unsafe path require a second, separately-named assertion means it cannot be
reached by accident, and it forces the caller to state the fact the safety
rests on rather than merely selecting a mode. It also logs at WARNING every time
it fires, so choosing it once does not make it invisible forever.

## 9. Why reconciliation has three verdicts, not two

`INCONCLUSIVE` is the whole point. A two-verdict probe forces "I could not find
out" into either "it happened" or "it did not", and both are lies.

The dangerous shape is treating the absence of bad news as good news — the probe
errors, the code takes the `else` branch, and the operation is marked applied.
`INCONCLUSIVE` leaves the record `unknown` and keeps it refused.

## 10. Why there are two probes, not one

`job_exists_probe` and `job_settled_probe` answer different questions:

- For a **create**-shaped operation like `chat_async`, the operation *is* the
  creation of the job. If the job exists, the call landed.
- For a **settle**-shaped operation like `approve`, the operation is only
  complete once the job reaches a terminal state. A job that exists but is
  still running is `INCONCLUSIVE`, not `APPLIED`.

That distinction is not academic — it is bug 5 exactly. An approve that returned
success while the job never settled is the wedge. A single probe would have to
guess which question it was answering, and answering "applied" for a job still
in flight is the library inventing the outcome it was built to refuse.

## 11. Why SQLite for the record

The record must survive `SIGKILL` (N4) and the claim must be atomic (R5). SQLite
gives both, is in the standard library of both languages, and adds no
dependency. A JSON file plus a lock would need a write-ahead log to be as
correct as this already is, and would be more code.

`BEGIN IMMEDIATE` takes the write lock before the read, so two callers racing on
one key cannot both observe "absent" and both insert.

## 12. Why full jitter

`delay = uniform(0, min(max, base × multiplier^n))`.

Equal jitter and decorrelated jitter both keep a floor under the delay, which
re-synchronises clients that failed together — the thundering herd you were
trying to avoid. Full jitter has the widest spread, and the spread is the
feature. A 20-second ceiling stays small next to a document edit that runs 30
seconds to several minutes.

## 13. Why the vectors assert delay bounds, not delay values

Seeded random number generators are not portable across languages. A vector that
pinned exact delays would pin one implementation's RNG rather than the specified
behaviour, and the second implementation would be written to match an artefact.

So the vectors assert `0 ≤ delay ≤ min(max_ms, base × mult^n)`. That is the
strongest cross-language assertion that is honest, and SPEC.md says so rather
than hiding it behind a fudged constant. `Backoff.ceiling_ms()` is public in
both implementations for exactly this reason.

## 14. Why zero runtime dependencies

Both implementations use only their language's standard library: Python uses
`sqlite3`, `json`, `random` and `urllib`; TypeScript uses `node:sqlite`. The
dev dependencies are `pytest`, and `typescript` plus `@types/node` for type
checking.

A library whose job is to make failure handling trustworthy is a poor place to
inherit someone else's failure handling. It also means the whole suite runs from
a clean checkout with no install step beyond a virtualenv.

## 15. Why `urllib` in the adapter, and what it costs

`urllib` uses a single timeout covering both connect and read, so it **cannot
distinguish a connect timeout from a read timeout** — the one distinction
section 5 calls the most valuable in the library.

The adapter therefore reports `sent: true` for every timeout, which is the
fail-closed answer: a refused retry the caller can reconcile, rather than a
duplicate edit. The cases urllib *can* tell apart — connection refused, DNS
failure — are attested correctly as `sent: false`.

This is a real cost, taken knowingly to keep the dependency count at zero. The
upgrade path is one line: `httpx` distinguishes `ConnectTimeout` from
`ReadTimeout` natively, and the table already has a rule for each, so swapping
the transport needs **no policy change**. That is the payoff of keeping the
policy in data, demonstrated rather than claimed.

The `sent` judgement gained a third never-sent case from the live run, and it is
worth recording how. The first live attempt failed on a TLS certificate error
and spent nothing — the handshake never completed, so no request existed. But
the adapter reported it as *sent*, and the library therefore refused an
operation that provably could not have happened. Wrong in the safe direction,
which is the direction that hides: the refusal looked exactly like a correct
refusal. `ssl.SSLError` now sits alongside `ConnectionRefusedError` and
`socket.gaierror`, with a test. A run that never reached the server still found
a bug in how the library talks to it.

## 16. What the second implementation actually caught

The card asks for two implementations verified against the same vectors. The
honest question is whether that is worth doing or just twice the work. In this
build it paid for itself once, concretely:

Running twelve processes at a single key, TypeScript children died
intermittently with `database is locked` — roughly one run in three, which is
the worst frequency a bug can have.

The cause turned out to be an ordering bug, and finding it took surfacing the
child's stderr into the assertion message rather than reporting a bare exit
code. `node:sqlite` sets no busy timeout by default. Python's `sqlite3` takes
one as a *connect argument*, so it is in force before any statement runs. My
first fix added `PRAGMA busy_timeout` but placed it **after**
`PRAGMA journal_mode=WAL` — and setting the journal mode needs an exclusive
lock. With no timeout yet in force, two processes opening the same database at
the same moment threw immediately, before the schema even existed.

Three things worth recording:

1. **The safety property held throughout.** `applies` was 1 in every single
   run, including the failing ones. The contended caller failed loudly instead
   of double-applying — fail-closed working as designed, under a fault I had
   not anticipated and against a bug I had not yet found.
2. Python's API makes this mistake unavailable: a connect-time argument cannot
   be ordered after a statement. The Python suite could not have found it.
3. The first fix looked correct and passed several runs. An intermittent
   failure that a rerun makes disappear is the shape that gets shrugged off; the
   only reason it did not was a 20-run loop.

Fixed by setting `busy_timeout` **before** `journal_mode`, matched to the Python
client's own 10s timeout. Verified across 20 consecutive runs of the fault
harness, all clean.

### 16a. Measuring a test's sensitivity, not just its colour

A later pass turned the mutation audit on the concurrency tests specifically,
and both languages failed the same way for the same reason.

Contending on **one** key gives the racing callers exactly one chance to hit the
window where two of them both see "absent". Process spawn overhead staggers them
by tens of milliseconds; thread scheduling is kinder but not reliable. Measured
against a deliberately weakened claim (`BEGIN IMMEDIATE` → `BEGIN DEFERRED`):

| | detection rate |
|---|---|
| TypeScript, 12 processes, 1 key | 0/1 — undetected entirely |
| Python, 20 threads, 1 key | 9/12 trials |
| both, after: barrier + 60 keys | 12/12 |

Both were passing the whole time. A green concurrency test says nothing about
whether it can *see* a broken lock, and the only way to find out is to break the
lock and count. The fix adds no test and changes no behaviour — it makes an
existing test able to detect what it already claimed to.

The Python figure is the more instructive one. 9 out of 12 is the worst possible
result: frequent enough to look like a working test, rare enough that a reviewer
who runs it once will probably see it pass.

## 17. Decisions not taken

**A server-side idempotency key.** Out of scope: it is a platform feature, not a
client one, and it is the thing this build exists to argue for. See section 18.

**Automatic key generation from the request body.** Rejected. A caller who
cannot name its operation stably does not have an idempotent operation, and
hashing the body would hide that behind a key that looks stable and is not — two
semantically identical edits with different whitespace would get different keys
and both apply. R1 makes keys the caller's responsibility on purpose.

**Making the loser of a concurrent claim wait for the winner.** Rejected as
more code and more failure modes (deadlock, poll intervals, timeouts) than the
problem justifies. The loser raises `OutcomeUnknown`, which is honest: from its
point of view the outcome genuinely is not known yet. Executions stay at one,
which is the property that matters.

**Async APIs.** Both implementations are synchronous. The library's work is
bookkeeping around a call the caller makes; making that async would have doubled
the surface for no behavioural gain. The caller's `fn` can do whatever it likes.

**Retrying inside the reconciliation probe.** Rejected. A probe that retries can
hang the refusal path, which is the one path that must stay fast and
predictable.

**A pluggable store interface.** Rejected as speculative. There is one store and
it is SQLite. An interface with one implementation is a guess about a second one.

## 18. Where this stops, and why that is a platform problem

Reconciliation needs something to reconcile against. The library binds
`key → job_id` the moment a job id is first seen, and the default probe asks the
server about that job.

When the **first** call is the one that times out, there is no job id yet, and
SuperDocs offers no lookup by operation key. The server may well have created a
job; the client cannot find out. `reconcile()` returns `INCONCLUSIVE` and the
operation stays refused.

A client library can make retries safe exactly up to the point where the server
can say what happened. Closing the last gap requires the server to accept the
operation key and return the original outcome on a repeat — which is the
platform feature at the top of my bug report, and the reason this card exists.

The escape hatch is a caller-supplied `probe`, which can answer the question
another way: for a document operation, by asking whether the document already
contains the edit. `test_faults.py::test_network_partition_resolves_when_the_server_can_answer`
shows what becomes possible the moment the server can answer, and
`..._stays_refused_when_the_server_cannot_answer` shows the state of things
today. Both are in the suite, because the gap is part of the design and not an
embarrassment to hide.
