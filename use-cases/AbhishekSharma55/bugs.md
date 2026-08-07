# What broke — a live bug log

Kept **as I hit things**, not reconstructed afterwards. Every entry has what I
did, what I expected, what happened, and whether I could work around it.
Severity is my judgement of impact on an integrator, not on SuperDocs' roadmap.

Environment unless stated otherwise: agent account created via
`POST /v1/agents/signup` on 2026-08-07, free tier (500 ops/month), REST over
`https://api.superdocs.app`, Python 3.13 + httpx, macOS.

Anything I could not reproduce is marked **UNCONFIRMED** and stays in the list
anyway, because a flake an integrator hits once still costs them an afternoon.

**Two of these are mine, not yours** (B1, B7). They are in the list because
they are still rough edges — I hit them by reading the docs correctly and
still guessing wrong.

| # | Severity | One line |
|---|---|---|
| B2 | **High — silent data loss** | A multi-section edit replaced a `<table>` with a `<div><tr>…`, destroying the header row and every prior row. Non-deterministic. |
| B3 | **High — false success** | The same turn reported `"1 section edited, rest untouched"` while having destroyed a table and skipped an instructed change. |
| B4 | Medium | An instructed step was silently skipped; no error, no mention in the response text. |
| B5 | Medium — blocks round-tripping | HTML export drops every `data-chunk-id`, so exported HTML cannot be re-uploaded and diffed at section level. |
| B6 | Low — formatting not byte-preserved | `font-family:Inter,Calibri` is stored as `Inter , Calibri`. Happens on upload, no AI involved. |
| B1 | Docs / DX | `/v1/documents/export` returns the raw file, not a JSON envelope, unlike every other endpoint. |
| B7 | Docs / DX | Free-tier agent accounts get 500 ops, not the 10,000 the task PDF implies; there is no documented way for an agent to learn its cap before signing up. |

---

## B1 — `/v1/documents/export` is the only endpoint that does not return JSON

**Severity:** docs / developer experience. *(My bug, and I am still reporting it.)*

Every other endpoint on the surface returns `application/json`. Export returns
the **file itself** — `text/markdown`, `text/html`, or the docx media type —
with a `Content-Disposition` header. I had written one transport that parsed
every 200 as JSON, so my first four export attempts returned `{}` and I spent
twenty minutes convinced the session had no document in it.

**Repro**
```
POST /v1/documents/export  {"session_id": "...", "format": "markdown"}
-> 200, content-type: text/markdown; charset=utf-8   (not application/json)
```

**What made it hard to see:** the OpenAPI `responses` block for this path does
not state the media type, and the endpoint description talks about "a JSON
envelope" — but only in the sentence about the *MCP* surface. On REST it is raw
bytes. Two different shapes for the same operation, documented in one paragraph.

**Suggested fix:** either state the REST media types in the OpenAPI `responses`
object, or (better) make the description's first line say *"REST returns the
file bytes; MCP returns a JSON envelope with a signed `download_url`."*

---

## B2 — A multi-section edit destroyed a table: `<table>` replaced by `<div>` wrapping a bare `<tr>`

**Severity: HIGH.** Silent data loss inside a document the API said it had left
alone.

**What I did.** One `POST /v1/chat` turn carrying a five-step instruction
(update a status line, replace bullets in two sections, rewrite the rows of one
table, and insert one summary row at the top of a second table). This is the
documented "up to 25 sections of targeted edits in a single request" shape.

**What I expected.** Five sections edited, tables intact.

**What happened.** The Archive `<table>` chunk — header row, styling, and its
existing data row — was replaced wholesale by:

```html
<div data-chunk-id="c67218bf-…"><tr><td>Week 2</td><td>2026-01-12 to 2026-01-18</td>
<td>Hired combat designer, migrated Perforce to Git LFS, completed grapple
prototype.</td><td>Controller difficulty un-tuned, outsourced character art
delay.</td></tr></div>
```

