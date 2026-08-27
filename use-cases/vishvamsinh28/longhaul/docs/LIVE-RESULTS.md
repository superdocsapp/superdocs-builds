# Running it against the live API

Everything else in this repository runs offline against a deterministic stand-in. This
page records what happened when the same job ran against `api.superdocs.app`, including
the things that broke.

**Cost: 8 operations.** The account reported 492 remaining afterwards. Uploads, exports
and every read used here are free; only edit turns bill.

## The run

The compact job — three synthetic runbooks, eight steps — on 27 August 2026.

| | |
|---|---|
| Steps planned | 8 |
| Chat jobs created on the session | **8** |
| Turns issued more than once | **0** |
| Changes approved / rejected | 4 / 2 |
| Billable operations | 8 |
| Status | `completed` |

A second run, after the verification pass below was added, reported **`blocked`** on the
same job — because two of its steps had not actually done what they said. That is the
system working, not failing.

Verified against the server's own transcript rather than the runner's account of itself:
each of the eight idempotency tokens appears exactly once, and the session holds exactly
eight chat jobs for eight steps.

This was not a clean run. It survived, in order:

1. **An operator interrupt** partway through, leaving a job `awaiting_approval`.
2. **A destroyed ledger** — the local database was deleted while the server kept everything.
3. **A process kill** during the approve call, in window W2.
4. **Two code changes deployed mid-run**, both fixing bugs the live API had just exposed.

Eight steps, eight jobs, no duplicates. The interruptions were real and unplanned, which
makes the result worth more than the clean run that was originally intended.

Final documents, each verified after export:

| Document | Outcome |
|---|---|
| `oncall-rotation` | paging tool renamed, role renamed, new section added over **two review rounds** |
| `security-incident` | paging tool renamed; the sentence Legal owns **kept its original wording**, because the gate rejected that change and the system respected it |
| `status-page` | duplicated section removed; nothing to rename, and correctly **billed 0** |

## What broke

Five findings. Three are mine, one is a rough edge in the product, and the last is the
one that matters most operationally.

### 1. One instruction can need several rounds of review — mine

`add a section titled X containing Y` came back as an `<h2>` heading in the first round
and its `<p>` paragraph in a second round of the *same* turn. My runner assumed one round:
it approved the heading and then waited indefinitely on a job that was patiently asking
about the paragraph.

The documentation does warn about this — "your polling loop should handle multiple rounds
of `awaiting_approval`, not just one" — and I built for a single round anyway. Fixed, and
the stand-in now reproduces the two-round shape so the tests cover it.

Fixing it exposed a second bug of mine immediately: recovery read `awaiting_approval` as
"the approve did not land", when after a successful approve it can equally mean "it landed
and the next round began". Replaying there re-applied the earlier round. The kill-point
proof caught this within one run.

And that fix exposed a third: the commit log was re-appending earlier rounds' changes on
every later round, so one change was recorded as two. The audit trail now holds exactly
one row per change.

### 2. The ledger can be behind the server — mine

Killing a *process* leaves the ledger intact, so 119 kill points could never reach this.
A ledger that is lost, restored from an older backup, or rolled back leaves steps reading
`PLANNED` for work the server has already done — and re-issuing there applies the edit
twice.

This surfaced as a `409 session_busy` on a brand-new run, because the previous run had
left changes staged. Every step now checks the transcript for its own token before
issuing, not only the steps the ledger admits were in flight.

### 3. Export has no per-document selector — a rough edge worth reporting

`POST /v1/documents/export` accepts `html`, `session_id` or `upload_id`. In a
multi-document session, exporting by `session_id` returns whichever document is **focused**
— there is no documented way to name a different one.

I had been passing `document_id` in the payload. **It is accepted and silently ignored.**
Three exports came back byte-identical, all of them the focused document, while the real
edits sat correctly on the server. A `422` on the unknown field would have caught this
immediately; the silent acceptance is what made it look like it worked.

Worked around by reading each document's HTML from the session roster and exporting that
directly. Both calls are free and, unlike switching focus, it mutates nothing.

*Suggestion:* either accept `document_id` on export, or reject unknown fields.

### 4. `metadata.awaiting_kind` is absent on change-review pauses — minor

The documentation says to branch on `metadata.awaiting_kind` to tell a HITL change review
apart from a large-edit continue prompt. On every change-review pause observed here the
field was **absent**, not `"change_review"`. Branching on `== "continue_prompt"` is
therefore safe, but code written to check `== "change_review"` — which the docs invite —
would never match.

### 5. The model silently skipped 2 of 8 replacements — the most important finding here

A step told to replace `"PagerDuty"` with `"Rootly"` returned **no proposed changes** for
a document that plainly contained "PagerDuty". The same happened for `"Ops Lead"` in
another document. Both steps were recorded as done, with zero changes and zero cost.

Nothing in the runner was wrong: it faithfully recorded that the model proposed nothing.
That is precisely the problem — **"there was nothing to do" and "I missed it" are
indistinguishable from the inside.** A run of eight steps reported success while two
documents still said the thing the job existed to remove.

For the ops team this is built for, that is the worst possible failure: not a crash, not a
duplicate, but a quiet, confident, wrong "done".

Fixed by checking the document afterwards. Every step now carries an expectation derived
from its own instruction — a `replace "X" with "Y"` directive already states that X must
not remain — and the document the server holds is checked against it once the step
finishes. The check costs nothing, because reading a document is free.

It distinguishes three outcomes, because they mean different things:

| Outcome | Meaning |
|---|---|
| `verified` | the document matches |
| `unmet: a reviewer rejected the change…` | a person chose this. Not a defect |
| `unmet: nothing was proposed…` | **the step did not do its job.** The run reports `blocked` |

A fourth exists for a step adopted after a ledger loss, where the record that would
explain the mismatch is gone: it says so rather than guessing.

Only the negative half of an expectation is derived. "X must not remain" is true whether
or not the document ever contained X; "Y must appear" is not, and asserting it would fail
every document the step correctly left alone.

## What the live run confirmed

- **The idempotency token survives in the session transcript**, exactly as the design
  depends on. This is what lets a crashed run ask the server whether a turn happened, and
  it is the single load-bearing assumption in the whole project.
- **Session history does not expire**, unlike jobs, which are purged an hour after
  creation.
- **Rejected changes are not billed.** Step 4's rejection left the account's remaining
  count unchanged.
- **A turn with nothing to change is not billed either.** Step 2 found no occurrences and
  cost nothing.
- **The double-parse trap is real**: proposed-change content arrives JSON-encoded inside
  JSON on the live API too.
- **Latency**: 13–16 seconds for a single-section edit, matching the documented range.

## What is still not proven live

Byte-identity across a restart. It is proven offline across 119 kill points against a
deterministic backend, and it is *not true* against a live model, which produces different
prose on every run. The claim that holds live is at-most-once, and that is the one that
costs money to get wrong. See the README for why these are kept apart.
