# What broke — a live bug log

Kept **as I hit things**, not reconstructed afterwards. Every entry has what I
did, what I expected, what happened, and whether I could work around it.
Severity is my judgement of impact on an integrator, not on SuperDocs' roadmap.

Environment unless stated otherwise: agent account created via
`POST /v1/agents/signup` on 2026-08-07, free tier (500 ops/month), REST over
`https://api.superdocs.app`, Python 3.13 + httpx, macOS.

Anything I could not reproduce is marked **UNCONFIRMED** and stays in the list
anyway, because a flake an integrator hits once still costs them an afternoon.

**B1 is mine, not yours.** It is in the list because it is still a rough edge —
I hit it by reading the docs correctly and guessing wrong anyway. Three further
mistakes that were entirely my own are in **"My own bugs"** at the end, because
a bug log that only contains other people's bugs is a marketing document.

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

**Repro.** Input document: `repro/B9-before.html`. Instruction: the five-step
weekly instruction, regenerable exactly with

```python
from weekly_digest.prompts import weekly_instruction
from weekly_digest.document import archive_plan
weekly_instruction(weeks[2], archive_plan(3), weeks[1], before_html=open("repro/B9-before.html").read())
```

Send it as `POST /v1/chat` with `response_mode: "full"` and no `model_tier`, then
again with `model_tier: "pro"`, `thinking_depth: "deep"`. Outputs from both are
committed: `repro/B9-after-core-PARTIAL.html` (3 of 4 bullets, later steps
dropped) and `repro/B9-after-pro-OK.html` (all steps applied).

*Note for honesty: `weekly_instruction` has since been changed - the factual
sections are now handed over as literal HTML rather than described in prose
(see bugs.md B11). The partial-application behaviour above was observed with the
prose form, which is the form most integrators will write first.*

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

**How I worked around it, and the second half is the interesting half.** First
I pinned `model_tier="pro"`, `thinking_depth="deep"`, which fixed it. Then I
removed the ambiguity that was causing it — the factual sections are now handed
over as literal HTML rather than described in prose (see B11) — and with that,
**the default tier gets every step right and does it 4.5x faster.** The strong
model is now used only on the repair path, for a week that failed verification.

Which suggests the underlying issue is less "core is too weak" and more "a
described replacement is ambiguous, and the weaker model resolves the ambiguity
differently". That is worth knowing on your side too: an integrator who writes
the natural instruction will hit this, and the docs give them no reason to
suspect the tier.

## B10 — Three documents opened into one session return a roster of ONE, all sharing `document_id: "doc_primary"`, and the answer changes between identical GETs

**Severity: HIGH.** It makes the multi-document surface unusable for targeted
edits, which is the reason the surface exists.

**This is server-side, not my client.** The transcript below is raw `curl` +
`jq`, no code of mine involved.

**Repro** — `repro/B10-multidoc-roster.sh` (runnable; needs `SUPERDOCS_API_KEY`):

```bash
# 1. upload three documents, each into its own session (they become saved docs)
# 2. open all three into ONE new session
curl -X POST https://api.superdocs.app/v1/sessions/init \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"session_id":"'$SID'","document_ids":["<gdd>","<mechanics>","<narrative>"]}'
```
Response — three opened, **one** in the roster:
```json
{"opened": 3, "documents": [{"document_id":"doc_primary","title":"gdd","focused":true}]}
```

Then four **identical** GETs of the roster, one after the other:

```
GET /v1/sessions/$SID/documents
-> documents:[{document_id:"doc_primary", durable_document_id:"e8457b79…", title:"mechanics"}]
-> documents:[{document_id:"doc_primary", durable_document_id:"ad71a352…", title:"gdd"}]
-> documents:[{document_id:"doc_primary", durable_document_id:"e8457b79…", title:"mechanics"}]
-> documents:[{document_id:"doc_primary", durable_document_id:"ad71a352…", title:"gdd"}]
```

Three problems in one response:

1. **The roster is incomplete** — one document, never three, even though
   `opened` lists all three and `/v1/documents/{id}` finds each of them.
