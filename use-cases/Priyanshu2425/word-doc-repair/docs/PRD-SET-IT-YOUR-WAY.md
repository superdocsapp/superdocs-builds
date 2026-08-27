# Set it your way — the styling counter

**Status:** approved for build, 2026-08-26. **Design:** V5 *Quiet Counter*,
`docs/style-it-yourself/v5-quiet-counter.html`.

> Read `BASELINE.md` first. This document proposes one amendment to it (B20 →
> B20′) and two additions (B27, B28). Everything else in this feature is built
> so that the existing invariants stay true.

---

## 1 · What this is

The recovery already styles the file on the way through and hands the styled copy
over, with the plain rebuild one link away. What it cannot do today is take an
opinion. A person who does not like how their recovered document has been set has
exactly one move: open Word and do it themselves.

The counter is a door beside the download. Behind it the repaired document is on
the left and a line to SuperDocs is on the right — one field, one sentence back,
and receipts one line each. On a phone the document holds the screen and the
counter is a drawer.

It opens **after** the automatic pass has run and been handed over. It is not the
opt-in button removed on 2026-08-26, and the entry copy is what keeps that true:

> Styled through SuperDocs, which changed how your words are set and not what
> they say. [Download the unstyled copy instead]
>
> **Set it your way →** — Not how you would have set it? Say so, and watch it
> change.

That wording is normative. "Style my document" would reintroduce the opt-in and
make **B3** false.

---

## 2 · What a person can ask for

**Formatting.** Sizes, weights, spacing, table rules, where pictures sit, setting
a passage apart, margins. Applied by SuperDocs, verified on the way back.

**Their own words.** Replacement or insertion text the person types, applied
verbatim. It arrives quoted in the field or through the *put in my own words*
affordance; the exact string is what is sent and what the guard expects to find
in the file that comes back.

**Refused, always.** Asking the model to write, complete, summarise, reword or
fill a gap. Refused locally, before anything is sent, at no cost.

> **You:** Can you finish that last paragraph? It stops mid-sentence.
> **Counter:** No. That would be writing words your document does not have. If
> you tell me how it ends, I will put your words in and mark them as yours.

That is the whole product in four lines. The person who came here to get *their*
words back is not handed a model's.

---

## 3 · The one baseline change

**B20 as written is made false by this feature** and is amended rather than
worked around.

> **B20 (before).** A styled file that returns with fewer readable pictures, or a
> different word multiset, is refused and the plain rebuild ships instead.

The word-multiset half is absolute today because of 2026-08-20, when a four-line
report came back with invented paragraphs, a subtotal row, a disclaimer and a
signature block. That was the *model* writing prose. A person typing their own
sentence is a different act with an identical signature, and the guard as built
cannot tell them apart.

> **B20′.** A styled file that returns with fewer readable pictures is refused. A
> styled file whose word multiset differs from its **authorised baseline** is
> refused. The authorised baseline is the rebuild's words, plus words the person
> supplied verbatim in this session, minus words they asked to remove. Only the
> person moves the baseline, only by supplying the exact text, and every move is
> recorded and disclosed in the handover.
>
> **B27.** Words the person supplied are recorded as theirs. The handover states
> how many words in the file were written at the counter rather than recovered
> from the damaged document.
>
> **B28.** The guard runs against two baselines on every turn: the previously
> accepted version, and the authorised baseline derived from the original
> rebuild. Per-turn checking alone would let twenty turns of one word each pass
> every individual check.

B1, B2, B3, B4, B5, B21 and B22 are unaffected, and each is re-asserted below
where the feature touches it.

### The authorised baseline, precisely

```
authorised = Counter(words(rebuild))
           + Counter(words(text the person supplied))
           - Counter(words(text the person asked to remove))
```

`words()` is the existing `superdocs_client._words` — lowercase alphanumeric
runs, a multiset, so re-wrapping and re-escaping read as no change. The guard
compares each returned file against `authorised` and against the previous
accepted version. Anything else is a refusal.

---

## 4 · Three layers of no, cheapest first

| Layer | Where it runs | What it costs | What it catches |
|---|---|---|---|
| **Pre-flight** | Locally, before any call | Nothing | Turn cap reached · allowance is zero · the turn asks the model to write words |
| **Envelope** | On the wire | — | Every turn wrapped in the bounded contract `superdocs_client.INSTRUCTION` already carries. Supplied text goes as an exact-string replacement, never as a description of one |
| **Guard** | On the file that comes back | **One operation, already spent** | `_why_not_acceptable`, against both baselines |

