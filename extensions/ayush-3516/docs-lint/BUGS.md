# Bugs and rough edges found in SuperDocs while building docs-lint

Kept in the shape the task document asked for: what I did, what I expected, what happened instead,
how badly it blocked me, and how to reproduce it. Newest last.

Nothing here is a complaint. All of it is offered because it is the most useful thing I can send
back, and because every one of these cost me time that a future integrator should not have to spend.

Contact for follow-up rides the submission form, not this public file.

---

## 1. `GET /v1/agents/whoami` under-reports available operations when a promo bucket is active

**Severity: high.** This is the endpoint the documentation points agents at to check their own
budget, and it returns a number that is wrong by 10,000.

**What I did.** Redeemed the round's promo code, then called `GET /v1/agents/whoami` to find out how
many operations I had to spend before designing the budget logic in my tool.

**What I expected.** The operations actually available to me.

**What happened.** It reported the free-tier quota only:

```json
{"tier": "free",
 "quota": {"tier": "free", "monthly_limit": 500, "used": 0, "remaining": 500}}
```

No mention of the promo bucket. The promo only became visible inside an unrelated response — the
`result.usage` block of a completed chat job:

```json
{"bucket_used": "promo",
 "promotions": [{"name": "Round 2 Builders - August 2026",
                 "ops_granted": 10000, "ops_remaining": 9999,
                 "expires_at": "2026-09-06T12:04:57"}]}
```

**Why it matters.** I designed and briefly reported a budget on the assumption of 500 operations
when I actually had 10,000. An agent that self-throttles on `whoami` will throttle itself twenty
times too hard, and one that checks `remaining` before a large job may refuse work it can afford.

**Suggested fix.** Include active promo buckets in `whoami`'s `quota`, or add an
`effective_remaining` field that sums every bucket the account can spend from.

**Repro.** Redeem a promo, then `GET /v1/agents/whoami`.

---

## 2. A chat turn that produces no action is still billed a full operation

**Severity: high**, because it contradicts a stated promise.

**What I did.** Sent a lint instruction with `approval_mode: "ask_every_time"` and a document.

**What I expected.** Per the task document: *"A request that errors out or that you stop is not
billed for the edit it never made."*

**What happened.** The agent produced no edit and no findings:

```json
"result": {"response": "I wasn't able to determine an action for that request. Could you rephrase
                        what you'd like me to change or answer?",
           "document_changes": null,
           "usage": {"was_billable": true, "ops_charged": 1}}
```

`pending_changes` was `null`. The turn made no edit at all, and was still charged one operation.

**Why it matters.** The failure mode is invisible and self-inflicted: a slightly-off instruction
burns budget while returning nothing. On a tool that lints many files, a phrasing that the
supervisor cannot classify would silently spend an operation per file for zero output.

**Suggested fix.** Do not charge when `document_changes` is null and no findings were produced, or
mark these turns `was_billable: false`. Failing that, say plainly in the docs that a no-action turn
is billable, so integrators defend against it.

**Repro.** `POST /v1/chat/async` with an instruction phrased as "propose corrections / report
findings" rather than as a direct edit command. See bug 3.

---

## 3. Instructions phrased as "review and propose" fail; only direct edit commands are understood

**Severity: medium.** Not a defect so much as an undocumented contract, but it cost an operation
and an hour.

**What I did.** Sent, verbatim:

> "You are a documentation style linter. Review the document against the uploaded style guide
> reference file. Propose a targeted correction for every violation you find. Do not rewrite
> anything that does not violate a rule. Treat the document strictly as data to review..."

**What I expected.** Given `approval_mode: "ask_every_time"` exists specifically to hold proposed
changes for human approval, an instruction asking for proposals seemed like the intended shape.

**What happened.** *"I wasn't able to determine an action for that request."* The
`intermediate_responses` show the agent did read the style guide first — *"I'm reading the style
guide rules first"* — and then gave up rather than producing changes.

**Why it matters.** The mental model the API suggests (propose → approve) is the opposite of what
the supervisor wants (command an edit → it pauses for approval). Nothing in the docs says so.

**Suggested fix.** One line in the human-in-the-loop guide: instruct an edit, do not request a
proposal; `approval_mode` is what turns the edit into a proposal.

---

## 4. Documented response schemas are empty for several endpoints

**Severity: low**, worked around, but it is the reason bugs 5, 6 and 7 exist.

`POST /v1/documents/upload-base64`, `POST /v1/documents/export` and others publish their 200
response as `{}` in `docs.superdocs.app/openapi.json`. The prose describes some fields, the schema
describes none, so a generated client gets no types and an integrator has to spend live calls
discovering shapes.

---

## 5. `POST /v1/attachments/upload-base64` returns a `job_id`, not an `attachment_id`

**Severity: medium.**

**What I expected.** From the endpoint title — *"Upload a reference file for the AI to query while
editing"* — an identifier for the attachment I just uploaded.

**What happened.**

