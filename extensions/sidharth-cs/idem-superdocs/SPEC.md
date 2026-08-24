# Specification — idempotency and safe-retry middleware

Version 1. Normative. This document is the single source both implementations
are written from; neither implementation is the specification.

Requirements are numbered `R1`..`R13`. Every requirement is pinned by at least
one behavioural vector in `vectors.json`, which both implementations execute.
Every "never" in §1 is pinned by a named test.

---

## 1. What the system must never do

Written before the code, in this order, because a retry library that is
merely *usually* correct is worse than no retry library: it converts a visible
failure into an invisible one.

| # | The system must NEVER | Proven by |
|---|---|---|
| N1 | Execute the same operation key twice | `test_nevers.py::test_completed_key_replays_recorded_result` |
| N2 | Retry an operation whose outcome is unknown, without an explicit policy choice | `test_nevers.py::test_unknown_refuses_by_default` |
| N3 | Report a success it did not observe | `test_nevers.py::test_never_synthesises_success` |
| N4 | Lose the record of an in-flight operation across a process restart | `test_faults.py::test_process_restart` |
| N5 | Retry a failure the decision table marks terminal | `test_nevers.py::test_terminal_is_not_retried` |
| N6 | Let two concurrent callers both execute the same key | `test_faults.py::test_duplicated_request` |

N1 is the double-charge and the double-edit. N2 is the reason this library
exists at all. N3 is what makes the other five checkable — a library allowed
to invent a success can satisfy every other rule and still be useless.

---

## 2. Vocabulary

**Operation key** — a caller-supplied string that identifies one logical
operation. Two calls with the same key are the same operation, however many
times they are submitted.

**Attempt** — one execution of the caller's function. An operation may have
several attempts.

**Outcome** — the classification of an attempt, decided only by the decision
table: `success`, `retryable`, `terminal`, or `unknown`.

**Record** — the durable local row for a key: its state, attempt count, the
recorded result on success, and the job id if one was seen.

---

## 3. States

```
NEW ──claim──▶ IN_FLIGHT ──success────────▶ SUCCEEDED   terminal, result recorded
                   │
                   ├──retryable──▶ jittered sleep ──▶ IN_FLIGHT
                   ├──terminal───▶ FAILED               terminal, never retried
                   └──unknown────▶ UNKNOWN              refused; needs a policy choice
```

`SUCCEEDED` and `FAILED` are terminal: the operation is over and its answer is
fixed. `UNKNOWN` is not terminal and is not retryable. It is a state that
requires a decision from outside the library, which is the whole point.

An `IN_FLIGHT` record found at startup by a *different* process is treated as
`UNKNOWN`: the process that owned it died without recording an outcome, so
nothing is known about whether the request reached the server. See R2, N4.

---

## 4. Requirements

### Identity and durability

**R1.** Operation keys are supplied by the caller. The library never generates,
derives, or hashes a key. A caller that cannot name its operation stably does
not have an idempotent operation, and hiding that behind a generated key would
produce silent double-application.

**R2.** The record is durable across process exit, including `SIGKILL`. State
held only in memory cannot satisfy N4.

**R3.** `run()` on a key whose record is `SUCCEEDED` returns the recorded
result and does not execute the caller's function.

**R4.** `run()` on a key whose record is `FAILED` raises `TerminalFailure` and
does not execute the caller's function.

**R5.** Claiming a key is atomic. Two concurrent callers of the same key
produce at most one execution; the loser observes the winner's record rather
than executing.

### The decision table

**R6.** The outcome of an attempt is determined only by the decision table in
`policy.json`. Rules are evaluated top to bottom, first match wins, and the
table must end with a catch-all.

**R7.** The table is data. The runner contains no conditional on an HTTP status
code or an error class name. This is checkable, and it is checked:
`test_nevers.py::test_policy_is_data_not_conditionals` greps the runner source
for status literals and error-class names and fails if any appear.

**R8.** An unrecognised failure classifies as `unknown`, never as `retryable`.
The table fails closed.

**R9.** A rule may carry `honour_retry_after`. When it does and the response
supplies `Retry-After`, that value replaces the computed backoff.

