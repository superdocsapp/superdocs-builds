# BUGS.md

Bugs and rough edges hit while building on the SuperDocs API, in the shape the
task document asks for: what I did, what I expected, what happened instead, how
badly it blocked, and how to reproduce it.

All of these were found against `https://api.superdocs.app` with a free-tier
`sk_` API key, while building the Product Manual and Quick-Start Builder in this
folder. Items 1–7 are from **2026-08-11**; items 8–13 from **2026-08-12** — 8–10
while getting the diagram-refresh path to complete one clean run, and 11–13
while building `verify`, the command that reads the published documents back and
checks them.

They live next to the build that found them, so anyone reading the code can see
what the service actually did while it was being written. The submission form
collects the same list.

No key appears in this file. Every snippet uses `$SUPERDOCS_API_KEY`.

Items 1–7 are ranked by how much they cost me; 8–13 are appended in the order
they turned up rather than renumbering the list. Item 13 is an observation
without a reproduction, and says so.

---

## 1. `upload-base64` silently replaces the focused document

**Severity: high — destroys a document, reports success.**

**What I did.** Uploaded two documents into one session, one after the other,
through `POST /v1/documents/upload-base64`, so a manual and its quick-start card
would both be open in the same session.

**What I expected.** Two documents in the session. The multipart sibling,
`POST /v1/documents/upload`, takes an `open_mode` form field documented as
`replace` / `new_focused` / `background`, so I expected either the same field or
the additive behaviour by default.

**What happened.** Both calls returned `200` with `"persisted": true`. The
second upload overwrote the first: one durable document, at `version: 2`, whose
title was still the *first* document's filename and whose `chunks_count` was the
*second* document's. Nothing in either reply said a document had been replaced.

`Base64UploadRequest` has no `open_mode` field at all — the asymmetry with the
multipart endpoint is not in the OpenAPI schema and not in the multi-document
guide, which documents `open_mode` only for `POST /v1/documents/upload`.

**Reproduce.**

```bash
SID=$(curl -sX POST https://api.superdocs.app/v1/sessions/init \
  -H "Authorization: Bearer $SUPERDOCS_API_KEY" \
  -H 'Content-Type: application/json' -d '{}' | jq -r .session_id)

for NAME in first second; do
  curl -sX POST https://api.superdocs.app/v1/documents/upload-base64 \
    -H "Authorization: Bearer $SUPERDOCS_API_KEY" \
    -H 'Content-Type: application/json' \
    -d "{\"filename\":\"$NAME.html\",\"session_id\":\"$SID\",
         \"file_base64\":\"$(printf '<h1>%s</h1>' $NAME | base64 -w0)\"}" | jq '.persisted'
done

curl -s "https://api.superdocs.app/v1/sessions/$SID/documents" \
  -H "Authorization: Bearer $SUPERDOCS_API_KEY" | jq '.documents | length'   # 1, not 2
```

**Cost to me.** About an hour, and it was only caught because the surviving
document's title and chunk count disagreed with each other. An integrator
uploading a second document into a session loses the first one and gets a
success reply.

**Suggested fix.** Add `open_mode` to `Base64UploadRequest` with the same three
values and the same default as multipart; failing that, return
`"replaced_document_id"` in the reply so the caller can see what happened.

---

## 2. Two endpoints disagree about which document is in a slot

**Severity: medium — the API's own views contradict each other.**

**What I did.** Opened a second document into an existing session with
`POST /v1/sessions/{session_id}/documents/open`, then immediately read the
session back.

**What I expected.** One consistent answer about what is in the session.

**What happened.** Within the same second, three views disagreed:

| Call | Says `doc_primary` is |
|---|---|
| `POST /v1/sessions/{id}/documents/open` (reply body) | the quick-start card |
| `GET /v1/sessions/{id}/documents` | the manual, 54 chunks |
| `POST /v1/sessions/{id}/documents/{doc}/focus` | `"title": "Halyard M1 — Product Manual"` |

