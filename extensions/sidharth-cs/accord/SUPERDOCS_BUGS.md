# SuperDocs — bugs and rough edges hit while building ACCORD

Reported in the shape the task asks for: what I did, what I expected, what
happened instead, how badly it blocked me, and how to reproduce it.

Context for all of these: a live Zoom meeting drafts into one SuperDocs
session via `chat_async` → poll → `approve_changes`, with a deterministic
validation gate between the proposal and the approval. Roughly 200 real
drafting runs against the live API between 2026-08-05 and 2026-08-19.

Severity is my own judgement of how badly it blocked this build, not a guess
at your priorities.

**Status as of 2026-08-23.** SuperDocs announced a large update on this date
— accuracy, hallucination, review mode, and "almost all the user-reported
bugs from the past few months". I re-ran the full pipeline against the live
API afterwards. Placement and cross-section contamination were noticeably
better: several runs completed all eight sections with zero gate rejections,
which had not happened before. Two findings still reproduced on 2026-08-23:
`revert_session` refusing with 400, 404 and 409 in the same session, and an
edit to one section deleting content another section had just committed.
Everything below was observed on the dates given, against the API as it
stood then; treat the older entries as history rather than as claims about
today's build.

---

## 1. Review mode is bypassed — edits apply themselves without approval

**Severity: highest.** This is the one I would fix first.

**What I did.** Called `chat_async` with `approval_mode="ask_every_time"`,
then polled the job expecting to reach `awaiting_approval` so my gate could
inspect the proposal before anything touched the document.

**What I expected.** Every edit stops at `awaiting_approval`. That is what
`ask_every_time` means, and my whole safety design rests on it.

**What happened.** Some jobs skip the approval state entirely: the job
settles as `completed` with `document_changes` already applied to the
document. The proposal was never offered, so nothing that validates
proposals ever saw it.

**Why it matters.** This is not just a missed hook — it is the safety layer
silently not being there. Everything my gate rejects went straight into the
document through this path: placeholder text, an invented table, and
duplicated content (bugs 2–4 below, all found in one real export).

**Repro.** Run any multi-section drafting request with
`approval_mode="ask_every_time"` and log every job's terminal status. A
minority settle `completed` with a populated `document_changes` instead of
`awaiting_approval`. It is intermittent, not deterministic, which is part of
what made it expensive to find.

**Workaround I shipped.** `structural_defect(html_before, html_after)` in
`backend/app/superdocs/integrity.py` — a second, document-level check on the
auto-apply path, because the proposal-level check cannot run there.

I note the task document says review mode is "a strong safety layer, not a
hard guarantee." I would still call this a bug rather than a documented
limit: the request explicitly asked for approval on every edit, and did not
get it.

---

## 2. Placeholder text written into the document

**Severity: high** — visible in a customer-facing export.

**What I did.** Asked for a section to be filled from meeting facts.

**What I expected.** Either the section is filled from the facts I supplied,
or it is left alone.

**What happened.** The document came back containing literal
`Please fill: Project assumptions and dependencies` and
`Please fill: Status`.

**Repro.** Ask for content in a section where the supplied facts do not
cover every field the model thinks the section needs. Confirmed in a real
exported `.docx`, not just the HTML.

**Workaround.** Explicit prompt instruction never to emit `Please fill:` /
TBD / TODO, plus a deterministic rejection in `validator.py` and again in
`integrity.py` for the auto-apply path. The prompt instruction alone was not
sufficient.

---

## 3. An entire duplicate table invented

**Severity: high.**

**What I did.** Asked for content to be added to a document that already had
one `Project Details` table.

**What I expected.** Content added; existing table untouched.

**What happened.** A second, complete `Project Details` table appeared,
carrying `Please fill: Status` — a field that does not exist in my template
at all.

**Repro.** Same export as bug 2. Reached the document through the auto-apply
path in bug 1.

**Workaround.** Table-count comparison before/after; any gain is refused.

---

## 4. One sentence restated as four rephrased paragraphs

**Severity: medium** — it does not corrupt the document, it bloats it, and a
reader notices immediately.

**What happened.** A single spoken fact came back as four near-identical
paragraphs, differently worded, in the same section.

**Workaround.** Sentence-level near-duplicate detection at 0.75 overlap.

---

## 5. 409 wedge — a session becomes permanently unusable after a successful approval

**Severity: highest for a live product.** This one cost me the most time.

**What I did.** `approve_changes(job_id, True)` returned success. I then
polled the job for its post-approval settlement.

**What I expected.** The job settles `completed`, and the session is clean
for the next edit.

**What happened.** The poll never reached a terminal state. The next
`chat_async` on that session returned **409 Conflict** — the session was
left dirty by an approval that had itself succeeded. `revert_session` then
returned **409** because a job was still in flight. So: cannot proceed,
cannot roll back, cannot recover. My retry logic looped roughly six minutes
before I made it fail fast.

**Why it matters most in this product.** In a live meeting there is no
second chance — the conversation keeps going while the session is wedged.

**Repro.** Approve a change, then have the settlement poll time out (easiest
under load). Any subsequent `chat_async` on that `session_id` 409s.