Note what that is: a **bare `<tr>` inside a `<div>`**, which is not valid HTML
and cannot render as a table row. The `<thead>`, the column headers, the
borders, the shading and the previous week's row are all gone. The document
lost data and the caller was told it had not.

**Repro material committed:** `repro/B2-before-week-02.html` (the exact input
document), `repro/B2-instruction.txt` (the exact instruction),
`repro/B2-after-week-03-CORRUPTED.html` (the output).

**Non-deterministic — and I think that is the important part.** I replayed the
*identical* instruction against the *identical* input document in a fresh
session and it produced a completely correct five-section edit with the table
intact (`repro/B2-after-second-attempt-OK.html`). I also tried three smaller
variants — insert-a-row, replace-all-rows, and summarise-then-insert, each as a
single-step instruction on a small document — and **all three were correct**.
So I could not minimise it below "a five-step instruction on a real document",
and it does not fire every time.

**My reading of the cause** (a guess, flagged as one): when the model authors a
replacement for a chunk whose element is a `<table>`, nothing validates that the
replacement is still a table. A bare `<tr>` was accepted and wrapped in a `<div>`
by whatever sanitiser runs next.

**Suggested fix, and it closes the class rather than the case:** validate that a
chunk's replacement HTML has the same *structural role* as what it replaces —
a `<table>` chunk may only be replaced by a `<table>`, a `<tr>` by a `<tr>`, a
list by a list. On mismatch, reject the change and let the model retry, rather
than wrapping the fragment in a `<div>` and reporting success. That one check
would also catch the `<li>`-replacing-a-`<ul>` version of the same mistake.

**How I worked around it:** I did not remove the multi-section edit — it is the
whole cost argument for the build. Instead the runner validates nine structural
and fidelity invariants from the document bytes after every turn, and on failure
re-sends the same instruction with `document_html` set to the last known-good
version (a verbatim reload plus the edit, in one operation). If that also fails
the week is rolled back to the last good state rather than left corrupt. Every
repair is counted as a real operation in the cost measurement, because it is one.

---

## B3 — `changes_summary` reported success for a turn that lost data

**Severity: HIGH.** This is a trust bug rather than a rendering bug.

In the B2 turn above, the response carried:

```json
"changes_summary": "1 section edited, rest untouched"
```

Two things in that sentence are false. It was not one section — the turn also
rewrote the risk table and both bullet lists. And "untouched" is exactly what
the destroyed Archive table was not.

An integrator building an approval UI on top of `changes_summary` — which is
what it is for — would show a reviewer "1 section edited, rest untouched" over a
diff that silently dropped a table. That is the worst possible failure mode for
a human-in-the-loop product.

**Suggested fix:** derive the summary from the applied change set rather than
from the model's own narration of what it intended, and make "rest untouched" a
*computed* claim (compare the stored chunk map before and after) rather than a
phrase. If it cannot be computed, do not assert it.

---

## B4 — An instructed step was silently skipped

**Severity: medium.**

Same turn as B2. STEP 2 of the instruction said, unambiguously:

> The bold status line directly under the title must read exactly:
> `Week 3 · 2026-01-19 to 2026-01-25 · Phase: Pre-production`

The output still said **Week 2**. No error, no warning, and the response text
did not mention it. The turn had five steps; four were applied.

I do not think "the model missed a step" is a bug in itself — models do that.
The bug is that **nothing told the caller**. A response that lists which
instructed changes it believes it applied would have made this a one-line check
instead of a manual diff.

**Suggested fix:** on a multi-step instruction, return the model's own
step-by-step account of what it applied and what it declined, so a caller can
assert on it. Even a plain list would do.

---

## B5 — HTML export drops every `data-chunk-id`, so exports cannot be round-tripped

**Severity: medium.** Blocks a whole workflow rather than breaking one call.