2. **`document_id` is the constant string `"doc_primary"` for every document.**
   `/v1/chat` takes a `document_id` "to target a specific open document", and
   `PendingChange.document_id` exists so an integrator can attribute each diff
   to the right document. Neither can work when the id is the same for all of
   them. The real identity is in `durable_document_id`, which chat does not take.
3. **It is not deterministic.** Two identical GETs, seconds apart, no writes in
   between, returned different documents. That reads like a race over which
   document is "primary" rather than a stable roster.

**One earlier oddity, honestly unresolved:** my very first `sessions/init` with
these three ids returned `404 {"detail":"None of the requested documents were
found."}`. The same ids worked moments later and every time since, so I could
not reproduce the 404 and I am not claiming it as a separate bug — but it
happened, and it is in this log because it cost me twenty minutes.

**Suggested fix:** give each open document a stable per-session id, return all
of them in the roster, and make `/v1/chat`'s `document_id` accept the durable id
as well. Until then, `focus` + one-document-at-a-time is the only reliable path
and the docs should say so.

**How I worked around it:** build #2 gives every document its own session and
holds the link graph itself (`gdd-editor/gdd_editor/workspace.py`). Every edit
is addressed to exactly one document by construction. The cost is that the model
never sees two documents at once, so a cross-document request is decomposed into
one targeted edit per document by my code rather than reasoned about in one turn.

---

## B11 — "Replace ALL X with Y" is executed as "append Y", and a changed cell can come back holding BOTH values

**Severity: medium-high.** Silent, and it corrupts data rather than failing.

Two instances from the same instruction, on the default and on the `pro` tier:

**(a) Replace read as append.** Instruction: *"Replace ALL bullets in that
section with exactly these 2 bullets, verbatim, in this order"* followed by two
bullets. Result: the three existing bullets were **kept**, and the two new ones
appended — five bullets where two were asked for.

**(b) A cell holding the old and the new value at once.** Instruction: a table
row whose Severity should become `Low` and Trend `worsening`. Result:

| Risk | … | Severity | Trend |
|---|---|---|---|
| Outsourced character art slipping two weeks | … | `Medium / Low` | `steady / worsening` |

The model wrote a *changelog* into the cell instead of changing it. Nothing in
the instruction asked for history, and a digest that says a risk is
"`Medium / Low`" is worse than useless to the person reading it on a Monday.

**Repro:** `repro/B11-instruction.txt` against `repro/B11-before.html`.

**Suggested fix:** this is a prompting-layer behaviour rather than an API defect,
which is exactly why it should be fixed *inside* the product — every integrator
who writes "replace" will hit it and most will not be diffing hard enough to
notice. A system-level rule that a targeted replacement must end with the target
containing only what was specified would close it for everyone.

**How I worked around it:** wording fixes helped and did not finish the job -
three rewordings reduced the rate without removing it. What removed it was
giving the exact replacement HTML instead of describing it, so there is nothing
left to interpret. It also stays verified — the runner re-derives the
bullets and every table row from the document bytes and compares them to the
week's input, so a recurrence fails the week rather than shipping.

---

## B12 — "Add a new section" returns the section wrapped in a `<div>`, and brought an entire table nobody asked for

**Severity: medium.** Same class as B2 — a chunk replacement that is not the
shape it should be — plus unrequested content.

