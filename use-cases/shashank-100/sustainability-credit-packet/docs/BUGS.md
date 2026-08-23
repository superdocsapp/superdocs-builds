# Bugs and rough edges found while building

Reported to hello@superdocs.app. Recorded here as they were found, with the
reproduction and what it cost the build.

---

## 1. `approval_mode: ask_every_time` is ignored when a document is created

**Severity:** high — the human approval gate is bypassed for created content.

**What I did**

```
POST /v1/chat/async
{ "message": "...", "session_id": "<fresh session>", "approval_mode": "ask_every_time" }
```

Then polled `GET /v1/jobs/{job_id}` to a terminal status.

**What I expected**

`status: awaiting_approval`, with the proposed content queued for a decision.
The docs describe `ask_every_time` as "every proposed change waits for human
approval", without an exception for creation.

**What happened instead**

The job goes straight to `completed` and the document is written. The change
carries `operation: create_full_document` and `status: auto_approved`.

**Reproduction — deterministic**

The deciding factor is the *shape* of the change, not the session state. With
`approval_mode: ask_every_time` in every case:

| Instruction against an existing document | Operation returned | Terminal status |
|---|---|---|
| "Add a short fourth paragraph about water fixtures." | (diff) | `awaiting_approval` ✅ |
| "Replace the entire contents with a new three-paragraph text." | `create_full_document` | `completed` ❌ |
| Same instruction into an empty session | `create_full_document` | `completed` ❌ |

Whenever the model decides to rewrite the document wholesale, the change is
emitted as `create_full_document` with `status: auto_approved` and the job runs
to `completed` without ever pausing. Additive and targeted edits gate correctly.

This means the gate is reliable exactly when the change is small, and silently
absent when the change is largest — the inverse of what a reviewer wants.

**How it blocked me**

My build is graded on a human approving changes before they land. I build every
document additively — a seed document, then one gated instruction per section —
so no instruction ever triggers a wholesale replacement. That is a better shape
anyway (it matches the "surgical precision" standard in the task document), but
I arrived at it to work around this, not by choice. See `packet.py`.

**Suggested fix**

Gate `create_full_document` as a single all-or-nothing change, so a reviewer
can accept or reject the whole rewrite. Right now it is the one change nobody
can refuse.

---

## 2. Job status endpoint is documented at the wrong path

**Severity:** low — costs an integrator an hour.

`llms-full.txt` describes polling at `/v1/chat/jobs/{job_id}`. That returns
`404`. The working path is **`/v1/jobs/{job_id}`**.

---

## 3. `approve` rejects `chunk_id` decisions with a 500; only `change_id` works

**Severity:** high — the documented request body crashes the server.

The docs show per-change decisions keyed by `chunk_id`:

```json
{"changes": [{"chunk_id": "abc123", "approved": true}]}
```

Sending that (with the required `job_id`, see below) returns **`500 Internal
Server Error`**. The same request keyed by `change_id` returns `200`:

```json
{"job_id": "...", "approved": true,
 "changes": [{"change_id": "c83808a4-...", "approved": true}]}
```

`change_id` is present on each entry of `metadata.pending_changes` but is not
mentioned in the approval documentation, which describes `chunk_id` throughout.
A 500 rather than a 422 also makes this look like an outage rather than a
malformed request.

---

## 4. Multi-part additions collapse into one indivisible change

**Severity:** medium — per-item approval is impossible for these.

Asking for two distinct paragraphs in one instruction returns a *single*
pending change whose `new_html` contains both. There is no way to accept one
and reject the other: the reviewer's only options are all or nothing.

The task document's standard is "approves what is right and rejects what is
wrong in the same review, item by item". That is achievable only by issuing one
instruction per item, which is what my build does — but it costs an operation
per section, so the workaround is not free.

---

## 5. `POST /v1/chat/{session_id}/approve` requires an undocumented `job_id`

**Severity:** medium — the documented request body cannot succeed.

The docs show:

```json
{ "changes": [ {"chunk_id": "abc123", "approved": true} ] }
```

Sending exactly that returns:

```
422 {"detail":[{"type":"missing","loc":["body","job_id"],"msg":"Field required"}]}
```

`job_id` is required and appears nowhere in the approve documentation. Adding
it works.

---

## 6. Approving a job that already completed returns a confusing 400

**Severity:** low.

If a job auto-completes (see bug 1) and you then send its decisions, you get
`400 "Job is not awaiting approval (status: completed)"`. Correct behaviour,
but combined with bug 1 it reads as "your approval call is broken" when the
real problem is that the gate never engaged.

---

## 7. `.csv` uploads are rejected

**Severity:** low — arguably by design, but worth stating in the docs.

`POST /v1/documents/upload` with a `.csv` returns `415 UNSUPPORTED_FILE_TYPE`,
accepting `.docx, .htm, .html, .md, .pdf, .rtf, .tex, .txt`. Tabular evidence
is common in this domain (fixture schedules, waste hauler logs), so I render
CSVs to Markdown before upload — see `sources.py`. Not a defect, but the
supported-format list is easy to miss until an upload fails.

---

## 8. `document_changes.updated_html` is null on full-document creation

**Severity:** low.

On a create, `updated_html` is `null` and the content lives only in
`document_changes.changes[].new_html`. A client that reads `updated_html`
alone gets an empty document and no error. Related to the double-parse warning
in the task document: the same class of silent-empty failure.

---

## Not a bug, recorded because it cost me an hour

The chat endpoint is not a way to read a document back. Asking "reply with only
the current document text" returns a conversational answer composed from the
model's context, which can include content that was proposed and then rejected.
I briefly believed rejected changes were landing because of this.

Exporting the session (`POST /v1/documents/export`, `format: txt`) returns the
genuinely stored document, and confirms rejection is honoured correctly — 0 of
3 trials leaked rejected content. Any verification of what a document actually
contains should go through export, never through chat.
