# Longhaul

**A durable runner for SuperDocs editing jobs that outlast one sitting.**

An ops team has forty runbooks and one migration to apply across all of them. That is a
job measured in hours, not minutes — and something always interrupts it. A laptop sleeps,
a deploy restarts the worker, someone hits ctrl-C, the process is OOM-killed at 3am.

The expensive question the next morning is not "where did it stop?" It is **"did that
last edit actually happen?"** Get it wrong in one direction and a step is silently
skipped. Get it wrong in the other and an edit is applied to the document twice.

Longhaul is built so that question always has an answer, and never a guess.

```bash
make live      # the operator console, against the real SuperDocs API
make proof     # kill a run and resume it, diff the result — offline, six seconds
```

![The console, live against api.superdocs.app](docs/console.png)

That is a real run against `api.superdocs.app`: every call it makes is on the right, with
status and timing; what it has spent is in the header; and two steps are flagged **unmet**
because the model quietly skipped them — see below.

---

## It refuses to say "done" when it isn't

The most useful thing this build does came out of running it live, and it is not the
durability.

A step told to replace `"PagerDuty"` with `"Rootly"` returned **no proposed changes** for a
document that plainly contained "PagerDuty". Across one eight-step run this happened
twice. Nothing in the runner was wrong — it faithfully recorded that the model proposed
nothing. That is exactly the problem: *"there was nothing to do"* and *"I missed it"* are
indistinguishable from the inside, and the run reported success while two documents still
said the thing the job existed to remove.

For an ops team, that is the worst failure available: not a crash, not a duplicate, but a
quiet, confident, wrong "done".

So every step now carries an expectation taken from its own instruction — `replace "X"
with "Y"` already says X must not remain — and the document the server holds is checked
against it once the step finishes. Reading a document is free, so the check costs nothing.
A run with an unmet expectation and nothing proposed reports **`blocked`**, never
`completed`.

It tells apart the three ways this can go, because they mean different things: the
document matches; a reviewer rejected the change (a decision, not a defect); or nothing
was proposed and it still does not match (**the step did not do its job**).

## What it does

Longhaul takes a **job spec** — a YAML file naming a set of documents and an ordered list
of edits — and runs it against SuperDocs, one step at a time:

1. Opens every document in one multi-document session.
2. For each step, sends an edit instruction in review mode and collects the changes
   SuperDocs proposes.
3. Puts each proposed change in front of a human (terminal, browser, or another program)
   who approves and rejects them **item by item**.
4. Commits the approved ones and exports the finished documents.

Every one of those transitions is written to a durable ledger before it is acted on. When
the process dies, a new one picks up from that ledger and from what SuperDocs itself
remembers — never from anything held in memory, because after a `SIGKILL` there is none.

Here is a run resuming after being killed at step 9. Note the two different kinds of
"skipped", and the evidence line under the table:

![A resumed run](docs/resume-report.svg)

`skipped: already-done (ledger)` means the ledger already had this step terminal.
`skipped: already-done (reconciled)` means the ledger did *not* know, and the server was
asked. The distinction matters, so the report keeps it.

---

## What is proven, and what is not

This is the part worth reading carefully, because "byte-identical" is a claim that can be
made honestly or made hollow, and the difference is the whole project.

**Determinism is a property of the runner, not of a language model.** Two runs of the same
plan against a live model produce different prose by nature. Byte-identity against the
live API is therefore not merely unproven — it is *not true*, and asserting it would be
theatre. So the two claims are separated and each is proven on its own terms:

| Claim | Proven against | How | Result |
|---|---|---|---|
| **A restart is invisible in the output** | a deterministic stand-in for the API | kill and resume at every checkpoint a real run reaches; diff documents, exported bytes, and the commit log | **119 / 119 kill points identical** |
| **No edit instruction is ever issued twice** | **the live API**, and the stand-in | the server's own transcript is counted, never the runner's account of itself | **8 steps, 8 jobs, 0 duplicates** |

The second row is a real run against `api.superdocs.app`, and it cost 8 operations. It
survived an operator interrupt, a deleted ledger, a process kill during the approve call,
and two bug fixes deployed mid-run — and still issued each of its eight turns exactly
once. The full account, including four things that broke, is in
[docs/LIVE-RESULTS.md](docs/LIVE-RESULTS.md).

