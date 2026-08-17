# SuperDocs integration — verified request and response shapes

Every shape below was captured from the live API, not copied from documentation.
Captured 10 August 2026 against `https://api.superdocs.app`.

Where this disagrees with `docs.superdocs.app`, the disagreement is the point —
see [PROGRESS.md](../PROGRESS.md) for the full list of sixteen findings and how
badly each one blocked.

---

## The four calls

```
upload   POST /v1/documents/upload-base64   filename, file_base64, session_id
edit     POST /v1/chat/async                message, session_id, approval_mode
poll     GET  /v1/jobs/{job_id}             status, result.document_changes
approve  POST /v1/chat/{session_id}/approve job_id, approved
export   POST /v1/documents/export          session_id, format
```

Auth is `Authorization: Bearer sk_...` on every call.

A **session** is the handle, not a document id. The session is created by passing
a `session_id` of your own choosing to the upload; every later call refers to it.

---

## 1. Upload

**Documented:** `document_html`.
**Actual:** answers `422` naming `filename` and `file_base64` as required.

```jsonc
// POST /v1/documents/upload-base64
{
  "filename": "RO-1001.html",     // the extension decides how it is parsed
  "file_base64": "PGh0bWw+...",   // base64 of the HTML
  "session_id": "c6d1e604-d098-4d44-973d-68821bec4f23"
}
```

```jsonc
// 200
{
  "html": null,
  "session_id": "c6d1e604-d098-4d44-973d-68821bec4f23",
  "filename": "shape.html",
  "chunks_count": 1,
  "version_id": "9703f074-5b03-439d-8412-422749a51c92",
  "page_setup": null,
  "persisted": true
}
```

`chunks_count` is **1** for a document of this size. That matters: the whole
document is one chunk, so every edit rewrites all of it and the last writer wins.

**The extension is load-bearing.** The same HTML uploaded as `.txt` is stored
literally — the editor then displays `<html><body><p>...` as visible text in the
document. As `.html` it parses. The upload response is identical either way.

---

## 2. Edit

The instruction is read by an agent, not parsed as a form. A structured
`SECTION: COMPLAINT\n<text>` produces *"I am not sure what you would like help
with"* — no error, no edit.

`approval_mode` must be a **string**; a boolean is rejected with `422`.

```jsonc
// POST /v1/chat/async
{
  "message": "Add COMPLAINT, CAUSE and CORRECTION sections to the end of this repair order, using exactly the text below, word for word. ...",
  "session_id": "c6d1e604-...",
  "approval_mode": "manual"
}
```

```jsonc
// 200
{
  "job_id": "5e1c4c21-f8b3-48e4-8248-60069555c7a9",
  "session_id": "c6d1e604-...",
  "status": "pending",
  "message": "Chat request queued for processing"
}
```

---

## 3. Poll

```jsonc
// GET /v1/jobs/{job_id}  → 200
{
  "job_id": "5e1c4c21-...",
  "organization_id": null,
  "user_id": "0f2a305d-...",
  "session_id": "c6d1e604-...",
  "job_type": "chat",
  "status": "completed",          // pending → processing → completed
  "created_at": "2026-08-10T19:22:48.172125",
  "updated_at": "2026-08-10T19:22:52.875296",
  "progress": 100,
  "result": { "...": "see below" },
  "error": null,
  "metadata": { "message": "<the instruction that was sent>", "...": "..." }
}
```

### `result.document_changes` — where the edits actually live

