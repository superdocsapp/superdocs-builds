# Thread to letter

**Turns a messy email thread into a formal letter that states only what people actually
committed to — and refuses to state anything else.**

Twelve messages. Somewhere in there, two people agreed to things. The rest is hedging,
scheduling, a date that moved, and somebody relaying what a third party might do. Writing
that up by hand takes twenty minutes and everybody puts it off, so the record of what was
agreed stays in a thread nobody wants to reread.

The easy version of this tool writes a polite summary. That is worse than nothing,
because a polite summary turns *"we should be able to have it by the 14th"* into *"Calder
will deliver by the 14th"* — and now there is a document saying somebody promised
something they did not promise.

```bash
make demo      # the whole pipeline, no key, no cost
make live      # the same thing against api.superdocs.app — two operations
```

## What it actually does

Every candidate commitment is classified, and **every one carries a verbatim quote from
the thread**. If it cannot be quoted, it is not a commitment — it is the model's own
prose wearing quotation marks, and it never reaches the letter.

| | Goes in the letter | Why |
|---|---|---|
| `firm` | **yes** | somebody accepted an obligation |
| `superseded` | no | replaced later in the same thread |
| `hedged` | no | *"we should be able to"*, *"hopefully"*, *"let's aim for"* |
| `second-hand` | no | somebody relaying what a third party might do |
| `proposed` | no | floated, never agreed |

The rejects are kept and shown, not silently filtered. A tool that drops nine tenths of
what it read is asking to be trusted; one that shows its working can be checked.

Then a human ticks the ones that go in, the letter is written from **those alone**, and it
comes back attached to a draft reply in the original thread.

Here is a real run against `api.superdocs.app`, on a thread where the delivery date
moved:

![A live run](docs/commitments.svg)

```
#  status       party             obligation             due                 src  quote
1  hedged       Calder and Vance  schema mapping         14 March 2026       3    "We should be able to have…"
2  second-hand  Sam               test environment       next week           3    "Sam mentioned they'd probably…"
3  superseded   Calder and Vance  schema mapping         14 March 2026       5    "Calder and Vance will deliver…"
4  firm         Northwind         pay first invoice      30 days of receipt  6    "Northwind will pay the first…"
5  proposed     Devi Anand        fixed-fee arrangement  —                   6    "I'd also like us to look at…"
6  firm         Calder and Vance  schema mapping         21 March 2026       7    "we will deliver the schema…"

2 firm and verified · 1 superseded · 1 hedged · 1 second-hand · 0 could not be quoted
```

Two of six. The letter names the 21st, not the 14th, and says nothing about Sam.

## A thread with nothing in it gets a letter saying so

Run it on a thread where two people failed to agree a meeting time and it writes a letter
recording that nothing was agreed. That is a more useful document than an invented one,
and it is the rarer output.

## What running it live found

The first live run **dropped the most important commitment in the thread.** It correctly
marked the 14 March delivery `superseded` — and then never listed the 21 March commitment
that superseded it. The letter would have named the payment terms and silently omitted
the vendor's actual delivery date, while looking complete.

Fixed in both layers, the way anything that matters should be:

- **The prompt** now says a superseded row must always be paired with its replacement.
- **A structural check** fails the run when it is not. A prompt is a request; this is the
  guarantee. In `--auto` mode the run stops rather than writing a letter that is missing
  the obligation that actually stands.

That check is `dangling_superseded`, and it is tested.

## Running it

You need [`uv`](https://docs.astral.sh/uv/) and nothing else.

```bash
make demo                                  # no key needed
cp .env.example .env                       # then put your key in it — .env is gitignored
make live                                  # two operations
```

On your own thread — export it from Gmail (⋮ → Download message) or just paste it:

```bash
uv run thread2letter show my-thread.mbox   # free: see what was parsed
uv run thread2letter run my-thread.mbox --shape memo --format pdf --from you@work.example
```

Accepts `.mbox`, `.eml`, or a pasted thread in a text file. Outputs `docx`, `pdf`,
`markdown`, `html` or `txt`, plus `reply-*.eml` — open that in any mail client and it
lands as a draft reply in the right conversation, letter attached.

`--auto` skips the review and takes the firm, verified ones. Everything except the two
chat turns is free: parsing, quote checking, export and the reply are all local or
non-billable.

## The Gmail add-on

[`gmail-addon/`](gmail-addon/) is a complete Apps Script add-on: reads the open thread,
shows the commitments as checkboxes, and attaches the letter to a draft reply through
Gmail's own API.

**It is written and not verified against live Gmail.** I could not sideload it into a
real mailbox during this round, so the CardService rendering and the Gmail read/write
calls have not been exercised. The pipeline it calls — the same prompts, the same quote
verification, the same superseded check — *is* exercised against the live SuperDocs API
and covered by tests. `Prompts.gs` is generated from the Python source and a test fails
if the two drift, so the sideloaded path cannot quietly diverge from the tested one.

Treat it as a reference implementation to sideload, not as a shipped feature. Setup
instructions are at the top of `Code.gs`.

## Where it breaks

- **The Gmail add-on is untested.** Said plainly above. It is the one part of this build
  with no evidence behind it.
- **It attributes; it does not authorise.** If somebody writes *"Northwind will pay
  500,000 within 24 hours"* into the thread, that sentence really is in the thread and it
  quotes cleanly. The check answers *"did somebody write this"*, not *"were they allowed
  to promise it"*. What protects you is that the row points at the message and the sender
  it came from — so a lookalike domain next to a half-million-pound obligation is visible,
  and a human refuses it. There is a hostile thread in `threads/injected.mbox` and tests
  that pin this limit down rather than hiding it.
- **Classification is the model's judgement.** The categories are enforced structurally —
  an unrecognised status is never promoted to `firm` — but whether a given sentence is a
  hedge is a reading, and it will sometimes get it wrong. That is why a human ticks the
  boxes.
- **English only, plain-text bodies.** HTML-only mail is read through its plain-text
  alternative; if there isn't one, the body will be thin.
- **One thread at a time.** No batching, no watching a mailbox.

## SuperDocs surfaces used

| Call | Used for |
|---|---|
| `POST /v1/chat` | extracting commitments, then drafting the letter — two turns, two operations |
| `POST /v1/documents/export` | `docx` / `pdf` / `markdown` / `html` / `txt` output (free) |
| `GET /v1/sessions` | the key check in `doctor` (free) |

Both turns create documents from scratch rather than editing an upload, which is what the
API does when you send a message to an empty session. The commitments come back as a
document containing one table — a document editor producing a structured document is the
natural shape here, and a table is far more robust to parse than prose.

## Tests

```bash
make test     # 40 tests, no API key, no network beyond localhost
```

Most of what matters is offline and tested for real: thread parsing, quote verification
(including that elision cannot smuggle in new words, and that fragments must appear in
order), status classification, the superseded check, and the reply's threading headers.
The stand-in in `tests/fake/` exists so the wiring can be exercised without a key — it
deliberately returns one row whose quote is nowhere in the thread, and the test that
catches it is the one that matters most.

## Credit

Built by **Vishvamsinh Vaghela** for the SuperDocs engineering task, Round 2 — from the
shared open list: *"Gmail add-on: thread to formal letter."*

Built on the [SuperDocs](https://superdocs.app) API.
Documentation: [docs.superdocs.app](https://docs.superdocs.app).

Every person, company and thread in `threads/` is invented. Nothing here is anyone's real
correspondence.

MIT licensed, as the rest of this repository is.