### Retry and backoff

**R10.** `retryable` outcomes are retried until `max_attempts` is reached, then
`RetriesExhausted` is raised and the key is released back to `NEW`.

> This rests on an invariant the table must preserve: **`retryable` implies
> provably not applied.** Every rule that classifies `retryable` does so
> because the request demonstrably never reached the server, or because the
> server explicitly declined to process it. Anything that merely *might* have
> been applied classifies `unknown` instead. That invariant is what makes it
> safe to release the key after exhaustion rather than leaving it stuck: no
> attempt can have had an effect, so a later caller is starting genuinely
> fresh. A table that classified a maybe-applied failure as `retryable` would
> break N1 through this door.

**R11.** Backoff is full jitter: the delay for attempt *n* (0-indexed) is drawn
uniformly from `[0, min(max_ms, base_ms * multiplier**n)]`.

> Vectors assert the delay's **bound**, not its value. Seeded random number
> generators are not portable across languages, so a vector that pinned exact
> delays would pin one implementation's RNG rather than the specified
> behaviour. Bounds are the strongest cross-language assertion that is
> honest.

### Unknown outcomes

**R12.** An `unknown` outcome is never retried without an explicit policy
choice from the caller. The choices are:

| `UnknownPolicy` | Behaviour |
|---|---|
| `REFUSE` (default) | Raise `OutcomeUnknown`. A human decides. |
| `RECONCILE` | Run `reconcile()`, then act on its verdict. |
| `RETRY_ANYWAY` | Retry regardless. Requires the caller to *also* pass `naturally_idempotent=True`, and logs at `WARNING` every time it fires. |

`RETRY_ANYWAY` exists because some operations genuinely are safe to repeat, and
a library that pretends otherwise gets worked around. It costs two deliberate
arguments rather than one, so it cannot be reached by accident or by copying a
snippet.

**R13.** `reconcile(key, probe)` is public and callable on its own, not only
from inside `run()`. It returns one of three verdicts:

| Verdict | Effect |
|---|---|
| `APPLIED` | Record becomes `SUCCEEDED`. The function is never re-executed. |
| `NOT_APPLIED` | Record becomes safe to retry. `run()` may proceed. |
| `INCONCLUSIVE` | Record stays `UNKNOWN`. Still refused. |

The default probe reads the server's job state. `INCONCLUSIVE` is a first-class
answer, not an error: see §6.

---

## 5. The decision table

`policy.json` is loaded identically by both implementations. Each rule carries
its own `why`, so the reasoning lives with the decision rather than in a
comment beside a branch somewhere in the runner.

The classifications that matter, and why they are what they are:

| Observation | Outcome | Reasoning |
|---|---|---|
| 2xx | `success` | Observed. |
| connect timeout, DNS failure | `retryable` | The request never left the client, so nothing can have been applied. This is the only timeout that is safe to retry. |
| read timeout after send | `unknown` | Sent, no answer. The metered edit may have happened. |
| connection reset after send | `unknown` | Same shape as a read timeout. |
| 5xx | `unknown` | The server received the request. Nothing observable distinguishes "failed before applying" from "applied, then failed to answer". |
| 429 | `retryable` | The server explicitly declined to process it. `honour_retry_after`. |
| 409 | `terminal` | The remote state rejects this call. Retrying is guaranteed to fail again *and* signals a dirty session. |
| other 4xx | `terminal` | A client-side defect. The same request will be rejected identically forever. |
| anything else | `unknown` | Fail closed (R8). |

The 409 row is the one drawn directly from production evidence rather than from
first principles. See `DECISIONS.md` §3.

---

## 6. The limit of what a client can do

Reconciliation needs something to reconcile against. The library records the
`key → job_id` binding the moment a job id is first observed, and the default
probe asks the server for that job's state.

When the *first* call is the one that times out, there is no job id yet, and
the server offers no lookup by operation key. The server may have created a
job; the client cannot find out. `reconcile()` returns `INCONCLUSIVE` and the
operation stays refused.