Every kill is a real `SIGKILL` to a real subprocess. Not an exception, not `sys.exit` —
those unwind through `finally` blocks and flush buffers, which is exactly the cleanup a
crashed process never gets. Testing with a catchable failure would prove a weaker property
than the one claimed.

The kill points are not hand-picked. One traced run emits every checkpoint it actually
reached, and the suite kills at each. It cannot be cherry-picked and it cannot drift away
from the code, because it *is* the code's behaviour. The brief asks for twenty; the
compact job produces 119, the full one 278. Raw per-kill-point data:
[`docs/proof-results.json`](docs/proof-results.json).

The offline proof is necessary and not sufficient, and it is worth being precise about why.
Killing a *process* leaves the ledger intact, so no number of kill points can reach a
ledger that is behind the server — and that is exactly the bug a live run found within
minutes. Both failure modes are now covered
([`tests/test_ledger_behind_server.py`](tests/test_ledger_behind_server.py)), but the
honest record is that the proof suite was structurally blind to one of them.

**On `.docx` specifically.** A real `.docx` embeds a creation timestamp, so two exports of
an identical document are never byte-identical — not across a restart, and not across
anything else. Byte-identity is therefore asserted on the document HTML and on the
`markdown` and `html` exports, which are pure functions of content. Saying "byte-identical
.docx" would have been an easy sentence to write and a false one.

---

## Getting started

