# thread-resolver

Walks the open comment threads in a Word document, drafts the edit each one
implies, and closes only the threads whose edit a person approved.

Built on SuperDocs. Threads with disagreement are surfaced for a human rather
than resolved arbitrarily, and a comment that tries to give the system orders is
reported rather than obeyed.

---

## The problem

A draft comes back from editorial with eighty comments on it. Someone has to
open each one, work out what change it asks for, make that change, and tick the
thread resolved. On a long document that is a full day of work, and the tedium
is exactly where mistakes happen.

Automating it naively is worse than doing nothing. Consider a real thread:

> **Ada:** Cut this clause, we bill quarterly now.
> **Grace:** No, leave it. Finance signed off on monthly.

Hand that to any AI editor and it will cut the clause. It has to: it was asked
to edit. The reviewer then sees a tidy before-and-after diff, approves it, and
Grace's objection is gone without anyone noticing there was one.

This tool refuses that thread. Deciding *which threads may be edited at all* is
the product; the editing itself is one API call.

## What it does

```
your.docx  ─►  read every comment thread   (replies, resolved state, anchored passage)
               │
               ▼
               judge what each thread is
               │
               ├── one clear request  ──► ask SuperDocs to draft the edit
               ├── people disagree    ──► surface it, draft nothing
               ├── just a question    ──► surface it, draft nothing
               ├── passage is gone    ──► surface it, invent nothing
               └── aimed at the system──► quarantine it, obey nothing
               │
               ▼
               a person approves or rejects each item
               │
               ▼
               write approved changes into your.docx
               close only the approved threads
```

![The review screen. The contested thread names both positions and offers no
approve option; the actionable thread below it carries a drafted
edit.](docs/review.png)

Six judgements are possible. Only one of them can produce an edit.

| Disposition | Meaning | Edit drafted |
|---|---|---|
| `actionable` | one participant, one clear request | yes |
| `contested` | participants want incompatible outcomes | no |
| `unclear` | could not establish whether they converged | no |
| `question` | asks something; implies no change | no |
| `unanchored` | the commented passage is no longer present | no |
| `quarantined` | the text addresses the system, not the document | no |

`unclear` is deliberately distinct from `contested`. Claiming disagreement the
tool has not established would be a guess dressed as a finding.

## Install and run