```jsonc
{
  "updated_html": "<p data-chunk-id=\"cb5d7907-...\">TECHNICIAN NOTE:<br/>Replaced coil.</p>\n<div data-chunk-id=\"8dabae32-...\"><h2>CAUSE</h2><p>Coil failed.</p></div>",
  "version_id": "9446a81e-...",
  "changes_summary": "1 added, rest untouched",
  "requires_approval": null,
  "pending_changes": null,
  "changes": [
    {
      "status": "auto_approved",
      "chunk_id": "new",
      "old_html": null,
      "new_html": "<h2>CAUSE</h2><p>Coil failed.</p>",
      "change_id": "729063b4-67ad-4bff-b17f-77b4db936828",
      "operation": "create",
      "document_id": "doc_primary",
      "ai_explanation": "✅ I have added the CAUSE section to the end of the document, as you requested.",
      "insert_after_chunk_id": null,
      "insert_before_chunk_id": null
    }
  ],
  "chunk_diffs": null,
  "concurrent_merges": null,
  "focused_document_id": "doc_primary"
}
```

**Read `changes`, not `updated_html`.** `updated_html` is the entire rewritten
document; `changes` is one entry per edit with `old_html` / `new_html`. This
client got it wrong at first and consequently reported every edit as a single
change covering the whole document.

**`metadata.pending_changes` is `null`.** The documented location for pending
changes is empty in practice. The client reads it anyway, second in preference
order, in case it is populated on other plans.

**`status: "auto_approved"` despite `approval_mode: "manual"`.** This is the
single most consequential finding. See below.

---

## 4. Approve

**Documented:** a `changes` array.
**Actual:** answers `422` requiring top-level `job_id` and `approved`.

```jsonc
// POST /v1/chat/{session_id}/approve
{ "job_id": "5e1c4c21-...", "approved": true }
```

Approval is granted **per job**, so one instruction is one approvable unit. That
is why `ProposedChange.change_id` is the job id rather than the API's own
`change_id`.

A job that already applied its change answers:

```
400 {"detail":"Job is not awaiting approval (status: completed)"}
```

which, given the finding below, is every job.

---

## 5. Export

Returns **plain text, not JSON**, when `format` is `markdown`:

```
TECHNICIAN NOTE:
Replaced coil.

## CAUSE

Coil failed.
```

The client falls back to `{"_raw": response.text}` when a response is not JSON.

Exports are **free** — they cost no operations. That is what makes
verify-by-export affordable as a correctness check on every write.

---

## The finding that shaped the build

`approval_mode` does not hold a change for a human.

Six values were sent to a live job: `manual`, `review`, `required`, `always`,
`hitl`, `approval`. Every one was accepted. Every job reached `completed`. Every
change came back marked `auto_approved`. `requires_approval` was `null`
throughout.

An integrator following the documentation would believe they had built a review
step, and would ship an agent that edits documents unsupervised. Nothing in any
response says otherwise — the job simply succeeds.

**Consequence for this build:** the human gate moved upstream. A section the
technician's note does not support is *never sent*. It cannot be applied by
accident, because it never reaches the API. That guarantee does not depend on a
flag working.

---

## Other measured behaviour worth knowing

| Behaviour | Detail |
|---|---|
| Edits silently do nothing | Three sequential edits lost sections; the job reported `completed` each time. |
| Text is truncated mid-word | `"Replaced coil. ... Road tested, no misf"`, status `completed`. |
| Sections are appended, not filled | Uploading empty `COMPLAINT:` headings produced a document with every heading twice. |
| Heading format varies per run | `COMPLAINT:`, `<strong>COMPLAINT:</strong>`, and markdown `### COMPLAINT` all observed. |
| The uploaded text reaches the agent | A note containing "IGNORE ALL PREVIOUS INSTRUCTIONS" changed the editor's behaviour. It never produced the invented repair, but it did delete the technician note. |

Each is reproduced by a test in `tests/`, and each is why the pipeline verifies
against the exported document rather than trusting the API's report.

---

## Cost

Twelve repair orders end to end cost **17 operations** — one per document, plus
one for each retry. Uploads, polls and exports were not billed as operations.

Worth knowing before you size a batch: the cost is per *edit*, and a document
needing two retries costs three. Verification is free, so checking is always
cheaper than guessing.