```
POST /v1/documents/export {"session_id": "...", "format": "html"}
```
returns clean HTML with all the styling intact but **zero `data-chunk-id`
attributes**, while the same document's HTML from `/v1/chat` (`response_mode:
full`) and from `upload-base64` (`return_html: true`) carries them all.

Why it matters: exports are free and chat turns are billable, so the natural
way to snapshot a document you are editing over 52 weeks is to export it. But an
exported snapshot has lost the section identity, so you cannot diff two exports
at section level, and you cannot re-upload one and continue editing the same
sections. I had to keep the billable turn's `updated_html` as my snapshot
instead, which means my archive of document states is only as complete as my
chat history.

**Suggested fix:** an `include_chunk_ids: true` option on HTML export. It is
already the same serialiser.

---

## B6 — Inline `font-family` is reserialised with spaces around the commas

**Severity: low, but it is a formatting-preservation claim.**

```
sent  : style="font-family:Inter,Calibri,Arial,sans-serif"
stored: style="font-family:Inter , Calibri , Arial , sans-serif"
```

This happens on **upload**, with no AI turn involved at all
(`POST /v1/documents/upload-base64`, `return_html: true`), so it is the HTML
parser, not the model. It is valid CSS and renders identically, so nothing
breaks — but it means an uploaded document is not byte-identical to itself, and
"formatting is preserved exactly" is a claim the product makes loudly. Anyone
building a byte-level fidelity test will trip on this in their first hour, as I
did.

---

## B8 — After re-uploading a document into a live session, the next chat turn returned the whole document twice

**Severity: HIGH.** Silent duplication of an entire document. **UNCONFIRMED at
small scale** — see the honest caveat at the end.

**What I did.** Inside one long-lived session:

1. `upload-base64` the digest (11 chunks, ~5 KB) — fine.
2. Several `POST /v1/chat` edit turns — fine.
3. `upload-base64` the *last known-good* HTML back into the **same session**, to
   roll the document back after a failed edit. The response looked correct:
   `chunks_count: 11`, the returned HTML was the single document.
4. The next `POST /v1/chat` turn returned `updated_html` containing **the entire
   document twice** — 23 chunks, ~10 KB, two `<h1>`s, and two copies of every
   one of the four `<h2>` sections.

Evidence committed: `weekly-digest/out/arm-a-edit/failed-attempts/` from the run
that hit it — `week-05-attempt-1.html` and `week-06-attempt-1.html` are the
doubled documents; `week-04-attempt-1.html` from the same run is the single
document, so the transition is visible in the artefacts.

Once doubled it stayed doubled, and every subsequent week failed verification
(two `<h1>`s, four extra `<h2>`s) until the run was stopped.

**Then I found the actual trigger, and it is worse than I first thought:
a REUSED SESSION ID.**

The isolating experiment, three runs, one variable:

| Session | Sequence | Result |
|---|---|---|
| brand new id | upload → chat(`document_html`) → chat(`document_html`) | **clean**, 1 `<h1>`, 11 chunks, both turns |
| brand new id | upload → chat → re-upload → chat | **clean**, 1 `<h1>` |
| **id reused from an earlier run** that still held an older version of the same document | chat with `document_html` = the week-1 HTML | **TRIPLED**: 3 `<h1>`s, 34 chunks, 15,946 bytes from a 5,081-byte input |

So: when a session already holds a document and you send `document_html` for the
*same* document at a *different* version, the content is **concatenated onto
what is there** instead of replacing it. Both the endpoint documentation for
`upload-base64` (*"the reliable way to REPLACE a session's document with exact
content you already hold"*) and the `document_html` field description (*"pass it
only to load new content or replace the document wholesale (a verbatim load)"*)
promise replacement. On a stale session it appends.

It compounds: my run went 1 copy → 3 copies in a single turn, and every
subsequent week inherited the mess.

**Repro** (needs a session id that has been used before with different content):
```
POST /v1/chat  {"session_id": "<previously-used-id>",
                "message": "<any edit>",
                "document_html": "<full HTML of an OLDER version>",
                "response_mode": "full"}
