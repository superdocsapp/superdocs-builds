# Meeting brief pack — calendar and mail in, one short brief out

Built for the SuperDocs Round 2 engineer task, assigned build: *Calendar and mail
to a meeting brief pack*, for executive support.

An executive has six minutes before a call. This assembles what they need from
the invitation, the email threads and the past documents — and, more importantly,
leaves out everything else.

---

## What it produced

Real output, from the fixtures in this folder, in **one billable operation**:

> ## What needs a decision today
>
> This is the most urgent item. The current agreement expires on 30 September
> 2026, and the notice period for non-renewal is 60 days before expiry. **That
> means the notice window has already passed**, so the renewal discussion needs
> to be handled promptly. Trellis has proposed a new renewal schedule with a
> platform fee of £148,000 per year (up from £120,000)…

Nobody wrote that sentence in any source document. It comes from joining the
contract's notice period against the date of this meeting — which is the
difference between a brief and a folder of attachments.

---

## The idea

The card says what strong looks like: *short and specific to that meeting rather
than a generic dossier*. That one sentence is the whole difficulty. Gathering
every document about a supplier is easy and useless.

So most of the work is **deciding what to leave out**, and it happens locally,
before any operation is spent:

```
invitation (.ics)  ──▶  what is this meeting?      agenda · attendees · date
                              │
candidate sources  ──▶  score each against it       ──▶  kept 4 / dropped 1
   .eml .md .docx            │                            with reasons
                              ▼
                    render calendar & mail to Markdown
                              │
                              ▼
                    upload as read-only attachments
                              │
                              ▼
                    one chat turn, approval gate armed
                              │
                              ▼
                    a human decides, section by section
                              │
                              ▼
                    verify against the export, then ship
```

Selection running locally is not a shortcut. It is cheaper, it is explainable —
every keep and drop prints its reason — and it means the model is asked to write
about four relevant documents rather than asked to ignore two irrelevant ones.
Asking a model to ignore things is a request it can decline.

```
KEPT     27.6  past-q2-minutes.md
                mentions 7 of 12 agenda terms: actions, diagnostics, milestone…
                involves amara osei, daniel kerr, priyanka raman
DROPPED   3.5  thread-unrelated.eml
                from or to harrowgate.example
                scored 3.5 against the 6.0 needed, so it was not sent to the model
```

That dropped file is a facilities notice about car park resurfacing. It shares a
company domain and a recent date with everything else in the folder, and nothing
else. It never leaves the machine.

---

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install httpx
echo 'SUPERDOCS_API_KEY=sk_...' > .env      # never committed
.venv/bin/python meetingbrief/scripts/run.py
```

Stops at the gate by default, with the proposed sections listed and nothing
applied. Add `--approve-all` to approve every section and export — a
demonstration convenience; a person should be deciding.

```bash
.venv/bin/python -m pytest meetingbrief/tests -q     # 11 tests, no key, no network
```

The tests cover the judgement that happens before anything is spent: reading the
invitation, scoring relevance, and converting calendar and mail. The API calls
are not mocked — a test proving a mock returns what the mock was told to return
proves nothing.

---

## Things worth knowing, including where it breaks

**Calendar and mail cannot be uploaded.** SuperDocs accepts `.docx`, `.htm`,
`.html`, `.md`, `.pdf`, `.rtf`, `.tex`, `.txt` — not `.ics` or `.eml`, which are
the two native formats of this use case. `render.py` converts them first. This
turned out better than uploading raw anyway: a `.eml` is MIME boundaries, forty
`Received:` headers and a base64 signature image, and none of that should reach a
model. The rendered copy names the file it came from, so a claim in the brief can
still be walked back to a real message on disk.

**The `core` model tier does not do this job.** Measured, three tiers, same
inputs back to back:

| tier | status | changes | time |
|---|---|---|---|
| core | `completed` | **0** | 36.5s |
| turbo | `awaiting_approval` | 1 | 57.8s |
| pro | `awaiting_approval` | 4 | 50.8s |

`core` finishes having proposed nothing about a third of the time, with no error
and the operation still billed. A tier costs the same one operation, so the
cheaper tier buys nothing here except a brief that sometimes is not written. The
build defaults to `pro` and retries once, then reports what happened.

**`awaiting_approval` does not mean the change list is complete.** The job flips
to that status as soon as the first change is ready and keeps adding — its own
event stream emits "Processing 4 sections in parallel" *afterwards*. Reading
`pending_changes` at first sight of the status gets a partial list, silently. The
client waits for the count to stop growing instead.

**The brief still gets things wrong.** In the run quoted above, "Who is in the
room" named Daniel Kerr as chair when the invitation names Amara Osei, and
omitted Stefan Lindqvist entirely. That section is exactly what the approval gate
is for, and rejecting it is a two-second decision — but it is a real error in a
real run, and pretending otherwise would be the kind of claim this build is
supposed to be incapable of.

**A brief is only called finished if it is.** After approval the document is
exported and checked for unfilled sections; anything still carrying placeholder
text is named. The first version of that check read the document out of job
events, which carry the *pre-edit* state, so it reported every section as
unfilled on a brief that was complete. A check that wrongly refuses valid work is
worse than no check, because it teaches the reader to ignore it. It now verifies
against the exported artifact, which is free and is the thing that actually
reaches the executive.

---

## What it costs

One billable operation per brief, regardless of how many source documents were
considered — selection is local, uploads are free, approvals are free, exports
are free. `Budget` refuses the call that would cross the ceiling rather than
reporting it afterwards, and prints the ledger at the end of every run.

```
chat_async: You are preparing a pre-meeting brief fo   1  → 1
total billable operations                              1

4 of 5 candidate sources were sent to the model.
```

---

## What it uses from SuperDocs

| Feature | Where |
|---|---|
| **Attachments** (`/v1/attachments/upload`) | the invitation, threads and past documents go up as read-only reference material, so the run that reads them cannot edit them |
| **Async chat editing** (`/v1/chat/async`) | one turn drafts every section against a fixed skeleton |
| **Human-in-the-loop approval** (`/v1/chat/{session}/approve`) | `approval_mode="ask_every_time"`; each section is decided individually and nothing lands unreviewed |
| **Jobs** (`/v1/jobs/{id}`) | polling, with a long ceiling because a real edit can take minutes |
| **Export** (`/v1/documents/export`) | `.docx` for the pack, and a free `.md` export used to verify the result before calling it finished |
| **Account** (`/v1/agents/whoami`, `/v1/promotions`) | budget checks before spending |

Model tier `pro`, for the measured reason in the table above.

---

## Layout

```
meetingbrief/
  superdocs/client.py   the four calls — upload, chat, approve, export — plus
                        budget, polling and the pending-change parser
  brief.py              read the invitation, score relevance, draft, verify
  render.py             .ics and .eml into something the platform accepts
  scripts/run.py        build a brief, showing its working
  scripts/smoke.py      proves the four calls against the live API
  tests/                11 tests, offline
fixtures/               a fictional meeting: Harrowgate Health × Trellis
                        Diagnostics. Invented company, invented people,
                        invented numbers.
```

Everything in `fixtures/` is fabricated. No real client, no real correspondence.

---

Built by Dinesh De Silva for the SuperDocs Round 2 engineer task.