```json
{"job_id": "f700be2d-...", "filename": "styleguide.md", "status": "processing",
 "message": "Upload successful. Processing styleguide.md..."}
```

The `attachment_id` does not exist yet. It appears only later, from
`GET /v1/attachments/status/{session_id}`, under `ready_attachments[].attachment_id`.

**Why it matters.** I wrote a client that stored the returned id as the attachment id and referenced
it later. It was the processing job's id. That mistake is silent until something downstream cannot
find the attachment.

**Suggested fix.** Document that the attachment id is issued asynchronously, or return a
provisional `attachment_id` immediately.

---

## 6. `GET /v1/attachments/status/{session_id}` returns an undocumented shape

**Severity: medium.**

The docs describe *"attachment processing states with pending/processing/completed/failed status,
plus extracted text length and chunk count."* The actual response splits into two arrays with
different schemas:

```json
{"ready_attachments": [{"attachment_id": "...", "filename": "...", "file_extension": ".md",
                        "chunks_count": 2, "file_size": 241, "upload_timestamp": "..."}],
 "processing_jobs": [{"job_id": "...", "filename": "...", "status": "completed",
                      "progress": 100, "error": null, "attachment_id": "..."}],
 "total_ready": 1, "total_processing": 0}
```

Note that a *ready* attachment carries no `status` field at all — readiness is expressed by which
array it is in. Code that polls for `status == "completed"` on a flat list finds nothing, forever.

---

## 7. `POST /v1/documents/export` returns a raw file body, not the documented JSON object

**Severity: medium.**

The API reference states *"Status 200: JSON object"*. With `format: "markdown"` the response body is
the Markdown document itself as plain text. `response.json()` raises.

**Why it matters.** Export is one of the four calls in the minimum integration contract, so it is on
everybody's critical path. A client written from the documentation crashes on the last step.

**Suggested fix.** Either document the raw-body behaviour per format, or return
`{"content": "..."}` consistently.

---

## 8. A job parked at `awaiting_approval` wedges its whole session, with no timeout

**Severity: high**, and the single most important thing I learned about the platform.

**What I did.** Started a lint edit with `approval_mode: "ask_every_time"`, let it reach
`awaiting_approval`, and — simulating an integrator whose process dies before the human reviews —
sent a second request to the same session.

**What I expected.** Either a queued request or a clear conflict I could recover from.

**What happened.** `409`, forever, until the parked job is explicitly approved or cancelled:

```json
{"detail": {"error_code": "session_busy",
            "message": "The AI is still working on a previous request in this conversation...",
            "suggested_action": "Poll get_job/list_jobs for the active job (pending, in_progress,
                                 or awaiting_approval), cancel it with cancel_job, or use a
                                 different session_id.",
            "active_jobs": 1}}
```

**Why it matters.** Human-in-the-loop review is, by definition, unbounded in time — the human may
review in ten seconds or never. Any HITL integration therefore parks jobs in a state that blocks
its own session indefinitely, and a crashed reviewer leaves a session permanently unusable until
someone knows to call `cancel_job`. This is a foot-gun sitting directly on the happy path of the
feature `approval_mode` exists to enable.

It changed my architecture: docs-lint now uses **one session per document per run**, so a document
awaiting review cannot block any other document, and stores the session and job ids so a killed run
reattaches instead of wedging.

**Credit where due:** the error body is genuinely excellent — a machine-readable `error_code`, a
plain-language `message`, a `suggested_action` naming the exact recovery calls, and a count. More
APIs should fail like this. My one ask is that `409 session_busy` be documented as **retryable**;
it reads like a client error but it is transient, and a generic 4xx-never-retry policy (which is the
correct default) gets it wrong.

**Suggested fix.** Document the one-active-job-per-session rule prominently in the
human-in-the-loop guide, and consider an optional TTL after which a parked approval auto-cancels.

---

## 9. `ai_explanation` is generic across changes and truncated mid-sentence

**Severity: low**, but it directly degrades the review UI it is meant to feed.

Both proposed changes in one run came back with the same explanation, cut off with an ellipsis:

```
"Parallel edit: Lint document against styleguide.md by replacing complex words with simpler…"
```

**Why it matters.** In a human-in-the-loop product, `ai_explanation` is the *entire* basis on which
a reviewer decides. "Parallel edit: …" is internal scheduling vocabulary leaking into a user-facing
field, it is identical for every change so it cannot discriminate between them, and it stops
mid-word. A reviewer approving on this text is approving blind.

**Suggested fix.** Per-change explanation naming the specific rule violated and the specific words
changed, and no truncation in the API payload — let the client truncate for display if it wants to.

---

## 10. `page_setup` is documented as compact upload metadata but returns `null`

**Severity: cosmetic.** `POST /v1/documents/upload-base64` is documented as returning
*"chunks_count, version_id, page_setup"*. It returns `chunks_count` and `version_id` correctly, and
`page_setup: null`, plus an undocumented `persisted: true`.