-> updated_html contains the document 2-3 times
```
Artefacts: `weekly-digest/out/arm-a-edit/failed-attempts/` from that run.

**Suggested fix:** make a `document_html` load unconditionally replace the
session's document — that is what "wholesale" and "verbatim load" mean, and it
is what the field is for. If there is a real reason to append in some case, it
should be an explicit flag, and the default should be the documented behaviour.
Failing that, the response should say which it did.

**How I worked around it, and it changed the architecture.** I removed
re-uploading from the design entirely. The runner now keeps the last known-good
HTML on disk and passes it as `document_html` on every chat turn, which the API
defines as a verbatim load. The client owns the document of record; the session
is just the editor. That is free — the ledger shows every week still charges
exactly one operation — and it also made crash-resume and rollback trivial,
because week N is computed from week N-1's bytes on disk and nothing else.

---

## B7 — An agent account gets 500 operations, and cannot find that out before signing up

**Severity: docs / DX.**

`POST /v1/agents/signup` returns a free-tier account with `monthly_limit: 500`.
The hiring task's own materials point at 10,000 operations via the `BUILDER26`
promo, which applies to a *human* account — so an agent that follows the
documented self-signup path silently gets a budget 20x smaller than the one the
task was scoped against.

That is a reasonable product decision. The rough edge is that there is no way to
learn the cap **before** signing up: `/v1/agents/whoami` needs a key, and the
signup response is the first place the number appears. An agent planning a
52-week measurement has to commit to a budget before it can read one.

**Suggested fix:** publish the agent free-tier limits in the docs page for
`/v1/agents/signup`, and mention that `POST /v1/promo/redeem` exists on agent
accounts too (I found it in the OpenAPI spec, not the docs).

---

## B9 — On the default model tier, a multi-step instruction is applied partially, and reported as done

**Severity: HIGH for anyone driving the API programmatically.**

The endpoint sells "up to 25 sections of targeted edits in a single request",
and that is the shape any batching integrator will reach for. On the default
tier (`model_tier` unset, i.e. `core`) a five-step instruction was, in four
consecutive weeks, applied **partially**:

- STEP 2 (rewrite the Archive table) — done.
- STEPS 1, 3, 4, 5 (status line, two bullet lists, the risk table) — **not done**,
  no error, no mention in the response text.

Worse, in one of those turns the model *created a second table* with invented
column headers (`Date Range`, `Completed`, `Issues/Notes` instead of `Dates`,
`Shipped`, `Risks carried`) and left the original table in place below it.

**Repro:** `repro/B9-instruction.txt` against `repro/B9-before.html`, sent as
`POST /v1/chat` with `response_mode: full` and no `model_tier`.
Compare `repro/B9-after-core-PARTIAL.html` with `repro/B9-after-pro-OK.html`.

**The isolating variable is the tier.** The *identical* instruction against the
*identical* input document with `model_tier: "pro"`, `thinking_depth: "deep"`
passed all thirteen of my structural and fidelity checks on the first attempt:

| tier | thinking | ops charged | seconds | result |
|---|---|---|---|---|
| `core` (default) | default | 1 | ~20 | 4 of 5 steps dropped, 4 weeks running |
| `pro` | `deep` | 1 | ~86 | all 5 steps applied, first attempt |

**Both cost one operation.** The cheaper tier is not cheaper in operations — it
is only faster — so the default is strictly worse for multi-section work, and
nothing in the docs says so.

**Suggested fix:** either scale the default tier with the number of distinct
changes an instruction asks for, or — cheaper and more honest — return the
model's own list of which instructed steps it applied, so a caller can assert.
At minimum, the `/v1/chat` docs should say that multi-section batching is
unreliable on `core` and name the tier it needs.

**How I worked around it:** the runner pins `model_tier="pro"`,
`thinking_depth="deep"` for both arms of the measurement, and still verifies
every turn from the document bytes rather than trusting it.