**Two kinds of no, and only one of them is free.** The pre-flight no costs
nothing and says so. The guard's no comes after SuperDocs has already applied and
billed the turn, because the synchronous chat applies inline — the platform bills
zero for *failed* and *denied* edits, but this is a successful edit that **we**
reject. The screen must not say "nothing was counted" for that case. It says:

> The change came back with wording that is not yours, so it was thrown away
> rather than handed over. That attempt was counted; your document was not
> changed.

The mock-ups in `docs/style-it-yourself/` currently say a refusal costs nothing.
That is true of the pre-flight layer only, and the copy is corrected with this
document.

---

## 5 · The session

`superdocs_client.style()` mints a `session_id` and discards it. For a
conversation the session has to survive the call. This is the largest change in
the feature.

**`StyleSession`**, held beside the existing `_READY` map in `web.py`:

| Field | Why |
|---|---|
| `session_id` | The SuperDocs conversation. Turns continue on the same document. |
| `rebuild` (bytes) | The cumulative anchor for B28. Never overwritten. |
| `versions: list[bytes]` | Accepted exports, oldest first. `versions[-1]` is what a download returns. |
| `authored: Counter` | Words the person supplied, for B20′ and B27. |
| `turns_used` | Against the cap. |
| `last_used_at` | The idle timer. |
| `dir` | A directory of its own — see O3 below. |

**Life: 30 minutes idle**, reset by each turn, matching the retention sentence the
page already makes (`frontend/src/App.tsx:157`). On expiry the counter says it has
closed and the last accepted file stays downloadable for the rest of its own
window.

**The retention gap this exposes.** `_READY` evicts by count (64 entries) and
never by time, while the page promises "about thirty minutes". Nothing enforces
the claim today. Sessions living half an hour make that material, so a real idle
sweep ships with this feature — the promise becomes enforced rather than asserted.

**O3 is fixed here, not later.** `engine.repair` writes `local_rebuild.docx` into
the process working directory, and concurrent requests race on that one path.
Sessions alive for thirty minutes make the race routine rather than theoretical.
Each session gets its own directory.

**A session lost mid-conversation** is never a dead end: re-upload
`versions[-1]` into a fresh SuperDocs session, carry on, and say so in one
sentence. The person's accumulated work is not spent again.

---

## 6 · Transport, timeouts, and the thing that must never be retried blindly

Three facts from our own teardown of the platform (`superdocs-teardown.html`)
decide this section:

1. **There is no idempotency key on billable writes.** Retrying a turn on a 5xx
   can apply the same edit twice and bill for it twice.
2. **Synchronous `/v1/chat` 504s past about 300 seconds**, while the application
   applies a 30-minute wall-clock cap. `REQUEST_TIMEOUT` is 300.0 — sitting
   exactly on that boundary. A turn can therefore time out on the wire while the
   edit is still landing.
3. **`/v1/chat/async` is durable** and survives that gateway limit.

**Decision.** Conversation turns go over the asynchronous endpoint. The automatic
pass inside the recovery stays synchronous and unchanged — it sends one bounded
instruction and D1 still stands. This is a transport choice, not the HITL
approval flow: `approval_mode` stays off, edits still auto-apply, and the guard
still does after the fact what approval would do before it.

**Never blind-retry a turn.** After a timeout or a 5xx, *reconcile* instead —
using the session's **version id**, which is free, session-scoped and exact:

1. Before sending, capture `document_state.version_id` from
   `GET /v1/sessions/{session_id}/history`.
2. After a timeout, read it again. Costs nothing.
3. Unchanged → the edit did not land. Offer to send it again.
4. Changed → the edit landed. Export (also free — §7) and run the guard on it as
   a normal turn.
5. History itself unreadable → *cannot confirm*. Do not resend automatically.
   Guessing wrong in this direction is the double-apply this whole section exists
   to prevent.

*Measured 2026-08-26: a real edit moved `version_id` from `c5c49219…` to
`01ca2b98…`. `document_state.last_modified` is `null` and carries nothing.*

**A trap worth writing down.** The obvious free check is the documented
`structure` block on `GET /v1/documents/{id}` — but that endpoint wants the
**permanent** document UUID. The id the upload hands back is `doc_primary`, a
session-local slot, and both it and the session id return **400**
(`session_scoped_document_id`). The permanent id is `durable_document_id`, from
`GET /v1/sessions/{session_id}/documents`. Reconciling on `version_id` avoids the
id resolution altogether, which is why it is the one on the hot path: a
reconciliation that silently always fails would report "it did not land" every
time and invite exactly the resend that must never happen.

A retry loop here would double-edit a document somebody is trying to get back
intact, and bill them for the privilege.