After a 2-second wait, `GET .../documents` changed its answer to the card — so
part of this is a propagation delay that is not surfaced anywhere, and part is
`focus` returning a different document's title than the one it was asked to
focus.

**Reproduce.** Upload document A into a session, then
`POST /v1/sessions/{id}/documents/open` with document B's durable id, and read
`GET /v1/sessions/{id}/documents` immediately and again after two seconds.

**Cost to me.** Perhaps forty minutes, most of it spent believing my own code
had a race in it.

**Suggested fix.** Either make the read consistent after the write returns, or
document the delay and give the read a way to say "not settled yet".

---

## 3. `/v1/poll/{session_id}` rejects API keys the rest of the surface accepts

**Severity: low — clear once you hit it, but the message points the wrong way.**

**What I did.** Called `GET /v1/poll/{session_id}` with the same `sk_` key that
`POST /v1/chat`, `GET /v1/sessions/{id}/jobs` and `GET /v1/documents` had all
just accepted.

**What I expected.** `200`, or an error saying this endpoint needs a different
credential.

**What happened.** `401 {"detail": "Invalid API key"}`. The key is not invalid —
it works everywhere else, including the chat call that created the job I was
polling for. `GET /v1/users/me/limits` gets this right and says so plainly:
*"This endpoint requires a signed-in user session; API keys (sk_/lce_) are not
accepted here."* `/v1/poll` should say the same thing rather than casting doubt
on a working key.

**Reproduce.**

```bash
curl -si "https://api.superdocs.app/v1/poll/$SID" \
  -H "Authorization: Bearer $SUPERDOCS_API_KEY" | head -1
```

**Cost to me.** Ten minutes, and it would have been zero with the message
`/v1/users/me/limits` already uses.

---

## 4. "Change nothing else" changed something else

**Severity: medium — a correctness surprise in the edit path, mitigated by review mode.**

**What I did.** One turn, on a 54-chunk manual, with the instruction:

> In the rails step, change the rail torque figure from 1.2 N·m to 1.6 N·m.
> Change nothing else.

**What I expected.** One proposed change, in the rails step.

**What happened.** Two proposed changes. The second one edited the **gantry**
step, which legitimately also reads `1.2 N·m` — it is a different fastener with
the same torque figure. Both explanations read `"Parallel edit: Change the rail
torque specification…"`, so the second change describes itself as the first.

This is exactly what review mode is for and it was caught there — nothing was
approved. Recording it because the instruction was explicit, and because a
reviewer scanning forty diffs with identical explanations will approve the
second one.

**Reproduce.** Upload a document containing the same figure in two places, then
send an instruction naming one of them and forbidding other changes.

**Suggested fix.** Where a turn matches a pattern in more than one chunk, say so
in the explanation — "also found in 1 other section" — rather than giving both
changes the same sentence. The information is clearly there; it just does not
reach the reviewer.

---

## 5. A parked approval blocks its session, and the block is invisible until the next turn

**Severity: medium — a stalled review locks the conversation it is in.**

**What I did.** Sent one instruction to two documents: turn one against the
manual, turn two against the card, both in the same session, both with
`approval_mode: "ask_every_time"`.

**What I expected.** Two turns, two batches parked, then one review covering
both.

**What happened.** Turn one parked at `awaiting_approval`. Turn two came back
`409 session_busy`. The first turn's batch holds the session, so a pair of
documents in one session can never have both halves proposed at the same time —
and the failure surfaces on the *second* turn, after the first has already
spent an operation.

The 409 body is genuinely helpful (it names `list_jobs`, `cancel_job`, and
using another session), which is more than most APIs do. Two things around it
are not:

- **`cancel_job` cannot cancel the thing that is blocking.** A job parked at
  `awaiting_approval` returns `400 "Job cannot be cancelled"`. The only way out
  is to approve it with every change denied. That is discoverable but backwards:
  the suggested action names a call that does not apply to the state you are in.
