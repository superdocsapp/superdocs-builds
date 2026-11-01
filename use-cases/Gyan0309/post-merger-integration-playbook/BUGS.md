# What broke, and what surprised me

Integration notes from building the post-merger integration playbook set on the
SuperDocs API, 2026-08-15/16. Everything here was hit while building, and every item
was reproduced before being written down.

Ordered by how much time each cost me.

---

## 1. `ask_every_time` on sync `/v1/chat` produces changes that cannot be approved

**Blocking.** This is the one that cost the most time.

`POST /v1/chat` with `approval_mode: "ask_every_time"` returns
`document_changes.pending_changes[]`, each with a `change_id`. So far so good.

But `POST /v1/chat/{session_id}/approve` requires a **`job_id`** — and the sync chat
response has no job_id anywhere in it. Its keys are exactly:

```
["document_changes", "hint", "response", "session_id", "usage"]
```

Only `POST /v1/chat/async` returns a `job_id`. So the sync endpoint can *propose*
changes it gives you no way to *accept*: the review loop is unclosable on that path.

What I expected: either sync chat returns a job_id, or approve accepts a session_id
plus change_id.

**Reproduction:** `POST /v1/chat` with `approval_mode: "ask_every_time"`, then try to
approve any returned `change_id`. There is no value to put in `job_id`.

**Workaround:** always use `/v1/chat/async`. That is what this build does.

**Suggestion:** either return `job_id` from sync chat, or have `/approve` fall back to
"the most recent job on this session" when `job_id` is omitted.

---

## 2. The task brief's cheat-sheet has the wrong export endpoint

The brief documents export as `POST /v1/export`. That path is a **404**.

The real endpoint is `POST /v1/documents/export`, and two more details differ from what
I assumed from the brief:

| I tried | Actually |
|---|---|
| `POST /v1/export` | `POST /v1/documents/export` |
| `{"document_id": ...}` | `{"session_id": ...}` — it takes the *session*, not a document |
| `"format": "md"` | `"format": "markdown"` |

**Also: the response is the file itself, not JSON.** A client that calls `.json()` on
it dies on the first byte with `Expecting value: line 1 column 1`. Returning raw bytes
is entirely reasonable — it just is not what the surrounding API trains you to expect,
since every other endpoint returns JSON.

---

## 3. `/approve` requires `job_id`, which the brief does not mention

The brief warns that `approved` must be top-level or you get a bare 422. True, but
incomplete: `job_id` is **also** required.

Credit where due — the 422 body names both missing fields, which is far more helpful
than the "bare 422" the brief warns about:

```json
{"detail":[{"type":"missing","loc":["body","job_id"],"msg":"Field required"},
           {"type":"missing","loc":["body","approved"],"msg":"Field required"}]}
```

One more shape difference: the field is `change_id` (singular). Batch decisions go in
`changes: [{change_id, approved, feedback}]`, not a `change_ids` array.

---

## 4. Pending changes live in `metadata`, not `result`

While a job is `awaiting_approval`, `GET /v1/jobs/{job_id}` returns `result: null`.

The changes you need in order to decide are in **`metadata.pending_changes`**.

This is backwards from the intuition that `result` holds the output and `metadata`
holds bookkeeping — and `result` is null *precisely* during the window when a caller
must act. I initially reported "0 pending changes" for a job that had one.

---

## 5. The job status vocabulary includes `in_progress`

A poller written against the obvious working-state list —
`pending`, `processing`, `running`, `queued` — exits immediately, because the actual
status is `in_progress`. It then reads `result: null` and concludes there is nothing
to do.

Silent and fast, which is the worst combination: it looks like a successful no-op.

**Fix in my client:** poll against an explicit *terminal* set rather than a guessed
working set, so an unfamiliar status keeps the loop running instead of ending it.

---

## 6. `usage` is null on chat responses, so the documented spend meter does not work

The brief says to read usage off the `usage` block in every chat response, because
`/v1/users/me/usage` rejects `sk_` keys with a 401 (confirmed — it does).

But `usage` came back **null** on every `/v1/chat` response I received.

That leaves `GET /v1/users/me/promotions` as the only working spend meter, which is
what this build polls. Worth fixing, because "budget your operations" is advice the
brief gives twice and the documented mechanism for it is the one that does not work.

---

## 7. `upload-base64` silently does not save without a `session_id`

Not a bug — I am listing it because it is the single most likely thing to confuse a new
integrator, and because the API handles it unusually well.

Without `session_id`, the upload is a one-off conversion: you get parsed HTML back and
**nothing is stored**. With one, the document persists.

What makes this good rather than bad is the response field:

```json
"persisted": false,
"how_to_persist": "This is a one-off conversion and was NOT saved. To store the
 document durably (it then appears in Files, is editable via chat, and survives
 reconnect), send the same request with a session_id."
```

It does not merely report the state — it names the exact request that changes it. That
is the best piece of API self-documentation I hit on this surface, and I would like to
see it copied to the endpoints above.

