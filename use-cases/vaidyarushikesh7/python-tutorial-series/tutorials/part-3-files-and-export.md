# Fifty page documents: uploading, editing and exporting without falling over

**Part three of three. Real file sizes, the pre-signed upload path, compact
responses, and four failures with the handling each one needs.**

Parts [one](part-1-first-edit.md) and [two](part-2-review-gate.md) used a two
page contract. That size hides every problem worth writing about. This part uses
a fifty five page tender response with compliance tables, which is an ordinary
document in the world where people actually need this.

## Prerequisites

Python 3.10 or newer, `SUPERDOCS_API_KEY` set, and the big sample:

```bash
python3 sample/make_samples.py --big 55
```

That writes `sample/tender-response.html`, roughly 183 KB of invented bid
response: 79 numbered sections, compliance tables every fifth section, no real
company anywhere in it.

## First, get a real .docx to work with

Uploading HTML that pretends to be a Word file teaches you nothing. Turn the
sample into a genuine .docx first, using the export endpoint, which is free:

```python
payload = client.export(html=big_html, fmt="docx", filename="tender-response.docx")
save_export(payload, "sample/tender-response.docx")
```

Now there is a real Word file on disk to push through the pipeline.

## Pages and bytes are two different problems

Here is the number that surprised me: fifty five pages of text is a **0.04 MB**
.docx. Word compresses text extremely well.

So the size question splits in two, and conflating them is how people pick the
wrong upload path:

- **Byte count decides how the file gets in.** A text-only fifty page document
  goes inline happily. The same fifty pages with scanned appendices is 30 MB and
  cannot.
- **Page count decides what the edit costs you**, in time, in operations and in
  the tokens the response spends.

Only one of those is visible in a page count, and it is not the one that breaks
your upload.

## Choosing an upload path

```python
INLINE_UPLOAD_LIMIT_BYTES = 20 * 1024 * 1024

if size <= INLINE_UPLOAD_LIMIT_BYTES:
    client.upload_base64(path.name, path.read_bytes(), session_id=session_id)
else:
    # pre-signed flow
```

Where that 20 MB comes from, since the endpoint documents 50 MB: base64 inflates
a file by about a third, and the hosted gateway rejects any request body over
roughly 32 MB before the API ever sees it. So a 25 MB file becomes a 33 MB body
and dies at the front door. The API's own limit never gets a say.

The failure mode is the reason to guard it rather than discover it. The gateway
answers with **HTML**, not JSON, so your client raises a JSON decode error on a
page of markup and tells you nothing about size at all.

```python
if exc.code == 413 or (exc.code >= 400 and raw.lstrip().startswith("<")):
    raise PayloadTooLarge(
        f"{path} refused before the API saw it ({exc.code}). "
        "The body was too large for the gateway. Use the pre-signed upload flow.")
```

An HTML body on an API error means something in front of the API answered. That
is a useful signal in any stack, not just this one.

## The pre-signed path

Three calls, and the file never passes through your process memory or an agent's
context window:

```python
ticket = client.request_upload_url(name, DOCX_TYPE, size_bytes)   # POST /v1/uploads
client.put_bytes(ticket["upload_url"], data, DOCX_TYPE)           # PUT straight to storage
parsed = client.process_upload(ticket["upload_id"], session_id, name)
```

Real output:

```
upload    tender-response.docx is 0.04 MB, inline limit is 21 MB
upload    ticket 31312e09452945d59c1d50859788f396, PUT url valid 300s
upload    bytes are in storage, 2.3s, and never went through the API
parsed    412 chunks via the presigned path, parsing is not billable
```

**412 chunks.** Every paragraph, heading, table, row and cell got an addressable
ID. That is what makes "replace the body of the data protection section" a
targeted edit rather than a rewrite of the file.

Two things to hold on to: the PUT URL is valid for **300 seconds**, so request it
when you are ready to send, not at the top of your script. And parsing is **not
billable**. You pay when the AI edits, not when you load.

## Compact mode, or how not to burn your context

By default the response carries the whole updated document. On a 183 KB document
that is most of a context window, per turn.

```python
job_id = client.chat_async(session_id=session_id, message=EDIT,
                           response_mode="compact")
```

```
edit      done, 1 operation, 4 section diff(s) returned
edit      response carried 5,164 chars of diffs instead of the whole document
```

5 KB instead of 183 KB, for the same edit. On any document past about twenty
pages this should be your default, and if you need to read a section you ask for
it in plain language rather than pulling the document back.

### One result worth reading carefully

I asked it to rewrite the "Data protection" section. It reported **four** edits.

That is correct, not a bug: my generated sample cycles through twenty section
titles four times, so there are four sections called Data protection and it
edited all of them. But it is the exact shape of an expensive mistake. If your
document has repeated headings, addressing sections **by title** is ambiguous.
The chunk IDs exist for precisely this, and the fix is to name the chunk, not the
title.

