# docsync — keep specs, ADRs and runbooks in step with the code

**Parth Saini** · an extension built on SuperDocs, for Cursor, VS Code and Claude Code.

A constant changes in `retry.py`. Three documents describe that constant: an
ADR that explains why it is what it is, a runbook the on-call engineer reads at
3am, and an API spec a customer sees. Nobody updates them, because nobody knows
which three documents they are.

docsync knows, because each document says what it carries. It extracts the
tracked values out of the code, compares them against the last time the
documents were in step, works out exactly which documents carry the thing that
moved — and which are deliberately left alone — then sends **one narrow edit per
document**, holds every proposed change at a human gate, checks what actually
landed, and writes the updated documents back into the working tree so they land
in the same pull request as the code.

It runs as an MCP server, so the agent already in your editor can do all of that
and show you the diffs before anything is applied. It is also a plain CLI, and
the useful half of it — *what is out of step, and what would it cost* — is free,
offline, and needs no API key.

---

## The 60-second demo

```bash
pip install -e .
cp .env.example .env          # then put your key in it
cd example
```

```bash
docsync facts --registry .
```

Prints the eight values docsync tracks in the example service. Offline, free.

```bash
docsync audit --registry .
```

Checks every coverage claim against the documents that make it — *does this
runbook actually contain the value it says it carries?* This is the command
worth running before you need it. Output on the shipped example:

```
docs/adr/0007-retry-policy.md
  ok     retry.max_attempts  = 3  (1×)
  ok     retry.backoff_seconds  = 30 seconds  (1×)
  ok     queue.dead_letter_topic  = provisioning.dead-letter  (1×)

docs/runbook-circuit-activation.md
  PROSE  retry.max_attempts  = 3
         the current value does not appear literally, so a change to it can only be
         applied as a prose edit (--allow-prose) and cannot be verified afterwards
  ...
docs/spec-provisioning-api.md
  WEAK   api.default_bandwidth_mbps  = 1000
         appears 2 times and is short enough to be ambiguous; add a `format:` to this
         fact so the anchor carries its own context

10 anchored · 1 weak · 1 prose-only · 0 unresolved
```

Now change the code the way a real commit would, and ask what it costs:

```bash
docsync snapshot --registry .           # record where the docs currently stand
sed -i '' 's/MAX_ATTEMPTS = 3/MAX_ATTEMPTS = 5/' src/provisioning/retry.py
docsync plan --registry .
```

```
1 fact(s) moved:
  Maximum retry attempts: 3  →  5

1 document(s) to edit, 2 left alone, 0 already correct:
  EDIT  docs/adr/0007-retry-policy.md
          Maximum retry attempts: 3 → 5
  HELD  docs/runbook-circuit-activation.md
          HELD BACK — Maximum retry attempts: "3" does not appear in this document,
          so it cannot be changed by substitution
  KEEP  docs/sla-summary.md
  KEEP  docs/spec-provisioning-api.md

Cost of this round: 2 billable operation(s) (1 upload, 1 edit).
```

Nothing has been sent and nothing has been billed. `docsync apply` does it for
real, showing you each proposed change and asking.

---

## How it decides what to say

**A fact is a named value, a file, and an extractor.** Declared once, in
`docsync.yaml`, next to the code:

```yaml
facts:
  retry.backoff_seconds:
    label: Retry backoff interval
    from: src/provisioning/retry.py
    extract: python_constant:BACKOFF_SECONDS
    format: "{value} seconds"
```

Five extractors: `python_constant`, `json_path`, `yaml_path`, `regex`, and
`regex_list` for set-valued facts like a route table. An extractor either finds
exactly what it was told to find or it raises — a missing constant stops the run
rather than becoming a `None` that gets quoted into a document.

**Coverage is declared by each document**, in its front matter, because the
person adding a paragraph about retries is the person who knows the runbook now
carries that fact:

```markdown
---
docsync:
  covers: [retry.max_attempts, retry.backoff_seconds]
---
```

A document with no `docsync` block is never touched. That is the default:
dropping this into a docs tree does nothing until somebody opts a document in.

**Before spending anything, every document is read and every fact classified
against its actual text:**

| | |
|---|---|
| `literal` | the old value is there, exactly once — quote it |
| `weak` | it is there but ambiguous — name the sentence, never the value |
| `unanchored` | it is not there at all — held back unless you ask |
| `current` | the document already says the new value — do nothing, cost nothing |

That classification is why `docsync plan` is trustworthy and why running it
twice costs nothing the second time.

---

## The human gate