- **The two views disagree about whether anything is active.**
  `GET /v1/sessions/{id}/jobs` showed nothing in an active state while
  `/v1/chat/async` was still answering `session_busy` with `active_jobs: 1`.

**Reproduce.** Open a session, send an async chat with
`approval_mode: "ask_every_time"`, wait for `awaiting_approval`, then send a
second chat in the same session.

**Cost to me.** An hour, and an architecture change: one session per document
instead of one session per pair.

**Suggested fix.** Let `cancel_job` resolve an `awaiting_approval` job, or say
in the 409 that denying it is how it is cleared.

---

## 6. Uploads lose `data-*` attributes, silently

**Severity: medium — an integrator's anchors disappear with no error.**

**What I did.** Uploaded HTML whose figures carried `data-diagram="step:laser"`,
so a later edit could point at a specific drawing without depending on wording.

**What I expected.** Attributes I put on an element to still be there. Nothing
in the docs says otherwise.

**What happened.** Every `data-*` attribute was stripped and replaced with the
service's own `data-chunk-id`. A figure comes back as
`<figure data-chunk-id="…"><img alt="…" src="…"></figure>` with nothing on it
naming which drawing it is. Attribute order changes too — `alt` before `src`,
where the upload had `src` before `alt` — which breaks a regex written against
the sent markup.

**Cost to me.** Half an hour, and a redesign of how the diagram-swap step
identifies a figure: it anchors on the caption now, which survives.

**Suggested fix.** Either preserve `data-*` on elements the service does not own,
or document the strip. If the strip is deliberate — and it is defensible —
saying so in the upload docs saves everyone this.

---

## 7. Stored image URLs come back signed, with a 754-character query

**Severity: low, once you know — but it looks exactly like a wrong URL.**

**What I did.** Uploaded an SVG via `POST /v1/documents/images/upload-base64`,
put the returned `url` into a document, and later compared what the service
proposed against what I had uploaded.

**What happened.** The `src` that comes back is the same file path with a
754-character signed query appended (`X-Goog-Algorithm`, `X-Goog-Expires`, and a
512-character signature). A check comparing URLs as strings refuses a perfectly
correct swap, which is what mine did on the first live run.

Two related things worth stating in the docs: the image upload reply carries
both a `url` and a `view_url`, and it is not obvious which is durable; and if
the served signature carries an expiry, a document stored today references an
image URL that may stop resolving later.

**Suggested fix.** Say which of `url` and `view_url` is durable, and note that
served `src` values are re-signed so integrators compare paths rather than
strings.

---

## 8. A session's memory re-proposes a change that was rejected in it

**Severity: medium–high — a mechanical instruction inherits an unrelated
conversation, and there is no way to opt out except to open a new session.**

**What I did.** In a session where an earlier turn had proposed a torque change
and had had part of it **rejected** at review, I later sent a purely mechanical
instruction into the same session: a list of `<img src>` substitutions, prefixed
with *"Make exactly these substitutions and nothing else — do not reword,
reformat, or renumber anything."*

**What I expected.** The substitutions, and nothing else. That is what the
instruction says, and there is nothing in it referring to any earlier turn.

**What happened.** The turn proposed the image swaps *and* re-proposed the
torque edit that had been rejected in that session earlier — the specific change
a human had already declined. My guard compares each proposed chunk against the
one it replaces with the image URLs masked out, so it refused the whole batch;
it did that on every attempt, and the diagram-refresh path could not complete a
single clean run until I worked out why.

Reasonable behaviour for a chat assistant, and wrong for an automated operation.
The real problem is that there is **no way to send a context-free turn**. Chat
requires a `session_id`, a session is a conversation and it accumulates, and
nothing on `POST /v1/chat/async` says "ignore the history" — no `system`
override, no `fresh`/`stateless` flag, no way to scope a turn to just this
message.