Instruction (build #2, `pro`/`deep`): add one `<h2>` reading
`Traversal - Grapple Rework`, one short paragraph under it, and one row to an
existing table. Explicitly: *"Do not change any other section."*

What came back:

```html
<div data-chunk-id="40120a2e-…">
  <h2>Traversal - Grapple Rework</h2>
  <p>A design spike is open to reduce the grapple cooldown…</p>
  <table style="width: 100%; …"><thead><tr …><th>Document Title</th>…
</div>
```

1. The new heading and paragraph are **wrapped in a `<div>`**, and the `<h2>`
   inside it carries **no `data-chunk-id`**. Every other heading in the document
   has one. So to any integrator addressing sections by chunk id, the document
   did not gain a section — the content is visibly there and structurally
   invisible.
2. It also invented **a whole extra table** with columns `Document Title …` that
   nothing in the instruction asked for, in a turn that was told to change
   nothing else.

**Suggested fix:** when new block-level content is inserted, emit it as sibling
blocks each carrying its own chunk id, the same as every block already in the
document — do not wrap it in an anonymous container. That single change would
also fix the `<div><tr>` case in B2.

**How I worked around it:** I fixed my own section model rather than the symptom
— `superdocs_kit/docdiff.py` now derives sections from heading *positions* in
the bytes, so a heading nested in a div, or three levels deep, is still a
section. The invented table is caught by an explicit check in the scenario and
repaired in a follow-up operation that is counted like any other.


## B13 — A two-part instruction edited the wrong section, and said it was doing the right one

**Severity: medium-high.** It is silent, it is plausible-looking, and the only
thing that caught it was a human gate.

**What I did.** One `POST /v1/chat/async` turn, `approval_mode:
"ask_every_time"`, `pro`/`deep`, against a mechanics document whose sections are
`Dash`, `Wall-run`, `Grapple`, `Overheat pulse`, `Salvage economy` — each with a
parameter table containing a `Cooldown` row:

> "Change the Dash cooldown to 1.5 s AND change the **Overheat pulse** cooldown
> to 7 s. Make these two separate changes. Change nothing else."

**What I expected.** Two proposed changes: one in `Dash`, one in `Overheat pulse`.

**What happened.** Two proposed changes: one in `Dash` (correct), and one in
**`Grapple`** — identifiable from the diff, whose `before` text is
`Range 18 m … Cooldown 5 s`, which is the Grapple table. It proposed setting
*Grapple's* cooldown to 7 s. `Overheat pulse` was never touched.

The `ai_explanation` on that change read:

> *"Parallel edit: Change only this row's Cooldown value to the requested number.
> Preserve every…"*

— confident, and about the wrong section.

**Why it is worth a report rather than a shrug.** Every section in that document
has a row labelled `Cooldown`, which is exactly the shape of a real design
document, and the section names were given explicitly. If this had run under
`approval_mode: "approve_all"` — the default — the wrong number would have
landed in the shipped document with a success message, and the only way to
notice would be a reader who happened to know Grapple's cooldown.

**Suggested fix:** when an instruction names a section explicitly, resolve the
target section *before* the edit and either apply it there or say it could not
be found. A section name in the instruction is the strongest signal available
and it is currently being outvoted by row-label similarity.

**Repro:** `gdd review mechanics "Change the Dash cooldown to 1.5 s AND change
the Overheat pulse cooldown to 7 s. Make these two separate changes. Change
nothing else." --accept 1 --live` — against
`gdd-editor/out/snapshots/before-act-3/mechanics.html`.

**The upside, and the reason the build works this way.** This is precisely what
the human gate is for. The reviewer saw two changes, approved the correct one,
denied the wrong one — and the resulting document has `Dash 1.5 s`,
`Grapple 5 s` (untouched), `Overheat pulse 6 s` (untouched). Denying one change
did not discard the other, which is the behaviour the approve endpoint promises
and, here, delivers.

---

## B14 — Inside one multi-step instruction, content from one step landed in another step's target

**Severity: medium-high.** Same family as B2 and B12 — a chunk gets a
replacement that is not the shape it should be — but the mechanism is different
and worth separating: this is *cross-wiring between steps of a single
instruction*, not a malformed fragment.

**What I did.** One `POST /v1/chat` turn, `pro`/`deep`, carrying five targeted
edits against a formatted digest. Two of them supply literal HTML:

- STEP 3: *"Replace the `<ul>` element in the 'What changed' section with exactly
  this HTML"* — followed by `<ul><li>…</li></ul>`.
- STEP 4: *"Replace the entire contents of that table's `<tbody>` with exactly
  these rows"* — followed by `<tr><td…>` rows for the risk table.

**What happened, twice, non-deterministically.** The `<ul>` in *What changed* was
replaced by a `<div>` wrapping a **`<table>`** — and on one occasion a table with
invented column headers (`Issue | Owner | Department | Risk | Status`) that
appear nowhere in the instruction or the document. The bullet list was gone; the
document grew from 5.1 KB to 7.9 KB. The `What is at risk` table and the
`What is next` list were also left unchanged, so the turn applied roughly one of
its five steps and mixed two others together.

**Why this one is worth separating from B2.** B2 is "the replacement fragment was
structurally invalid". This is "step 3's target received something derived from
step 4", which is a *routing* failure inside a batched request. It matters
because batching is the documented, encouraged shape — up to 25 sections in one
operation — and the more steps a caller batches, the more surface this has.

**Suggested fix:** bind each instructed edit to a resolved target *before* any
content is generated, and validate the replacement against that target's element
type. A `<ul>` target may only receive a `<ul>`. That single check closes B2,
B12 and B14 together — it is the whole class rather than three cases.

**How I worked around it, and it changed the design rather than adding a retry.**
The runner verifies every week from the document bytes, and on failure it
**decomposes** rather than repeating: one turn for the archive, one for the
status line and the three factual sections, each naming what it must not touch.
Re-sending the same instruction was the original repair and it mostly reproduced
the same confusion — which is the general lesson here. If a batched instruction
confuses the model, the fix is fewer things per turn, not the same things again.
Failed attempts are kept in `weekly-digest/out/arm-a-edit/failed-attempts/`
with the exact instruction that produced them.

---

# My own bugs

Not SuperDocs' fault. Here because they cost real time or real money, and
because the same four hours that found twelve bugs in someone else's product
should be honest about the ones it created.

## M1 — I committed a live API key as a test fixture

Writing the redaction tests, I used the **real key** as one of the
"credential-shaped strings that must be redacted". It went into
`tests/test_budget_and_secrets.py` and four local commits.

Caught by running the pre-PR check written down in `PR-DRAFT.md`
(`git log -p --all | grep -E 'sk_[a-z0-9]{8}'`) — not by noticing at the time,
which is the entire argument for having the check be a written step rather than
a habit. Fixed: fake constant, four commits rewritten, `refs/original` and the
stash deleted, reflog expired, objects pruned, verified zero occurrences across
every git object. Nothing had been pushed. Full account in `ASSUMPTIONS.md` A7,
including the rotation command, because a secret that touched disk should be
rotated even when the exposure was local.

The uncomfortable part: `superdocs_kit/secrets.py` redacts anything key-shaped
before it can reach a fixture, and there is a test asserting it. None of that
helps against a key a human types into a source file.

## M2 — Omitting `--live` spent five real operations

`build_transport` treated `live=None` as "decide for me": no explicit flag,
so look for a key — and it found one in `.env`. A command a reader would
reasonably take for a dry run therefore ran against the live API and spent five
operations before I noticed.

Fixed by making absence of `--live` mean **replay, unconditionally**. The
expensive path has to be asked for by name. Also added `--out`, so a replay
writes elsewhere and can never overwrite the committed artefacts of the run it
is replaying.

The general shape of this mistake is worth naming: a default that is convenient
when you have credentials is a trap for everyone who does not, and "helpful
auto-detection" on the path that costs money is the wrong kind of clever.

## M3 — A test that hung by building its own input

`test_deep_parse_is_bounded` nested `json.dumps` fifty deep to check the parser
terminates. Each pass roughly doubles the escaping, so the *test* was building a
petabyte-scale string and the suite hung — in the one file whose job was to
prove a pathological input terminates. Twelve levels proves the same thing in
microseconds. The comment in the test says so.

## M4 — I assumed one passing week was evidence

Having made the weekly instruction unambiguous, I re-tested the cheap model tier
on the week that had been failing, watched it pass, and switched the whole run
to it. Over the next four weeks it failed first-attempt verification about 60%
of the time. n=1 is not a measurement, and I of all people should not have
treated it as one in a repo whose entire argument is that claims need numbers.
Reverted, and the reasoning — including the error — is in `runner.py` where the
setting lives.