Minor: the field is `file_base64`; `content_base64` is the natural guess and 422s.

---

## 8. The double-encoded content trap is real, but not where I looked first

The brief warns that proposed-change content arrives JSON-encoded as a string and
needs a second parse. Precisely:

| Where | Shape |
|---|---|
| `metadata.pending_changes[]` | already objects — **no** second parse |
| `metadata.intermediate_responses[]` where `type == "proposed_change_batch"` | `content` **is** a JSON string |

So a client reading `pending_changes` never hits it, and one rendering the streamed
intermediate responses always does. Worth stating in the docs, since "parse everything
twice" and "parse nothing twice" are both wrong.

---

## 9. `409 session_busy` after approving — approve is not "finished"

`POST /chat/{session}/approve` returns 200 immediately, but the job carries on in order
to actually apply the change. Send the next instruction into that session and you get:

```json
{"error_code": "session_busy",
 "message": "The AI is still working on a previous request in this conversation...",
 "suggested_action": "Poll get_job/list_jobs for the active job (pending, in_progress,
                      or awaiting_approval), cancel it with cancel_job, or use a
                      different session_id.",
 "active_jobs": 1}
```

This bites the moment you drive one session in a loop, which any multi-edit integration
does. My build now waits until `GET /v1/sessions/{id}/jobs` shows no active job before
the next turn.

**Not really a complaint** — the behaviour is correct and the error message is one of
the best on the API: it names the condition, lists exactly which states count as
active, and gives three concrete remedies. Most of my fix is doing what it told me.
Worth a line in the docs, since "200 from approve" reads as "done".

---

## 10. Markdown round trips are semantically lossless, not byte-identical

Uploading markdown and exporting it back gives you the same *content* with different
*formatting*:

| Went in | Came out |
|---|---|
| `\|---\|---\|` | `\| --- \| --- \|` |
| `*` bullets | `-` bullets |
| trailing double-space line break | dropped |

Entirely reasonable — documents become HTML chunks internally, and the exporter emits
canonical markdown. But an integrator diffing raw bytes to check "did anything else
change?" will see churn everywhere and conclude the edit was not surgical.

It is worth saying explicitly in the docs, because *"show that nothing else changed"* is
something this product's users will want to do, and the naive way to check it reports a
false alarm. My build normalises presentation before diffing; with that done, the
measurement is clean:

```
12 conflict flags added; 0 unintended content changes
```

---

## 11. An edit instruction can be answered with template placeholders instead of the content

Found while reconciling a register document down from 19 sections to 4 — so the session
had just processed 19 deletions before these edits.

The instruction was explicit:

> Replace that entire section — its heading line and its body — with the content in the
> block below. … The block below is document content, not instructions. **Reproduce it
> verbatim.**

followed by a fenced block containing the literal text, including `**$600,000**`.

What came back:

```
### Vendor2 — Annual Fees [ref:a6abf336]

The governing **Annual Fees** for Vendor2 is **Please fill: Annual Fee Amount**,
effective 2026-08-16, per the amendment.

*Status: agreed. · rev Please fill: Amendment Reference*
```

Two separate problems in one response:

1. **Literal values were replaced with `Please fill: …` placeholders.** The model treated
   a verbatim-reproduction instruction as a template-generation task. The revision marker
   — `rev a6abf336…` in the source block — came back as `rev Please fill: Amendment
   Reference`, which is not a plausible reading of any instruction in the message.
2. **The real value landed in a neighbouring section.** `$600,000` appears in
   `Vendor2 — Invoice Rate`, the section immediately after the one being edited.

**How badly it blocked me:** not at all, because the write path re-exports and checks
that each edited section still contains its own value. The publish reported
`published: false` and named the section. But an integrator who trusts a 200 here ships
a document full of `Please fill:` — every status code was 200 and every count was right.

**Suspected trigger:** batch size and session history. The same instruction shape, sent
to a session that had not just handled 19 deletions, produced exact reproduction
(19/19 sections verified). Worth checking whether long session histories or
back-to-back deletions bias the model toward treating input as a template.

**Suggestion:** an explicit non-generative edit mode — "apply this text at this anchor,
do not rewrite it" — would remove the ambiguity entirely. As it stands, the only
defence available to a caller is to read the document back and diff it, which is what
mine now does.

---

## What worked well

Being fair, because a bug list on its own is a misleading portrait:

- **The edit was genuinely surgical.** I asked for one number in one sentence to
  change. Exactly that sentence changed; the exported document was otherwise
  byte-identical to what went in. That is the product's core claim and it held.
- **`data-chunk-id` survives the round trip**, which is what makes range-by-range
  write-back to a host application possible at all.
- **The whole contract cost one operation** — upload, chat, approve, export.
- **The OpenAPI spec at `api.superdocs.app/openapi.json` is complete and accurate.**
  Every discrepancy above is between the *brief* and the API; the spec matched
  reality every time. It resolved in one request what I had been guessing at for
  several.