**Workaround.** `_is_conflict()` detects 409, sets `_unrecoverable`, and
fails fast to a terminal error state rather than retrying. Recovery is
manual.

---

## 6. `revert_session` returns 409 while a job is in flight

**Severity: high**, and it compounds bug 5.

Rollback is unavailable in exactly the situation that needs rollback. When
it fails, my local document has been restored but the remote has not — and
any retry from that state stacks duplicate content remotely. I traced eight
duplicate paragraphs in one document to precisely this.

**Workaround.** Rollback now reports whether the remote revert actually
succeeded; when it did not, the batch is abandoned rather than retried.
Losing the batch is better than duplicating it.

---

## 7. A denied proposal leaves the job open, wedging the next call

**Severity: high.**

`approve_changes(job_id, False)` — the correct call when a gate rejects a
proposal — left the job open. The next `chat_async` then 409'd, the same
wedge as bug 5 but reached from the deny path.

This makes rejecting a bad proposal as dangerous as accepting one, which
inverts the incentive a review gate is supposed to create.

**Workaround.** An explicit deny-settlement step that polls the denied job
to a terminal state before any further call.

---

## 8. Export returns the remote document, not what the user reviewed

**Severity: medium**, but it is a trust problem rather than a cosmetic one.

**What happened.** The panel showed a clean document. The exported `.docx`
carried template headings with zero content under them — sections the user
had never seen as anything but empty. The human approved one artifact and
received a different one.

**Workaround.** A best-effort reconciliation pass before export that asks
for the empty headings to be removed, written to never fail export.

---

## 9. Drafting into an uploaded `.docx` template produces placeholders

**Severity: medium.** Honestly, this may be as much a prompt-design problem
on my side as a platform bug — reporting it because the failure shape is
consistent.

Uploading a firm's own `.docx` works well: the structure, headings and
styling come back correctly and the document adopts them. But drafting into
an unfamiliar structure reliably produces `Please fill:` placeholders for
fields the conversation did not mention, which my gate then refuses. The
result is an empty document rather than a partially filled one.

What would help: a documented way to say "leave anything unsupported
untouched" that holds across an unfamiliar structure.

---

## 10. One session = one live document, and concurrency 409s

**Not a bug — a constraint worth documenting more loudly.**

Concurrent `chat_async` calls against one `session_id` 409. That forces full
serialization of every edit, which is the single largest contributor to my
end-to-end latency in a live meeting. I rejected parallelism as unsafe
rather than working around it.

I see latency is already named as the next thing you are working on. Flagging
it from this angle: for live use it is the serialization that bites, not the
per-call time.

---

## What I did not report

I hit other failures that turned out to be mine, not yours, and I am not
listing them here as platform bugs. Two worth naming, because they cost real
time and might be common: an anchor regex that swallowed a trailing comma so
`$45,000,` never matched, and a substring match that found `product` inside
`products` and rolled back a correct batch. Both were mine.

---

## 11. Same input, materially different output, run to run

**Severity: medium** on its own; high as an obstacle to trusting anything else.

Nine runs of an identical 9-line transcript against an unchanged build, on
2026-08-19, produced outcomes ranging from every section correct to four
sections empty. The variance is not in my pipeline — the transcript, the
batching, the routing and the instructions are deterministic and I verified
each stays identical across runs. What changes is what comes back.

This matters more than any single defect below it: it makes "is this fixed?"
unanswerable from one run, and it is why several of my own bugs took most of
a day to isolate — a fix looks like it worked, then the next run says
otherwise.

**Repro.** Run the same transcript ten times and diff the resulting
documents. I would be glad to send the ten documents if useful.

---

## 12. Placeholders reach the document even after three explicit rejections

**Severity: high.** A specific, reproducible instance of bugs 1 and 2 together.

**What happened.** In one run the gate rejected `Please fill:` content three
separate times, on three different sections:

```
GATE REJECT op=Scope of Work  failures=[... "Please fill:" ...]
GATE REJECT op=Timeline       failures=[... "Please fill:" ...]
GATE REJECT op=Out of Scope   failures=[... "Please fill:" ...]
```

The exported document still contained
`final website delivery set for Please fill: October [Day], 2026`.

Every rejection was correctly issued and correctly refused. The content
arrived anyway, through the auto-apply path in bug 1 — so a denial is not
sufficient to keep refused content out of the document.

**Why I am reporting it separately.** Bug 1 says review mode can be skipped.
This says something sharper: an edit my gate *explicitly denied* still landed.
That is the difference between a missing hook and an ignored answer.

---

## 13. Number words are treated as monetary values

**Severity: low.** Ours, arguably — reporting it because the shape may be common.

Our own anchor extraction treats bare number words as money, so ordinary
speech like "one correction" or "one moment" produced `one` as a required
monetary anchor. Anyone building spoken-input validation against your API
will likely hit the same thing. We left it unfixed rather than narrow a
pattern that correctly catches "forty-five thousand" the night before a
deadline — a deliberate trade, recorded rather than hidden.