## Getting large files back out

`POST /v1/downloads` returns a signed URL valid for fifteen minutes, and streams
to disk without holding the file in memory:

```python
ticket = client.download_url(session_id, fmt="pdf", filename="tender.pdf")
client.save_from_url(ticket["download_url"], "out/tender.pdf")
```

```
export    tender-response.edited.docx 0.04 MB, link valid 900s
export    tender-response.edited.pdf 0.40 MB, link valid 900s
export    tender-response.edited.txt 0.18 MB, link valid 900s
```

When a document is too large to render inside one request, there is an email
fallback that runs in the background and mails a link:

```python
except SuperDocsError:
    client.request_export_by_email(session_id, fmt=fmt, filename=name)
```

Wire the fallback even if you never hit it. It is four lines, and the alternative
is a pipeline that stops dead on the biggest document a user owns, which is
always the one that matters.

## The four failures, and what each one needs

These are not hypotheticals. Every one of them happened while writing this, and
`--demo-failures` triggers all of them on purpose:

```bash
python3 part3_files_export/large_documents.py --demo-failures
```

### 1. Processing an upload whose bytes never arrived

```
handled: /v1/uploads/5e72fcd5.../process -> 404 Upload 5e72fcd5... not found in
cloud storage. It may have expired (uploads are auto-deleted after 24 hours) or
never been completed.
```

An excellent error message, and the right handling is to re-request a ticket and
PUT again rather than retrying `process`, which will keep saying the same thing.

### 2. A pre-signed PUT that does not match its ticket

```
handled: PUT failed: 403. The pre-signed URL lasts five minutes and is bound to
the content type and size you declared. Ask for a fresh one.
<Error><Code>SignatureDoesNotMatch</Code>...
```

The signature covers what you declared. Send a different content type or a
different length and storage refuses it. Note this error comes from Google Cloud
Storage as XML, not from SuperDocs as JSON, so a client that assumes JSON on
every error will crash while handling the error.

### 3. An inline upload that is too large to inline

```
handled before a single byte left the process: too-big.docx is 21.0 MB. Base64
would push the request past the ~32 MB gateway cap. Use upload_via_url instead.
```

The cheapest failure is the one that never leaves your machine.

### 4. A long edit that pauses to ask whether to continue

Large multi-section edits can run out of their step budget and stop, waiting.
This looks exactly like the approval pause from part two and is answered by a
completely different endpoint:

```python
if meta.get("awaiting_kind") == "continue_prompt":
    client.continue_job(session_id, job_id, keep_going=True)   # fresh budget
else:
    ...  # this is a change approval, see part two
```

Check `metadata.awaiting_kind` before you decide which call to make. Sending an
approval to a continue prompt does nothing, and your job sits there until your
timeout fires.

And the timeout is the last piece: on a long document a job can sit at 99 percent
for minutes. A quiet job is a working job. Give `wait_for_job` a generous
`max_wait` and, when it expires, say the true thing:

```python
raise SuperDocsError(
    f"job {job_id} still {status} after {int(max_wait)}s. "
    "It keeps running server side; poll it again rather than starting another.")
```

Starting another is how you pay twice for one edit.

## Run the whole thing

```bash
python3 sample/make_samples.py --big 55
python3 part3_files_export/large_documents.py            # inline, since it is small
python3 part3_files_export/large_documents.py --presigned # force the large file path
python3 part3_files_export/large_documents.py --demo-failures
```

One operation for the edit, everything else free. You end with a fifty five page
tender response edited in one targeted place and exported to .docx, .pdf and
.txt, plus a verification step that reads the exported text back and confirms the
new wording is actually in it.

Because that is the through line of all three parts: the API telling you it
worked, and the document being right, are two different claims. Check the second
one.

## Where to go next

- **The MCP server**, if your editor or agent should hold this instead of your
  script.
- **Multi-document sessions**, for the case every bid team has: one master
  response and twelve variants of it.
- **Attachments**, uploaded as read-only reference material the AI can consult
  while editing, which is how you get last year's winning bid to inform this
  year's without pasting it in.

All three are in the docs at [docs.superdocs.app](https://docs.superdocs.app).

## The full series

1. [Editing a Word document from Python without touching the formatting](part-1-first-edit.md)
2. [Putting a human in front of every AI edit](part-2-review-gate.md)
3. Fifty page documents: uploading, editing and exporting without falling over

Code for all three:
[github.com/vaidyarushikesh7/superdocs-python-tutorials](https://github.com/vaidyarushikesh7/superdocs-python-tutorials)

---

*Written by Rushikesh Vaidya as part of the SuperDocs Round 2 task. Every command
and every error message above came from a real run against the live API.*