`apply` is two phases with a person in between. **`stage`** sends the edits and
stops; **`commit`** applies exactly what somebody approved. Between them the
process can exit — the paused jobs live server-side and the batch describing
them lives in `.docsync/pending.json`.

That split exists because of where this runs. A CLI can block on `input()` and
call it a gate. An MCP server cannot: the tool returns, and a person looks at
the result whenever they look at it.

Over MCP: `docsync_apply` returns the proposed changes and applies **nothing**.
`docsync_approve` takes an explicit list of change ids — there is deliberately
no approve-everything argument, and anything not listed is rejected.

**Be clear about what that does and does not buy you.** It guarantees the diffs
exist and were surfaced before anything applied. It does *not* guarantee a human
read them: an agent holding both tools can call the second one itself. If you
want the gate enforced rather than encouraged, set `DOCSYNC_APPROVE_MODE=cli` —
`docsync_approve` then refuses, and the only way to apply a staged batch is a
person running `docsync approve` in a terminal.

---

## Install it in your editor

```bash
pip install -e .
```

Copy the matching file from `editor-config/` into your repository. None of them
contain a key: docsync reads `SUPERDOCS_API_KEY` from the `.env` beside your
`docsync.yaml`, which your `.gitignore` already covers.

| editor | file | note |
|---|---|---|
| Claude Code | `.mcp.json` | or `claude mcp add docsync -- docsync serve --registry .` |
| Cursor | `.cursor/mcp.json` | same `mcpServers` shape |
| VS Code | `.vscode/mcp.json` | key is `servers`, and needs `"type": "stdio"` |

Eight tools. `docsync_facts`, `docsync_audit`, `docsync_plan` and
`docsync_pending` are marked read-only and cost nothing. Only `docsync_apply`
spends operations.

---

## What SuperDocs features it uses

- **Chat editing with `approval_mode: ask_every_time`** — the human gate.
- **Async jobs** (`/chat/async` + polling), branching on
  `metadata.awaiting_kind` because a change review and a continue-prompt share
  the status `awaiting_approval`.
- **Per-change approval** — `changes: [{change_id, approved}]`, with top-level
  `approved` always present because omitting it is a bare 422.
- **Multipart upload with `open_mode=new_focused`**, never `upload-base64`.
- **Session document roster with `include_html=true`** to read each document's
  own body back for verification. Free, and it avoids the export path, which has
  no `document_id` and returns whichever document is focused.
- **Markdown export** to write the edited document back into the repository.

---

## Where it breaks

Written from live runs, not from imagination. Every number below was measured.

### 1. A turn carrying more than one instruction item is unreliable

The one that shaped the design. Against the example ADR:

| instruction | paused at the gate | ran to `completed`, proposing nothing |
|---|---|---|
| 1 item | 12 | 0 |
| 2 items | 1 | 6 |
| 3 items | 1 — and applied one of the three | 0 |

A bypassed job replies *"✅ I've completed the requested change"*, returns a
populated `document_changes.updated_html`, and **persists nothing**. The
document is untouched and no change was ever offered for review.

So docsync sends **one changed fact per document per round**. A document with
three changed facts takes three rounds against the same session; `docsync apply`
runs them back to back. Splitting them across sessions instead would be cheaper
and wrong — each session holds its own copy, so the edits would land on
different copies and no copy would ever be correct.

This is reported to SuperDocs. The cost of the workaround is one extra upload
per extra round, because the document changes between rounds.

### 2. Verification is presence-based, and that has a limit

After an edit, docsync checks that the new value is in the document, and that
every *other* fact the document carries is still correct (the second check
catches collateral damage — it is what caught an edit that updated a retry
backoff and silently rewrote a request timeout that read the same).

What it still cannot tell you is whether a value landed on the *right sentence*,
when the two candidate sentences carry no other tracked fact between them.
Catching that needs a reader that understands which sentence is which.

### 3. Prose edits cannot be verified, and are not idempotent

A runbook saying "it will make three attempts" states a fact without containing
its value. `--allow-prose` will send the edit; nothing can confirm it landed,
and the next run will offer to send it again, because there is no literal to
detect. These are reported as *applied, not verified* and never counted towards
a green result.

### 4. Write-back reformats the document on the first sync

SuperDocs' markdown export puts every soft-wrapped source line in its own
paragraph, so the first write-back of a hard-wrapped document produces a large
diff (measured: 45 changed lines for 6 real changes) and turns `|---|` into
`| --- |`. Subsequent runs are stable because the file is already in that shape.
Front matter is exempt — it is stripped before upload and re-attached after, so
it round-trips byte-identical.

If a large first diff is unacceptable, run with `--no-write-back` and copy the
changes across by hand.

### 5. Everything else worth knowing