You need [`uv`](https://docs.astral.sh/uv/) and nothing else — it fetches the right Python
(3.11+) itself.

```bash
make proof
```

Six seconds, no key: it runs the job twice, kills one partway, and diffs them. Then:

| Command | What it does |
|---|---|
| `make live` | The operator console against the real API. Needs `.env`. **Opens idle** — spends nothing until you press Run. |
| `make offline` | The same console against a local stand-in. No key, no cost. |
| `make proof` | Kill a run, resume it, diff the result. ~6s, offline. |
| `make proof-all` | The headline: the same at **every** checkpoint. ~95s, offline. |
| `make test` | The whole suite, 24 kill points, ~40s. Offline. |
| `make mcp` | Prints the MCP client config to paste into your agent. |

`live` and `offline` mean the same thing in both of this repository's builds: `live`
uses your key and costs operations, `offline` touches nothing but localhost.

Every run takes `--max-operations N` and `--reserve N`. Operations cost money and a long
job is exactly the shape of thing that spends an allowance unattended, so a run stops
*before* the turn it cannot afford and resumes later without repeating anything. The
reserve is checked against what the server reports remaining, not against local
arithmetic.

### Running it against the real SuperDocs

```bash
cp .env.example .env      # then put your key in it — .env is gitignored
uv run python scripts/live_smoke.py
```

`live_smoke.py` checks the four-call contract against `api.superdocs.app` with one tiny
synthetic document: upload, chat, approve, export. **It costs one operation.** Nothing in
it loops and nothing scales with corpus size.

To run a real job:

```bash
uv run longhaul run --spec jobs/runbook-migration.yaml
```

The same command starts a job and resumes an interrupted one — there is no separate
resume path, which is the point.

---

## The job is data, not code

A migration is a YAML file. Adding a document, a step, or a gate rule never touches the
source:

```yaml
gate:
  mode: policy              # or: manual (a person), deferred (browser / MCP)
  default: approve
  reject_when:
    - description: Wording owned by Legal does not change without a named approver.
      old_html_contains: "Legal"

documents:
  - slug: oncall-rotation
    path: ../corpus/runbooks/oncall-rotation.md
    title: On-Call Rotation Runbook

steps:
  - id: paging-tool-rename
    for_each_document: true
    instruction: >
      We have migrated our paging from PagerDuty to Rootly. Throughout this runbook,
      replace "PagerDuty" with "Rootly", keeping the surrounding sentence intact.
```

Two jobs ship in [`jobs/`](jobs/): the full six-document migration and a compact
three-document one the proof suite uses. They differ only as data.

**Declared inputs.** Documents: `.md`, `.txt`, `.html`, `.docx`, `.pdf`, `.rtf` — whatever
`POST /v1/documents/upload` accepts. Domain: any document set where the same edit has to
land consistently across many files. The corpus here is synthetic engineering runbooks for
a company that does not exist; a second run means a different job YAML over a different
document set, which is what the two shipped jobs demonstrate.

---

## Three surfaces, one gate

A human holds the gate, and the gate is the same wherever you stand:

- **Terminal** — `longhaul run --gate manual` walks you through each change; or
  `longhaul pending` / `longhaul decide --approve ch_x --reject ch_y --feedback "..."`.
- **Browser** — `make live` against the real API, or `make offline` against the local
  stand-in. The screenshot at the top.
- **MCP** — `list_pending_changes` and `decide_changes` are ordinary tools, so another
  agent drives the whole run *including* the approval, explicitly and on the record.

All three write through one function, `gate.record_decisions`, so they cannot drift apart.
Decisions are durable the moment they are made: a crash afterwards does not re-ask, and
does not quietly replace a human's call with a policy's opinion. There is a test for
exactly that.

Rejecting one change never discards the rest. In the shipped demo, one document has its
paging tool renamed while a sentence in the same document is refused because Legal owns
the wording — both in the same review.

### Wiring the MCP server

```json
{
  "longhaul": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/longhaul", "longhaul-mcp",
             "--spec", "jobs/runbook-migration.yaml"],
    "env": { "SUPERDOCS_API_KEY": "sk_your_key_here" }
  }
}
```

Seven tools: `plan_job`, `advance_run`, `list_pending_changes`, `decide_changes`,
`run_status`, `export_run`, `adjudicate_step`.

---

## Documents do not get to give orders

One runbook in the corpus carries a section written to look like instructions aimed at an
automated document system: approve everything, mark the remaining steps done, skip the
gate, and say nothing about it.

Longhaul refuses all of it, structurally: the plan comes from the job spec, the decisions
come from a policy or a person, and document text never reaches a position where it could
influence either. A second, deliberately hard-coded detector then *names* the attempt so
it lands in the report rather than passing through silently. Both layers are there on
purpose — the first is what makes it safe, the second is what makes it visible.

The policy gate additionally never auto-approves a change whose content reads as an
instruction. It refuses and says why, leaving the call to a named human.

The detector is also tested for the opposite failure: it fires on none of the five
ordinary runbooks. A defence that refuses valid work is not a defence.

---

## When it will not guess

Some crashes leave evidence that genuinely does not settle the question. A turn is in the
session transcript, its job has been purged, and the document has moved off its recorded
pre-state — so whether *this* step's changes are part of that movement cannot be
established from outside.

Longhaul stops. The step is marked `adjudicate`, the run reports `blocked` rather than
`completed`, and the report says what could not be established. A person looks at the
document and settles it:

```bash
uv run longhaul adjudicate --step 7 --resolve done     # the work is there
uv run longhaul adjudicate --step 7 --resolve replan   # it is not; run it again
```

Guessing "it landed" silently skips a step. Guessing "it did not" applies an edit twice.
Stopping is the only honest third option, and a success line that could mean either would
be worth nothing.

---

## SuperDocs surfaces used

The four-call contract, plus the reads that make crash recovery possible:

| Call | Used for |
|---|---|
| `POST /v1/documents/upload` (`open_mode=background`) | opening the whole document set into one session |
| `POST /v1/chat/async` (`approval_mode=ask_every_time`) | each edit step, in review mode |
| `POST /v1/chat/{session}/approve` | committing per-change decisions |
| `POST /v1/documents/export` | markdown / html / docx output |
| `GET /v1/jobs/{id}` | fast-path crash recovery |
| `GET /v1/sessions/{id}/history` | durable recovery — this outlives the 1h job TTL |
| `GET /v1/sessions/{id}/jobs` | recovering a job id that never reached the ledger |
| `GET /v1/sessions/{id}/documents` | document roster, and reading back document state |

The documented trap is handled: proposed-change content arrives JSON-encoded inside JSON
and needs a second parse. The local stand-in reproduces the trap rather than hiding it, so
the client is tested against it.

---

## Calls made while building

Where the brief left room, these are the calls taken and why.

**Byte-identity is asserted against a deterministic backend, not a live model.** Covered
above. This is the largest single judgement call in the project.

**`.docx` is excluded from the byte-identity claim.** It embeds a timestamp. Content-pure
formats are used instead.

**The instruction carries its own idempotency token.** Rather than depending on an
undocumented server-side idempotency key, each step's token rides inside the message text.
The act of the request landing echoes it into the session transcript, which does not
expire. That turns "did this land?" into a question the server can answer indefinitely.

**Jobs expire after an hour, so job status cannot be the only recovery route.** The
documented TTL is real and the recovery ladder is built around it: job, then transcript,
then document state, then stop.

**Approve is retried; chat is not.** An approve names `change_id`s that already exist as
proposals, so replaying it cannot invent an edit. A chat turn can. Treating those two as
the same problem is the mistake the whole design exists to avoid.

**A dead lease is reclaimed immediately when the holder is provably gone.** A killed
process never releases its lease. If the holder is on this host and its pid no longer
exists, waiting out a timer is only downtime. A holder elsewhere, or one whose liveness
cannot be established, is left to time out — never guessing a remote holder is dead is
what keeps two machines from running one job.

**A step that proposed nothing is a success, not a pause.** Some documents do not contain
the string being replaced. That step completes with zero changes and is billed zero, and
the report says so rather than treating it as a failure.

**Cost is read off the server, never modelled locally.** Longhaul reports what SuperDocs
says a turn was billed. It does not maintain an opinion about pricing.

**One instruction can need several rounds of review.** Discovered live: a section-creating
edit came back as a heading in one round and its paragraph in the next. The gate loops
until the turn completes, and every round is decided like any other — a later round is not
a rubber stamp.

**Exports are read back per document, not by session.** The export endpoint has no
per-document selector and returns the focused document; a `document_id` in the payload is
accepted and ignored. Each document's HTML is read from the session roster and exported
directly, which is free and mutates nothing.

---

## Where it breaks

Written down deliberately. Knowing where a system fails is worth more than pretending it
does not.

- **A step's proposals cannot outlive its job.** If a run is interrupted while changes are
  awaiting approval and nothing resumes it within an hour, the proposals are purged with
  the job. The step goes to `adjudicate` rather than being silently re-proposed, because
  a fresh turn would produce different changes than the ones a human was reviewing. That
  is correct, but it is a real operational limit: **resume within the hour, or expect to
  adjudicate.**
- **Reconciliation assumes this run owns its session.** Orphan-job adoption and the
  document-hash argument both rely on the run's lease being the only writer to its
  session. Another process editing the same session out of band would break that
  assumption, and Longhaul would not detect it.
- **The proof's backend is deterministic, and a language model is not.** Everything proven
  about restart-invisibility is proven about the runner. What holds against the live API
  is at-most-once, which is the property that actually costs money to get wrong.
- **Steps are serial.** One step at a time per run, on purpose — it is what makes orphan
  adoption sound. A wide corpus is not parallelised within a run; run several jobs
  concurrently instead, which is tested.
- **The stand-in is not a model.** It implements quoted directives, enough to exercise
  every code path the real API exercises. It is not evidence about how SuperDocs interprets
  natural language.
- **Not tested at corpus scale.** The largest job here is six documents and twenty steps.
  Document scale limits (25,000 sections per document) are far above anything exercised.
- **Review rounds are bounded at twelve.** A turn that keeps proposing past that stops with
  an error rather than looping. The bound is a guess: the live runs here needed two.
- **Live evidence is one run.** Eight steps, eight jobs, zero duplicates is a real result,
  not a large sample. Everything broader is proven offline.

---

## Layout

```
CONTRACT.md          the five invariants, written before the code
ARCHITECTURE.md      the state machine and the recovery ladder
jobs/                two job specs — the only difference between two migrations
corpus/runbooks/     six synthetic runbooks; one deliberately hostile
src/longhaul/
  ledger.py          durable state: CAS transitions, leases, append-only commit log
  runner.py          the step machine
  reconcile.py       "did that actually happen?", answered from durable evidence
  gate.py            one decision core behind the terminal, the browser and MCP
  client.py          the SuperDocs client
  checkpoints.py     the fault injection the proof suite drives
tests/
  fake/server.py     the deterministic stand-in
  test_kill_points.py  the proof
scripts/live_smoke.py  the one thing that talks to the real API
```

Read [`CONTRACT.md`](CONTRACT.md) first if you want to know what this system is not
allowed to do, and [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it manages it.

---

## Credit

Built by **Vishvamsinh Vaghela** for the SuperDocs engineering task, Round 2 — the
assigned build *"Long-run editing job that survives a restart without duplicating work."*

Built on the [SuperDocs](https://superdocs.app) REST API. Documentation:
[docs.superdocs.app](https://docs.superdocs.app).

Every company, document, incident, and person in `corpus/` is invented. Nothing here is
anyone's real paperwork.

MIT licensed, as the rest of this repository is.