**Workaround.** Call `POST /v1/sessions/init` with the document's **durable**
id, giving a session with no history, and send the turn there. This works and is
what the build does now. It costs an extra call per document per operation, it
abandons the old session, and the fix is not discoverable from the chat docs —
you have to already believe the history is the problem.

**Reproduce.** In one session: send an edit, reject one of its proposed changes
at approval, then send an unrelated mechanical instruction in the same session
and read `metadata.pending_changes`.

**Cost to me.** Several hours, most of it spent suspecting my own instruction
wording, because a re-proposed change looks like a model being sloppy rather
than a model being well-informed.

**Suggested fix.** A per-turn flag on `/v1/chat` and `/v1/chat/async` that scopes
the turn to the message and the document, ignoring prior turns. Failing that,
one sentence in the chat docs saying the session is conversational and that
automated callers should open a fresh session per operation.

---

## 9. A turn that asks a clarifying question is indistinguishable from a turn with nothing to do

**Severity: high — the caller cannot tell "done, no change needed" from "I did
nothing and would like to talk about it".**

**What I did.** Sent the same substitution list to two documents in one
operation: a manual holding 8 figures, and a quick-start card holding 1 of those
8. The instruction listed all 8 captions.

**What I expected.** The card to make the one substitution that applies to it,
and ignore the seven figures it does not contain. Or, failing that, an error.

**What happened.** The card's job went to `status: "completed"` with
`metadata.pending_changes: []`, and `result.response` reading:

> "I haven't received the full list of substitutions, and I only see one image
> in the current document (Halyard M1 parts breakdown) […] Could you please
> provide the complete list of substitutions […]?"

So it changed nothing and asked a question. Nothing in the job's *status* says
so — `completed` with an empty change list is exactly what a document that
needed no changes returns. My code read it as "no changes proposed", approved
the manual's 8, and produced precisely the outcome the whole build exists to
prevent: the manual pointing at the new diagrams, the card still pointing at the
old one, and a run that reported 8 clean swaps. Every statement it printed was
true.

**Reproduce.** Send an instruction naming several elements to a document that
contains only some of them, and read `status` and `metadata.pending_changes` on
the resulting job.

**Cost to me.** An hour to find, and it is the one on this list I would most
want fixed — it is silent, it looks like success, and a caller doing exactly
what the docs suggest hits it.

**Suggested fix.** Distinguish the two states. A terminal status like
`awaiting_clarification`, or a boolean on the job saying the turn asked a
question rather than acting. Anything that lets a caller branch without
string-matching the prose. Partial application — do the parts that apply, report
the parts that do not — would also be a defensible answer, but the caller
knowing which happened matters more than which one is chosen.

---

## 10. `export` immediately after `approve` returns the pre-approval document

**Severity: medium — verification reads stale bytes and reports them as current.**

**What I did.** Approved a batch of 9 changes across two documents
(`POST /v1/chat/{session_id}/approve`, all 9 approved, `200`), then in the same
shell command called `POST /v1/documents/export` for both documents to check
that the approved edits had landed.

**What I expected.** The exported documents to contain the approved changes, or
some indication that they were not settled yet.

**What happened.** Both exports came back with the documents exactly as they
were *before* the approval — the previous round's image URLs in all 9 places.
No error, no staleness marker, correct-looking files of the expected size.
Re-exporting a few seconds later returned the correct, post-approval content.

Worth being precise about the evidence: I have this as **one clean observation**,
plus a contrasting one. An earlier run in the same session did `approve` and
`export` as two separate commands, seconds apart, and that export was correct.
The run that chained `approve && export` with no gap was stale. That is
consistent with a short propagation delay after approval, and I have not
measured how long it is or confirmed the exact boundary, because doing so costs
operations.

This is the same shape as item 2 — a write that returns before the reads agree
with it — on a different pair of endpoints.