**`response_mode='compact'`** returns only the changed chunks. Use it: it is what
writes the receipt line ("Table rules are hairlines now") without re-reading the
whole document every turn.

---

## 7 · Cost and the allowance

- **A per-document cap of 10 turns**, checked locally and free. Protects one
  shared key from being spent by one person, and gives a no that costs nothing.
- **The account allowance read before each billable turn** via
  `SuperDocsClient.allowance()`. **B22 is unchanged**: an unreadable balance
  proceeds and says the number is unknown; it is never reported as zero.
- **Undo does not consume a turn from the cap.**
- What is left is shown beside the field that spends it, as drawn in V5.

### What each call costs — read, not assumed

Measured against the live account on 2026-08-26, one operation spent to do it
(`scripts/probe_revert_billing.py`, re-runnable; balance went 496 → 495 and
stopped there).

| Call | Cost | How we know |
|---|---|---|
| `POST /v1/documents/upload` | **0** | Measured. Docs: "Uploading and parsing is NOT itself a billable operation" |
| `POST /v1/chat` (a turn) | **1** | Measured. Response `usage`: `was_billable: true, ops_charged: 1` |
| `GET …/history` | **0** | Measured |
| `GET /v1/documents/{id}` → `structure` | **0** | Docs: "always included, token-light, NON-BILLABLE" |
| `POST …/export` | **0** | Docs: "uploads/parsing and exports are free" |
| `GET /v1/agents/whoami` | **0** | Reads are free |
| **`POST …/revert`** | **0** | **Measured.** Balance unchanged across the call; no `usage` block in the response |

So a revert is free, and the turn cap is the only thing that needs to bound it.
This was the open question B22's principle would not let us ship on; it is now a
number somebody read.

**Also zero-billed by the platform:** failed edits, denied HITL changes, and an
edit the document already satisfies. A guard rejection is none of these — see §4.

**`usage` comes back with every turn — nested, not at the top level.** On the
async path it is at `job["result"]["usage"]`:

```json
{"monthly_used": 6, "monthly_limit": 500, "monthly_remaining": 494,
 "was_billable": true, "ops_charged": 1, "quota_exhausted": false}
```

Keep the pre-flight `whoami` read that B22 requires, and refresh from the turn's
own `usage` afterwards rather than asking twice.

**The turn index comes free with the job** — `job["metadata"]
["user_turn_index_pre_inserted"]` is the user message's index, which is what
`revert` takes. No second read of the history to find it.

---

## 8 · Undo

**Native, not re-upload.** SuperDocs ships per-message revert, and it restores
the document and the conversation together —
which matters, because a document rolled back under a conversation that still
remembers the change will drift on the next turn.

Linear, matching V5's receipts: the newest change carries *put it back*, older
entries are history. Per-change revert (the V2 *Amendment Slips* model) is
technically available — the endpoint takes any user message's `turn_index` — and
is deliberately out of scope for this build.

After a revert, `versions` pops and the local guard baseline is recomputed from
`rebuild` plus `authored` minus anything the reverted turn added.

**The contract, as measured:**

- `POST /v1/sessions/{session_id}/revert` with `{"turn_index": n}`, where `n` is
  the position of the **user** message being undone. It comes from
  `GET …/history`, where each message carries `turn_index` and `checkpoint_id`.
- **Free** (§7).
- Returns `compose_text` — the text of the reverted instruction. V5 puts it
  straight back in the field, so *put it back* leaves the person holding what
  they said, ready to change one word and send it again. That is the whole
  reason to prefer the native call.
- Returns `reverted_to_turn` (`-1` when the session is back to empty) and
  `archived_turn_count`. Reverted turns are soft-archived, not destroyed.
- **`409`** if a chat job is running on the session — wait for it to settle.
  Reachable here: a person can hit *put it back* while a turn is still in
  flight, and the button must be withheld rather than fail.
- **`422`** if the message predates the revert feature (`checkpoint_id` is
  `null`). Not reachable for sessions this feature creates, but the branch is
  written rather than assumed away.
- The response also carries a `redo_checkpoint_id`. **Deliberately not kept**
  (owner, 2026-08-27). Redo is not in V5's interface and is not being built, so
  storing an id for it would be carrying state for a feature that does not
  exist. Recorded for whoever wants it later: the redo endpoint needs **both**
  `turn_index` and that id, and a request carrying only what the prose
  describes comes back `422` — verified 2026-08-26, before the id was dropped.

---

## 9 · What ships

`download` always points at `versions[-1]`. `plain_download` is always the
rebuild — **B2 unchanged**, preferring the unstyled copy never costs a second run.
A turn in flight never changes what a download returns.

Per **B27**, when `authored` is non-empty the handover says so:

