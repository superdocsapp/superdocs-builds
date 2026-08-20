# What broke, and how to reproduce it

Everything here was found while building the three part tutorial series against
the live API on 18 and 19 August 2026, on a free account with the Round 2
Builders promotional allowance. Written in the shape SuperDocs asks bug reports
to take, ready to send through the in-app bug button or by replying to the task
email: what I did, what I expected, what happened, how badly it blocked me, and
how to reproduce it.

Nothing here stopped the build. Two are real bugs, three are rough edges, and one
turned out to be my own mistake and is included because it cost the most time.

---

## 1. Bug: an inserted section lands inside the previous section

**Severity: medium.** Wrong output that reads as correct in the response summary.

**What I did.** A five section service agreement, sent to `POST /v1/chat` with:
"Insert a new section titled Confidentiality immediately after section 3, and
renumber the sections that follow it. Change nothing else."

**What I expected.** The new section after the whole of section 3, including its
charges table.

**What happened.** The new section arrived between section 3's heading and
section 3's own first paragraph, wrapped in a `div`:

```html
<h2>3. Charges and payment</h2>
<div><h2>4. Confidentiality</h2><p>Each party shall keep ...</p></div>
<p>Charges are invoiced monthly in arrears ...</p>
<table> ... </table>
```

The clause text was right and the renumbering was right: Service levels became
5, Governing law became 6. Only the placement was wrong. The response's own
`changes_summary` read "2 sections edited, 1 added, rest untouched".

The insertion appears to anchor to the heading chunk rather than to the last
chunk of the section the heading owns.

**Reproduce:** `python3 part1_first_edit/first_edit.py`. It is **intermittent**:
across six runs on 18 and 19 August, with the same prompt and the same document,
four placed the section wrongly and two placed it correctly. The script's
`orphan_headings` check prints `PLACEMENT ['3. Charges and payment']` on the bad
runs.

The intermittency is part of the finding. A single clean run does not prove the
placement logic is right, and any test suite that asserts on one run will pass
about a third of the time by luck.

**Worth knowing:** denying the change and returning the feedback "place it after
the whole of section 3, including its table" fixed it on the next attempt
(`--revise` in part two). So the model can place it correctly when told. It just
does not by default.

---

## 2. Bug: the OpenAPI schema for the export endpoint describes a JSON body

**Severity: low, but it costs everyone twenty minutes once.**

**What I did.** `POST /v1/documents/export` with `{"html": ..., "format": "docx"}`,
and parsed the response as JSON, because the published schema at
`https://api.superdocs.app/openapi.json` declares an `application/json` response
for that path.

**What happened.** The endpoint returns the file bytes with
`content-type: application/vnd.openxmlformats-...` and a `content-disposition`
header. `json.loads` fails on `PK\x03\x04`, the first bytes of a zip, which is
what a .docx is. The error a developer sees is a `JSONDecodeError` full of
binary, which points nowhere near the real cause.

The behaviour is correct and useful. The published schema is what is wrong.

**Reproduce:**

```bash
curl -s -D - -o out.bin -X POST https://api.superdocs.app/v1/documents/export \
  -H "Authorization: Bearer $SUPERDOCS_API_KEY" -H "Content-Type: application/json" \
  -d '{"html":"<h1>t</h1>","format":"docx"}' | grep -i content-type
```

---

## 3. Rough edge: nothing caps approval retries, and the text degrades across them

**Severity: medium, because it spends operations.**

**What I did.** `chat_async` with `approval_mode="ask_every_time"`, then denied
the first proposed change in every round with the same feedback, to see how
revision behaved.

**What happened.** Twenty six rounds and fifty two decisions before I stopped it
myself. Each round is a billable turn. The proposed clause also drifted: it began
as my specified wording (three year term, public domain carve out, regulator
exception) and by round twenty six had become generic boilerplate about a
"Receiving Party" with none of the specifics.

Two suggestions: a server side cap or a `max_revisions` parameter on the job, and
carrying the original instruction forward through revisions so the text does not
wander.

**My part of it:** denying every round was my bug, not the API's. Fixed by
sending feedback once. The finding is that nothing stopped me.

**Reproduce:** deny the first pending change in each round, repeatedly.

---

## 4. Rough edge: whoami does not surface a promotional allowance

**Severity: low, but it misleads exactly the agent the docs encourage you to build.**

`GET /v1/agents/whoami` reports the base monthly quota. On an account running on
the Round 2 promotional allowance it reads `used: 0, remaining: 500` and never
moves, no matter how many billable turns you run. After about thirty edits it
still said 500.

The true numbers are on each chat response under `usage.promotions`:

```json
{"bucket_used": "promo",
 "promotions": [{"name": "Round 2 Builders - August 2026",
                 "ops_remaining": 9970, "ops_granted": 10000}]}
```

The docs suggest calling `whoami` before doing work to confirm you have
operations left. An agent that follows that advice on a promo account reads a
number that is not the one being spent. Surfacing the promo bucket in `whoami`
would fix it.

---

## 5. Rough edge: presentational attributes on a table are dropped on a round trip

`<table border="1" cellpadding="6" cellspacing="0">` goes in and `<table>` comes
back, with a `tbody` added. Rows, cells and values all survive, and the docx
export still renders borders because the renderer applies its own styling. It is
only a problem if you author HTML yourself and rely on those attributes
surviving. Worth a line in the docs next to the fidelity claim.

**Reproduce:** any `/v1/chat` turn on HTML containing a table with inline
presentational attributes.

---

## 6. Rough edge: two different pauses look identical while polling

A job reaching `status=awaiting_approval` can mean two unrelated things: changes
are waiting for approval (`POST /v1/chat/{session_id}/approve`), or a large edit
paused to ask whether to continue (`POST /v1/chat/{session_id}/continue`).

They are told apart by `metadata.awaiting_kind`, which is documented, but the
shared status makes the wrong call the natural first guess, and the wrong call is
silent: the job just sits there until your own timeout fires. A distinct status
such as `awaiting_continue` would remove the class of bug entirely.

---

## Smaller notes

- Every element comes back with a `data-chunk-id` it did not go in with. Correct
  and necessary, but it means a naive string diff reports the whole document as
  changed. One sentence in the quickstart would save people the confusion.
- Editing "the Data protection section" in a document with four sections of that
  name edited all four. Correct behaviour, but a good place to point readers at
  chunk IDs for disambiguation.
- The gateway rejects request bodies over roughly 32 MB with an **HTML** error
  page rather than JSON, so a client that assumes JSON on errors crashes while
  handling the error. The pre-signed flow is the answer; a JSON 413 would make
  that discoverable.
- Pre-signed PUT failures come back as XML from Google Cloud Storage, so the same
  assumption bites a second time in a different place.