This is a real limit, stated rather than hidden. A client library can make
retries safe exactly up to the point where the server can say what happened.
Closing the last gap requires the server to accept the operation key and
return the original outcome on a repeat — which is the platform feature this
build was written to argue for.

The escape hatch is a caller-supplied `probe`, which can answer the question
some other way — for a document operation, by asking whether the document
already contains the edit.

---

## 7. Public surface

Deliberately small: one class, two methods, one enum, three exceptions.

```
Idempotent(store_path, policy, *, job_probe=None, sleep=..., rng=..., extract_job_id=...)
  .run(key, fn, *, on_unknown=REFUSE, probe=None, naturally_idempotent=False) -> result
  .reconcile(key, probe=None) -> Verdict

UnknownPolicy    REFUSE | RECONCILE | RETRY_ANYWAY
Verdict          APPLIED | NOT_APPLIED | INCONCLUSIVE

OutcomeUnknown      the outcome is unknown and no policy authorised a retry
TerminalFailure     the table classified the failure terminal
RetriesExhausted    max_attempts reached on a retryable failure
```

`fn` takes no arguments and returns the operation's result. It raises to signal
failure. The library inspects the raised exception for a `status` (or a
`response.status_code`) and for whether the request was sent, and hands those
to the table. It never imports an HTTP library to do so.

---

## 8. Requirement coverage

Ten of the thirteen requirements are pinned by behavioural vectors, which both
implementations execute. The other three are structural or durability
properties that a scripted sequence of attempt outcomes cannot express, so each
is pinned by a named test instead. R11 appears twice: a vector can bound a
delay, but only a distribution test can show it is actually jittered.

| Requirement | Pinned by |
|---|---|
| R1 keys are caller-supplied | `test_nevers.py::test_library_never_generates_a_key` |
| R2 durability across process exit | `test_faults.py::test_process_restart` |
| R3 replay of a succeeded key | `V02` |
| R4 replay of a failed key | `V14` |
| R5 atomic claim | `test_faults.py::test_duplicated_request` |
| R6 outcome decided by the table | `V01 V03 V05 V06 V08 V16` |
| R7 the table is data, not conditionals | `test_nevers.py::test_policy_is_data_not_conditionals` |
| R8 unrecognised failures fail closed | `V15` |
| R9 Retry-After honoured | `V17` |
| R10 retry budget and key release | `V03 V04 V19` |
| R11 full-jitter bounds | `V18` |
| R11 full-jitter *distribution* | `test_nevers.py::test_backoff_is_not_a_constant`, `::test_backoff_spreads_across_its_whole_range`, `::test_backoff_mean_matches_full_jitter` |
| R12 unknown needs an explicit policy | `V07 V12 V13` |
| R13 reconcile's three verdicts | `V09 V10 V11` |

Two further properties are not numbered requirements — they were not foreseen
when this document was written — but are load-bearing enough to be pinned:

| Property | Pinned by |
|---|---|
| A `NOT_APPLIED` verdict releases the key and never succeeds it | `test_nevers.py::test_not_applied_releases_the_key_it_does_not_succeed_it`, `::test_only_applied_may_produce_a_succeeded_record` |
| The store holds no file descriptors open between operations | `test_nevers.py::test_the_store_does_not_leak_file_descriptors` |

Both were found by testing rather than by design — the first by mutation
testing, the second by the fuzzer. Recorded here because a specification that
silently absorbs its own bug fixes teaches nothing.

---

## 9. Behavioural vectors

`vectors.json` is the cross-language contract. Each vector names the
requirement it pins, supplies a scripted sequence of attempt outcomes, and
states the expected final state, execution count, and raised error.

```json
{
  "id": "V07-read-timeout-refuses",
  "requirement": "R12",
  "attempts": [ { "event": "error", "class": "ReadTimeout", "sent": true } ],
  "on_unknown": "refuse",
  "expect": { "final_state": "unknown", "executions": 1, "raised": "OutcomeUnknown" }
}
```

`executions` is the assertion that matters. It counts how many times the
caller's function actually ran, which is the observable form of "did we
double-apply".

Sleep is injected in both implementations, so the suite is deterministic and
never actually waits.