- **Markdown only.** Front matter or an HTML comment; `.rst`, `.adoc` and Word
  are not supported.
- **A list fact is one capture group.** If you need a method *and* a path, put
  them in one string in the source, as `example/src/provisioning/api.py` does.
- **Reordering a list is not a change.** Set membership only, by design.
- **A fact that stops resolving stops the run.** If `MAX_ATTEMPTS` is deleted,
  the correct new sentence is a human judgement and docsync will not guess it.
- **`git` is required for `--base`.** The snapshot baseline and `--base-dir`
  work without it.
- **Values are matched case-sensitively.**
- **`whoami` under-reports your quota.** It returns the plan limit and omits
  promotional grants — on the account this was built with, 500 against 9,837
  actually available. docsync adds `/users/me/promotions` and reports the total.

---

## A measured live run

The shipped example, against the real API. Three facts move: retry attempts
3→5, backoff 30s→45s, and one new endpoint.

| round | operations | what happened |
|---|---|---|
| 1 | 6 (3 upload, 3 edit) | ADR, runbook and spec each take one fact. All three verified and written back. `api.endpoints` baseline advances. |
| 2 | 1 (1 edit) | The ADR takes its second fact. Verified, written back. `retry.backoff_seconds` advances. |
| 3 | 0 | Nothing left. |

**7 billable operations, about 100 seconds.** Reads, exports and approvals are
free and are not counted.

What the documents say afterwards, checked against the code:

- ADR — "attempted up to **5** times", "spaced **45** seconds apart" ✓
- Runbook — "spaced **45** seconds apart" ✓, and *"each call is given **30**
  seconds"* left alone ✓ — that sentence is the request timeout, which did not
  change, and it reads identically to the backoff that did
- Spec — the new endpoint added to the route table ✓
- `sla-summary.md` — carries none of the changed facts, never contacted ✓
- Front matter — byte-identical in every document ✓
- One change held back: the runbook states the retry count in prose

The runbook line is the one worth dwelling on. An earlier version of this build
updated both "30 seconds" sentences, so the runbook told an on-call engineer the
carrier timeout was 45 seconds when the code said 30 — and verification passed,
because the value it had asked for was indeed present. That is the failure this
tool exists to prevent, arriving from inside the tool.

---

## Tests

```bash
pytest -q
```

**235 tests, no API key, no network.** The CLI tests run with
`SUPERDOCS_API_KEY` unset and `SUPERDOCS_BASE_URL` pointed at a closed port, so
a command that quietly made a call would fail rather than pass.

The SuperDocs client is exercised against a fake **transport**, not a mocked
client, and the fake models the awkward parts on purpose — `upload-base64`
returning no document id, a session refusing a second concurrent job, proposed
changes arriving JSON-encoded inside a JSON field, and a service that
over-applies an edit. A fake that agrees with you is how the offline suite stays
green while the live build is wrong; that happened in Task 2 of this round and
the fixtures here are written against shapes verified in production.

Six tests exist specifically because a live run found a bug the offline suite
could not, and each fails against the code as it was:

| test | what it caught |
|---|---|
| `test_each_document_gets_its_own_session` | a session runs one job at a time, and a job parked at the gate still counts |
| `test_an_anchor_that_is_another_facts_value_stops_being_quoted` | an instruction that moved a retry backoff also rewrote a request timeout reading the same |
| `test_collateral_damage_to_an_unchanged_fact_fails_the_run` | ...and verification said OK, because it only checked what changed |
| `test_a_gate_that_does_not_engage_is_retried_exactly_once` | `ask_every_time` completing without pausing, claiming success, persisting nothing |
| `test_it_overwrites_its_own_previous_round` | round one's write-back made the file dirty, so round two refused to write its own output |
| `test_already_applied_is_detected_when_a_sibling_still_reads_the_old_value` | a change re-sent every round because another fact still read the old value |

---

## Command reference

| command | costs | what it does |
|---|---|---|
| `docsync facts` | free, offline | every tracked value as the code has it now |
| `docsync audit` | free, offline | check every coverage claim against the document |
| `docsync plan` | free, offline | what drifted, who carries it, what it would cost |
| `docsync snapshot` | free, offline | record the current values as the baseline |
| `docsync apply` | **operations** | send, review, verify, write back |
| `docsync approve` | free | decide a batch the MCP server staged |
| `docsync serve` | — | run as an MCP server over stdio |

`--dry-run` prints the plan and its cost without a single call, and without
needing a key. `--max-operations` is a hard stop checked before every billable
call, not a warning printed afterwards.

---

MIT licensed, as the repository requires. Every document and every line of code
in `example/` is synthetic and says so.