> 14 words in this file were written by you here, not recovered from your
> document.

---

## 10 · Degradations, one sentence each

**B21 unchanged**: every degraded outcome states its reason in one sentence a
non-engineer can act on. No class names, no engine vocabulary.

| Case | What is said | What happens |
|---|---|---|
| No key | The counter is not available on this copy of the page. | The field is not drawn at all |
| Allowance zero | There is no styling allowance left this month, so nothing was sent and nothing was spent. | Field not drawn; receipts stay readable |
| Turn cap reached | That is the tenth change on this document, which is as many as one recovery carries. | Field not drawn; download unaffected |
| Turn timed out | That change did not come back in time. | Reconcile (§6), then say whether it landed |
| Empty export | Nothing came back, so the document is as it was. | Version stack untouched; turn counted |
| Guard — pictures | It came back with fewer pictures than it was sent, so it was thrown away. | Previous version stands; turn counted |
| Guard — wording | It came back with wording that is not yours, so it was thrown away. | Previous version stands; turn counted |
| Put it back, mid-turn (`409`) | That change is still going through. You can put it back once it has landed. | *Put it back* withheld while a turn is in flight, not failed |
| Session expired | The counter has closed. Your file is still here to download. | Last accepted version stays downloadable |
| SuperDocs unreachable | The counter cannot be reached just now. Your document is unchanged. | Field not drawn; nothing lost |

**Nothing renders as a button that cannot be pressed.** Where the field is not
drawn, one sentence stands in its place.

---

## 11 · Progress

**B5 unchanged**: every stage arrives on one stream, in order, as it happens.
`POST /api/style/{token}/turn` streams SSE exactly as `/api/recover` does — a turn
can take from thirty seconds to minutes, and a spinner that could mean anything is
not an answer. On a phone the stream survives the drawer closing, and the dock
line carries the progress.

---

## 12 · Endpoints

Added under `/api/style/{token}/…`. The existing `POST /api/style/{token}` retry
route stays as it is.

| Route | Does |
|---|---|
| `POST …/open` | Opens a session. Returns turns left, allowance (known/remaining), retention |
| `POST …/turn` | One instruction. SSE stages, then the manifest |
| `POST …/revert` | Back one accepted version |
| `GET …` | Session state: receipts, versions, turns left |
| `DELETE …` | Dispose now — "let it go" |

**Availability comes from the endpoint that already exists.**
`GET /api/capabilities` reports whether styling is available and is currently
unreferenced by the report component. It decides whether the counter's *field* is
drawn. It never gates the automatic pass — **B3 unchanged**. This is exactly the
"wiring cut, implementation left behind" trap `CLAUDE.md` names, so the existing
probe is reused rather than a second one invented.

---

## 13 · Non-goals

Accounts. Collaboration. Comments. Versions outliving the session. Touching the
person's original file. Per-change revert. The asynchronous **approval** flow —
async is used here only as a durable transport, and D1 stands.

---

## 14 · How we will know

Measures that can be failed, in **B19**'s spirit — a bar that cannot be failed by
the defect it exists to catch is a claim, not a measurement.

- **Guard-rejection rate.** The number to watch. A rising rate means the envelope
  is leaking and the model is writing prose again.
- Turns per session, and the share of sessions ending in a revert.
- Share of downloads taken after at least one turn — whether the door was worth
  opening.
- Distribution of user-authored word counts, against B27's disclosure.

**`tests/test_styling_conversation.py`**, offline against an injected client
(**B24**: the whole suite runs with no key and no network):

1. A scripted conversation's final file has exactly the authorised word multiset.
2. Picture count never falls across a conversation.
3. A turn asking the model to write prose is refused with no network call made.
4. Twenty turns of one-word drift are caught by the cumulative baseline (B28).
5. Revert restores the previous bytes exactly.
6. Turn cap and a zero allowance both refuse before anything is sent.
7. A timed-out turn reconciles rather than retries, and never sends twice.

---

## 15 · Open questions

- ~~Is a native revert billable?~~ **Answered 2026-08-26: no, it costs nothing.**
  Measured against the live account rather than inferred from the docs, which
  annotate other endpoints as billable or non-billable and say nothing either way
  about this one. See §7.
- **Is 10 turns the right cap?** Picked to be defensible, not measured. First
  real sessions should move it.
- ~~Is `redo` free too?~~ **Moot: redo is out** (owner, 2026-08-27). Never
  measured, and now never needs to be.
- **How does supplied text arrive?** Quoted in the field is specified here. If
  real use shows people writing unquoted prose and expecting it inserted, the
  affordance needs to be more than a convention.