**Reproduce.** Approve a batch and export the same document in the same breath,
with no delay between the two calls; compare against an export taken a few
seconds later.

**Cost to me.** Twenty minutes, and it briefly looked as though a fix I had just
made had not worked.

**Suggested fix.** Make export consistent with an approval that has already
returned, or have the approve reply carry the resulting document version so a
caller can wait for it. Both would also fix the honest version of the problem,
which is that right now the only way to be sure is to sleep and hope.

---

## 11. A session is not a handle on a document, and export is keyed by session

**Severity: high — a read silently returns a different document than the one
asked for.**

**What I did.** Published a manual and a quick-start card, each into its own
session, and recorded which session held which document. Later, exported both
by session id — `POST /v1/documents/export` — to check the published pair.

**What I expected.** Each session to still serve the document it was created
holding, or an error saying otherwise.

**What happened.** The card's session returned **the manual**. Same session id,
same call, a different document, no error and no warning. My verification step
then reported the card as having eight figures instead of one and as disagreeing
with the manual — both true of the document it was handed, and nothing to do
with the card.

Export renders what the session is *focused* on, and focus is not owned by the
integration that created the session. Opening the pair in the web interface and
clicking the other tab is enough to repoint it. `GET /v1/sessions/{id}/documents`
confirmed it: the session recorded for the card was holding a document with the
manual's `document_id`, a durable id belonging to neither published document,
and 78 chunks against the manual's 54.

The published documents were both intact the whole time. Nothing was lost. What
broke was the assumption — mine, and one the docs invite — that a session is a
stable handle on a document.

**Reproduce.** Upload a document into its own session, note the session id, open
that document in the web interface alongside another one, focus the other, then
export by the original session id.

**Cost to me.** An hour, and a verification step that confidently reported on
the wrong document. That is the part worth flagging: the failure mode is not an
error, it is a *plausible answer about something else*.

**Workaround.** Before reading, check `GET /v1/sessions/{id}/documents` actually
returns the expected `document_id`, and if it does not, open a fresh session on
the **durable** id. That is what the build does now.

**Suggested fix.** Let export name a `document_id` instead of inferring one from
session focus. Failing that, return the exported document's id in a header or
alongside the file so a caller can tell it got what it asked for.

---

## 12. Every entry in Chat History is timestamped "just now"

**Severity: low — cosmetic, but it makes the history unusable for finding anything.**

**What I did.** Opened the Chat History panel in the web interface on an account
with sessions going back three weeks.

**What I expected.** Relative times, the way the *Your files* list on the same
screen shows them ("28m ago", "2h ago").

**What happened.** All fifteen sessions read **"just now"**, including one from
2026-07-18 — twenty-four days old.

The data is correct at the API, so this is purely a rendering fault.
`GET /v1/sessions` returns a populated, distinct `last_activity` for every one:

```
2026-08-11 20:31:33   msgs=2    'raise the rail torque to 1.6 N·m'
2026-08-11 18:37:37   msgs=10   'Change the rail torque figure in the rails ste…'
2026-08-06 18:35:23   msgs=2    'In section 2 change the hourly rate to USD 135…'
2026-07-18 19:29:58   msgs=4    'can you summarise the doc'
```

The `preview` strings match the panel exactly, so the panel is reading this
endpoint and dropping the timestamp on the way to the screen.

**Reproduce.** Open Chat History on any account with a session older than a few
minutes.

**Suggested fix.** Render `last_activity`. The *Your files* list on the same
screen already formats the same kind of value correctly.

---

## 13. Two documents exist that nothing I ran created

**Severity: unknown — recorded because the evidence is solid even though the cause is not.**

**What I saw.** `GET /v1/documents` lists 28 documents on this account. Every one
the integration uploaded is titled with the **filename** it was uploaded under —
`halyard-m1-manual`, `halyard-m1-quickstart`. Two are not:

| Created (UTC) | Title | Version | `session_count` |
|---|---|---|---|
| 2026-08-11 19:52:46 | `Halyard M1 — Product Manual` | 4 | 0 |
| 2026-08-11 20:05:02 | `Halyard M1 — Quick Start` | 1 | 0 |

Those two are titled from the documents' `<h1>` headings. The client never
uploads under those names, and the account owner does not recall creating them.
The first of them, `35753835-93f5-4d47-8390-5c9d10146df9`, is the document that
had displaced the card in its session in item 11 above.

That copy is also **damaged** relative to what was published, in ways that all
point at a Word round trip:

- its `<img>` tags carry `class="docx-image"`; the published manual's carry no class
- the breakdown figure appears **five times** instead of once
- the symptom cell of each troubleshooting row contains its text **three times**
- every `-` (U+002D) has become `‑` (U+2011, non-breaking hyphen) — which is why a
  text comparison against the published document reported the two as disagreeing
  while they looked identical on screen

`source` reads `ai_created` for all 28 documents, so that field does not
distinguish these from anything else and offers no clue about origin.

**What I could not establish.** What created them. Two things are ruled out, by
snapshotting `GET /v1/documents` before and after: opening the *Your files* list
creates nothing, and **opening a document in the editor creates nothing** — no
new document, no version bump. So it is not browsing and it is not viewing.

What remains untested is the Word download path, an AI turn taken from inside
the editor, and the **Revert** control that appears above a chat message there.
The timing is at least suggestive of the last two: the copies appeared at
19:52:46 and 20:05:02, two and a half minutes after an API edit was sent to that
pair and while the editor was open on it with a completed turn and its *Revert*
button on screen. The manual copy then reached `version: 4` — something edited
it three more times after creating it — while the card copy stayed at `version: 1`.
That is a correlation and not a reproduction, which is why it is written here as
one.

**Why it is here anyway.** Whatever the cause, an integrator ends up with copies
of their documents that they did not create, under different titles, one of
which was bound to a session the integration was actively using. That is worth
knowing about even without a reproduction.

**Suggested fix.** Make `source` mean something — distinguish an API upload from
a UI action from a format conversion — so a caller can tell its own documents
from copies. And if a Word round trip is in this path anywhere, the image
duplication, the tripled table cells and the U+2011 substitution are each a bug
on their own.

---

## Not bugs, but things that cost time and are not written down anywhere

- **`POST /v1/chat` requires `session_id`,** and takes a singular `document_id`.
  Reasonable, but the quickstart's shape suggests a document-first flow, and the
  multi-document guide's "AI can work across documents in one turn" reads as
  though one turn can *edit* several. It cannot: one turn targets one document.
  That distinction decides an integrator's whole architecture and deserves one
  explicit sentence.
- **`POST /v1/chat/{session_id}/approve` requires a `job_id`** that the
  synchronous chat reply does not contain. It is available from
  `GET /v1/sessions/{session_id}/jobs`, which took a while to find.
- **Pending changes live in two places.** `document_changes.pending_changes` on
  the synchronous reply, `metadata.pending_changes` on the job object. Both are
  already-parsed lists; the JSON-encoded string only appears on the streaming
  path.
- **`GET /openapi.json` is the best documentation on the site** and is not linked
  from it. Every shape above came from there in one request.
- **A document has two ids.** The session-scoped `doc_c8c07c4a91` is what a chat
  turn names; the durable UUID underneath is what opens it in another session.
  Passing the session-scoped one to `/v1/sessions/init` returns *"None of the
  requested documents were found"*, which reads like the document is gone.
- **A turn will edit a second place it found the same figure in.** Told to change
  one torque value and nothing else, it also changed a different step that
  legitimately shares the number — twice, in separate runs. Review mode catches
  it, which is the point of review mode; it is worth knowing that "change
  nothing else" is not a constraint the turn enforces on itself.