Requires [uv](https://docs.astral.sh/uv/). No other setup.

```bash
cd thread-resolver            # this folder, from a clone of the repository
uv sync

cp .env.example .env          # then add your key
```

```
SUPERDOCS_API_KEY=your-key-here
```

Create one at [use.superdocs.app](https://use.superdocs.app) under
Settings → API Keys.

**Try it without a key or a document of your own:**

```bash
uv run thread-resolver sample demo.docx        # a document with every kind of thread
uv run thread-resolver run demo.docx --offline # full loop, built-in editor, no API calls
```

**On your own document:**

```bash
uv run thread-resolver run contract.docx
```

You get one screen per thread showing the passage, who said what, the judgement,
and the proposed change. Approve `[a]`, reject `[r]`, defer `[d]`, quit `[q]`.
Threads with no drafted edit offer no approve option.

The result is written to `contract.resolved.docx`; `--output` chooses elsewhere.

### Options

| Flag | Effect |
|---|---|
| `--dry-run` | Judge and report. No API calls, nothing written. |
| `--offline` | Full loop against a built-in editor. No API calls. |
| `--max-threads N` | Stop after N open threads. Caps spend. |
| `--yes` | Approve every drafted edit without prompting. |
| `--concurrency N` | Edits requested at once. Default 4. |
| `--no-judge` | Skip language judgement even if one is configured. |
| `--run-id ID` | Resume an interrupted run. |
| `--output PATH` | Where to write the result. |

```bash
uv run thread-resolver runs     # list runs and where each stopped
uv run pytest                   # the test suite, no key needed
```

## What it uses from SuperDocs

| Call | Used for |
|---|---|
| `POST /v1/documents/upload-base64` | opening the document for editing |
| `POST /v1/chat/async` | drafting the edit a thread implies, with `approval_mode: "ask_every_time"` |
| `POST /v1/chat/{session_id}/approve` | applying approved changes, rejecting the rest, per item |
| `GET /v1/jobs/{job_id}` | polling an edit that can take minutes |
| `GET /v1/agents/whoami` | remaining operations |

SuperDocs writes every word of replacement text. This tool never generates
document prose; it decides which threads deserve an edit, says which passage to
change, and drives the review.

## Why it writes into your original file

An unedited round trip through upload and export does not preserve comment
threads. Measured with `scripts/roundtrip_check.py`:

| | before | after |
|---|---|---|
| comments | 6 | **5** |
| replies | 1 | **0** |
| resolved threads | 1 | **0** |
| `word/commentsExtended.xml` | present | **removed** |

Top-level comments survive as real Word comments. A **reply was silently
deleted**, thread parentage is gone, and resolved state with it. The comment
lost was a dissenting reply, which for this tool is the most costly kind.

So the exported file is never used as the output. SuperDocs decides the change;
the approved text is written into the original package, one paragraph at a time.
Everything else is untouched because nothing writes to it:

```
parts differing after a run: word/document.xml, word/commentsExtended.xml
parts before: 6      parts after: 6
```

Details in [docs/roundtrip.md](docs/roundtrip.md).

## What it refuses to do

**It does not take orders from comments.** Comment text is written by other
people and arrives untrusted. Text that addresses the system rather than the
document is quarantined and reported. Detection is deterministic rather than
delegated to a model, because a component that can be reasoned with can be
reasoned out of its own defence. False positives are the direction worth failing
in: a wrongly flagged comment costs one glance, a missed one puts hostile text
into an editing request.

Quarantined text is never sent to the editing service and never shown to the
judge. For threads that do proceed, the note is quoted inside the request rather
than merged into it.

**It does not invent an edit it cannot ground.** A comment whose passage has
been deleted produces a finding, not a guess.

**It does not close what nobody approved.** Rejecting one item leaves the rest
intact. Approving a finding that carries no edit closes nothing.

## Formats

**`.docx` only, in and out.** Not a limitation of effort. A comment *thread*,
meaning reply parentage plus resolved state, exists as machine-readable data in
a Word file and in the Google Docs API, and nowhere else that matters here. PDF
annotations cannot be written back surgically; HTML and Markdown have no comment
concept. Pointing this at anything else stops immediately with a message saying
so, rather than finding nothing and reporting success.

`ThreadSource` is an interface for exactly this reason. A second source is
mostly a new file, but not entirely: the pipeline still names and constructs the
`.docx` source directly in order to close threads, so that one call would move
out to the CLI before a Google Docs source could drop in.

## Judging disagreement

Deciding whether several participants converged is the one judgement that needs
language understanding. It is optional:

- **with no model configured**, threads with more than one participant are
  reported `unclear` and go to a person. Every safety behaviour is intact; you
  are simply asked more often.
- **with a judge configured**, obvious agreement is drafted, disagreement is
  reported as `contested`, and uncertainty still goes to a person.

The fallback and the safe answer are the same, so an unreachable model degrades
into asking rather than into guessing. The judge receives a transcript only,
never the document, and can return a label and nothing else.

Gemini is the provider with an adapter. A key from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) is free and
needs no card:

```bash
JUDGE_PROVIDER=gemini
JUDGE_API_KEY=...
JUDGE_MODEL=gemini-3.5-flash-lite   # optional
```

Only threads with more than one participant reach it, so a document of ten
threads usually costs one or two calls. `--no-judge` skips it for a run.

## Design

```
domain/     pure. no network, no files, no XML.
  models      Thread, Comment, Anchor, Classification, ReviewItem
  classify    what each thread is, and what may follow from that
  rules       patterns identifying text aimed at the system
  run         run state and the stages it moves through

ports/      interfaces. the seams.
  thread_source   where threads come from
  editor          who performs edits
  judge           who reads language
  review          who decides
  store           where state survives

adapters/   the outside world.
  docx_source     reads and closes threads in a .docx
  docx_writer     writes approved changes into the original package
  superdocs       the REST API
  fake_editor     a working stand-in, used by the tests
  cli_review      the review screen
  scripted_review decisions supplied rather than typed
  sqlite_store    checkpointing

app/
  pipeline    the stage machine
```

The domain layer imports nothing from adapters. Tests of the rules that matter
run in milliseconds with no key, no network, and no files.

## Resuming

Stages are checkpointed as they complete. Kill a run mid-way and continue it:

```bash
uv run thread-resolver runs
uv run thread-resolver run contract.docx --run-id run-3dd8763d
```

Drafting skips threads that already carry a proposal, so a resumed run does not
spend a second operation on a thread it already paid for. There is a test for
exactly that.

## Limitations

- Replacement text is written back as plain text with the first run's
  formatting preserved. Rich inline formatting that varied *within a changed
  paragraph* is not fully round-tripped. Unchanged paragraphs are untouched at
  the byte level.
- A passage that appears identically more than once in a document cannot be
  placed unambiguously; the run stops rather than editing the wrong one.
- Closing threads needs `word/commentsExtended.xml`. Documents written by tools
  that omit it read fine but cannot record resolution, and say so.
- The question heuristic is English-only.
- Concurrency is bounded per run, not across runs.

## Tests

```bash
uv run pytest
```

182 tests, no API key required. They cover the claims above rather than the
plumbing: hostile comments quarantined and legitimate ones not, a killed run
resuming without paying twice, an outage degrading into a finding instead of a
crash, rejection changing nothing, and exactly two of six package parts
differing after a run.

---

Built by [degenSumi](https://github.com/degenSumi) for the SuperDocs task.
MIT licensed.
