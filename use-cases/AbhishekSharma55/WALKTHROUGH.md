# Walkthrough — for Abhishek, before the live conversation

This round ends with Omkar opening these builds with you and changing something
live. This file is the preparation for that: what is here, why it is shaped this
way, where it is weak, and the answers to the questions a sharp founder asks.

Read it once end to end. Then re-read **§6 (the eight questions)** and
**§7 (where it is weakest)** — those are the ones that get asked out loud.

---

## 0. The thirty-second version

Two builds on the SuperDocs REST API, in one folder, on one shared client layer.

**Build 1 — weekly digest.** One document, fifty-two weeks, *edited* every week
and never regenerated. One billable operation per week. Thirteen invariants
re-derived from the document's own bytes after every week catch drift; a failed
week is repaired with a second operation or rolled back so the document is never
left corrupt. A control arm regenerates the same digest from the same inputs so
the cost claim has a number behind it, with the method committed before the
result.

**Build 2 — GDD editor.** A game design document plus linked sub-documents
(mechanics, narrative, art bible), edited by chat, with image support. The
graded scenario — *new section plus one linked sub-document, then revise one
mechanic, and only the correct section changes across both documents* — runs as
one command and **passes 18/18 in 6 operations.**

**And a bug log with twelve entries**, several of them found by refusing to
believe the API's own success messages.

---

## 1. The shape of the folder

```
use-cases/AbhishekSharma55/
├── superdocs_kit/        the shared layer both builds sit on
├── weekly-digest/        build 1
├── gdd-editor/           build 2
├── tests/                61 tests, no key, no network, ~0.05s
├── repro/                minimal reproductions for the bug log
├── bugs.md               12 bugs, with repro steps
├── ASSUMPTIONS.md        decisions logged as they were made
└── WALKTHROUGH.md        this file
```

`superdocs_kit` exists because four things had to be true before either build
could be honest, and they are the four things to say if he asks "why a shared
layer instead of just calling the API":

1. **An operation is never spent without a durable ledger line** (`budget.py`).
2. **A key never reaches a log, a fixture or a commit** (`secrets.py`).
3. **The tests run with no key and no network** (`transport.py`, record/replay).
4. **"Only the intended section changed" is proved from the bytes**, not taken
   from the API's own summary (`docdiff.py`).

---

## 2. Build 1 — the weekly digest

### What it is

`data/weeks.json` holds 52 weeks of synthetic game-production input — what
shipped, which risks are open with severity and trend, what is next — following
a real production arc from pre-production to live ops. The weeks genuinely
differ, because 52 near-identical weeks would prove nothing: drift only shows up
when the content actually moves.

Week 1 is uploaded verbatim. Every week after is **one chat operation** that
does five things: the status line, the archive, and the three standing sections.

### The one line to have ready

> **Facts are transported. Prose is generated.**

Every fact in the digest is passed through verbatim from the week's input. The
model is never asked to recall or paraphrase one, because a paraphrased fact is
a fabricated fact. What *is* delegated is summarising the outgoing week into an
archive row and folding four old rows into one — genuine summarisation, source
material right there in the document, exactly what a word processor cannot do.

If he pushes — *"so the LLM isn't doing much?"* — the answer is: it is doing the
part that is hard to verify and easy to get wrong, and it is being kept away from
the part where a mistake is invisible. That is a deliberate boundary, not a
limitation.

### The archive

Newest first, at most 8 detail rows. When a ninth would appear, the oldest 4
fold into one rolled-up row **inside the same operation** — so navigability
costs zero extra operations. Over 52 weeks: 18 rows instead of 51.

That policy is verified across all 52 weeks **offline**, in a test that feeds
each week's planned rows back in as the next week's input. Every past week
accounted for exactly once, table never unbounded, milliseconds. Discovering a
bug in it on the live API would have cost 52 operations.

### The drift check, and why it is the interesting part

Thirteen invariants, re-derived from the document's own bytes after every week:
structure (headings not renamed, duplicated or reordered), fidelity (bullets and
every table cell verbatim against the input), formatting (borders, header
shading, alternating rows), growth (archive coverage and bounds).

**None of them ask the API whether it did the right thing.** That matters,
because the API said it had. See §6, question 2.

**When a week fails, the repair is a decomposition, not a retry** — this is
the bit to say out loud, because it is the difference between engineering and
hoping. Re-sending the same instruction was the first design. It failed for a
reason worth knowing: when a week broke, the cause was almost always that one
turn was carrying too much, and the model cross-wired the pieces — twice it put
the risk table's rows into the *What changed* bullet list, once it invented a
table with headers from nowhere. Repeating an instruction that confused the model
mostly reproduces the confusion.

The repair now splits the week into two simpler turns, each naming what it must
not touch. If that also fails the week rolls back rather than being left corrupt.
Every repair operation is counted in the cost measurement.

---

## 3. Build 2 — the GDD editor

Four seed documents; a fifth created at runtime by the scenario. The link graph
is **data** (`corpus.LINKS`) — adding an audio bible is a dict entry.

The graded scenario is `gdd scenario --live`. 18/18, 6 operations. The proof
step is the one to demo: before each act every document's bytes are snapshotted;
afterwards the changed sections are re-derived per document, and a document
nobody named must come back **byte-identical, whole**.

The demo-able moment: `gdd ask mechanics "raise the Dash cooldown to 1.5 s"
--only Dash` prints a PASS/FAIL computed from the document. That is the product
in one command, and it is the thing to type if he says "change something."

### The human gate, and the story that comes with it

`gdd review <doc> "<instruction>"` runs the full approval path — propose, pause,
print the diff, decide per change. Have this story ready, because it is the best
one in the repo:

I asked it to change **two** cooldowns — Dash to 1.5 s, **Overheat pulse** to
7 s. It proposed the Dash change correctly, and proposed the second one against
the **Grapple** section instead. Every section in that document has a row
labelled `Cooldown`, so the wrong one looked right. I approved the first, denied
the second, and the document came out with Dash at 1.5 s and Grapple and Overheat
untouched.

That is bug B13, and it is also the argument for the gate existing: under the
default `approve_all` the wrong number lands in the document with a success
message, and the only person who catches it is a reader who happens to know what
Grapple's cooldown should be.

### The architectural decision he will ask about

SuperDocs has a multi-document session. I did not use it, because opening three
documents into one session returns a roster of **one**, every entry carries
`document_id: "doc_primary"`, and four identical GETs return a different
document each time. `repro/B10-multidoc-roster.sh` reproduces it in about
fifteen seconds against a fresh session, with `curl` and no code of mine.

So each document gets its own session and this code holds the link graph.
**Say the cost out loud before he finds it:** the model never sees two documents
at once, so a cross-document request is decomposed into one targeted edit per
document — which is exactly why ACT 2 and ACT 3 are two operations each rather
than one.

---

## 4. The SuperDocs surface actually used

REST throughout. Both builds hit the four-call minimum contract.

| Call | Where | Billable |
|---|---|---|
| `POST /v1/agents/signup` | got the key; the account is Abhishek's | no |
| `POST /v1/documents/upload-base64` | every seed, both builds — verbatim, no model | no |
| `POST /v1/chat` | every edit, `response_mode: full`. Digest: `core`/`balanced`, escalating to `pro`/`deep` only on a repair. GDD editor: `pro`/`deep`, because it authors prose | **yes** |
| `POST /v1/documents/images/upload-base64` | concept plates → stable URLs | no |
| `POST /v1/documents/export` | Markdown + `.docx`, constantly | no |
| `POST /v1/chat/async` + `GET /v1/jobs/{id}` + `POST /v1/chat/{id}/approve` | in `client.py`: the human-gated path, and the automatic fallback when a sync turn hits a gateway timeout | yes |
| `GET /v1/documents`, `POST /v1/sessions/init`, `GET /v1/sessions/{id}/documents` | explored, then abandoned — bug B10 | no |

**MCP was not used.** Say so plainly: the brief allows either, REST let me hold
the record/replay layer and the budget ledger in one place, and every call the
MCP surface exposes is the same operation underneath. If he asks what I would do
differently: the MCP surface is the better fit for the *interactive* half of
build 2, and wiring the workspace up as an MCP server so Claude Code could edit
the GDD directly is the obvious next step.

---

## 5. Python idioms doing real work — with the TypeScript you already know

You are strong in TS and newer to Python. These are the places where the Python
is doing something non-obvious, so you are not surprised by your own code.

**`@dataclass`** — `Change`, `WeekRecord`, `DocState`, `Section`. This is TS's
`interface` + a generated constructor in one. `@dataclass(frozen=True)` is
`readonly`. `field(default_factory=list)` is there because a mutable default
argument in Python is shared across all instances — the classic footgun. TS has
no equivalent because TS has no default-argument-evaluated-once semantics.

**`from __future__ import annotations`** at the top of every file. It makes all
type hints lazy strings, so `dict[str, str] | None` works on older runtimes and
forward references need no quotes. Closest TS analogue: nothing — TS types are
always erased. Here they are erased *on request*.

**`str | None` and `Any`** — TS's `string | null` and `any`. Python does not
check them at runtime; they are documentation the reader and the IDE enforce.
Do not claim the code is "type safe"; say it is type *annotated*.

**Generators and comprehensions** — `[c for c in changes if c.chunk_id]` is
`changes.filter(c => c.chunk_id)`. `{k: v for k, v in d.items()}` is
`Object.fromEntries(Object.entries(d).map(...))`. The `any(...)`/`all(...)`
built-ins are `.some()`/`.every()`.

**`pathlib.Path`** — `Path("a") / "b" / "c.json"` is `path.join`. `.read_text()`
and `.write_text()` are `fs.readFileSync`/`writeFileSync` with encoding handled.

**Atomic writes** — `tmp.write_text(...); tmp.replace(final)` in `runner.py` and
`workspace.py`. `Path.replace` is an atomic rename on POSIX, so a process killed
mid-write leaves either the old file or the new one, never half of either. Same
trick you would use in Node with `fs.rename`.

**`os.fsync(fh.fileno())`** in `budget.py` after every ledger line. Python's
`flush()` only pushes to the OS buffer; `fsync` forces it to disk. It is there
because a `kill -9` must not lose the record of money already spent.

**Protocol-style duck typing** — `Transport` is a base class with one method,
and `HttpTransport` / `RecordingTransport` / `ReplayTransport` all satisfy it
without registering anywhere. That is TS structural typing, except Python does
it at runtime and never checks.

**`html.parser.HTMLParser` with manual offset arithmetic** (`docdiff.py`). The
parser reports positions as `(line, column)`, not string offsets, so the code
precomputes line starts and converts. This is the fiddliest code in the repo and
it exists for one reason: to slice the *original bytes* rather than re-serialise
them, because a serialiser would normalise away the very differences the diff is
trying to detect.

**`str.rstrip(".")` in `verify.py`** — a declared tolerance, not a bug. Read §7.

---

## 6. Eight questions a sharp founder asks, and the answers

**1. "Your digest is one operation a week. What is the regeneration arm actually
costing, and how do I know you did not pick a control that flatters you?"**

The method is committed in `METHOD.md` before any number was collected — check
`git log`. Both arms take the same 52 weeks of input in the same order and are
asked for the same document with the same formatting brief. Arm B is *given* the
archive contents as input rather than asked to remember them, because a
regenerating system has no memory of last week's document; withholding them
would have made arm B produce a shorter document and won the comparison
dishonestly. Arm B also gets a fresh session per week, because reusing one would
let the server carry document state across turns, which is *editing*. And the
falsification criteria are written down in the same file — including "if arm A
needs frequent repairs, its effective cost approaches 2 and the gap narrows."

**2. "What is the single most useful thing you found?"**

`changes_summary` said `"1 section edited, rest untouched"` for a turn that had
destroyed a table — replaced a `<table>` with a `<div>` wrapping a bare `<tr>`,
losing the header row and every prior row. Two things in that sentence were
false. An integrator building an approval UI on `changes_summary` — which is
what it is for — would show a reviewer "rest untouched" over a diff that
silently dropped a table. That is the worst failure mode a human-in-the-loop
product can have, and it is why nothing in this repo trusts a success message.
The fix I would make: compute "rest untouched" from the stored chunk map instead
of taking the model's narration of what it intended, and if it cannot be
computed, do not assert it.

**3. "Show me it not working."**

`out/arm-a-edit/failed-attempts/` has the instruction and the output of every
week that failed verification, kept on purpose. `repro/B2-after-week-03-CORRUPTED.html`
is the destroyed table. `repro/B10-multidoc-roster.sh` reproduces the roster bug
live in fifteen seconds. And one of the tests loads the real corrupted document
and asserts that the surgical check rejects it. I would rather hand over the
failures than a demo that only goes one way.

**4. "Are you just throwing a bigger model at it?"**

I was, then I stopped, then I had to partly go back — and the third part is the
one worth telling.

On the default tier the five-step weekly instruction was applied *partially*:
the archive done, the four steps after it silently dropped, four weeks running
(bug B9). The reason was that the instruction *described* its target ("replace
all bullets with exactly these four"), and description is ambiguous — measured,
it was read as *append* often enough to matter.

So I handed the factual sections over as **literal HTML**, re-tested the default
tier on the exact week that had failed four times, watched it pass 4.5× faster,
and moved attempt 1 to the cheap tier.

**Over a longer run it failed first-attempt verification about 60% of the time.**
One passing week was not evidence. Attempt 1 is back on `pro`/`deep`, and the
comment in `runner.py` says so, including the part where I was wrong.

The lesson that survives: on the first failure, removing the ambiguity beat
buying a bigger model — the literal-HTML change is what made the *content*
correct, and it stayed. It just did not remove the need for the stronger model
entirely. Both tiers bill one operation, so none of this was ever about money.

**5. "You are re-sending the whole document on every turn. Isn't that fighting
the product?"**

Yes, and I would tell you before you found it. It started as a workaround — a
re-upload into a live session came back with the document duplicated, then
tripled — and it stayed because it made three other things fall out for free:
crash-resume, rollback, and reproducibility, because week N is computed from week
N-1's bytes on disk and nothing else. It costs zero operations; the ledger shows
one per week. What it costs *you* is that I stopped exercising your cross-turn
persistence, which is a real feature. For a document too large for a request body
I would invert it: keep server state and reconcile.

**6. "Your fidelity check ignores a trailing full stop. What else does it
ignore?"**

Nothing else. That one tolerance is declared in `verify.py` with the reasoning:
SuperDocs adds a full stop to a bullet roughly one time in twenty and nothing
else about the bullet differs, and failing the week would mean spending a repair
operation to move a period. Wording, ordering, count and every other character
are compared exactly. I put it in a separate named function with a docstring
rather than folding it into the general normaliser, because a tolerance a reader
cannot see is indistinguishable from a bug.

**7. "The tests do not hit the API. What are they actually proving?"**

Behaviours, from real artefacts. The double-parse of a JSON-encoded change list,
including the double-encoded case. That a cell edit does not report its row and
its table as changed, *and* that a table whose own attribute changed still is —
the over-suppression sibling. That a heading wrapped in a `<div>` is still a
section, using the exact shape the API returned. That the budget cap raises
*before* spending and the ledger survives a restart. That a recorded fixture
never contains a key. And 52 weeks of archive growth simulated offline. The
record/replay transport means anyone can run the suite on a fresh clone with no
key in about 0.05 s — `make setup && make test`.

**8. "What would you build next on SuperDocs, if you joined?"**

Three, in order. First, **structural validation on chunk replacement** — a
`<table>` chunk may only be replaced by a `<table>`, a list by a list. That one
check closes bug B2, bug B12, and the `<li>`-replacing-a-`<ul>` version nobody
has hit yet; it is the whole class, not the case. Second, **make the change
summary computed rather than narrated**, which closes B3 and makes every
approval UI on the platform trustworthy. Third, **`include_chunk_ids` on HTML
export** (B5) — right now exports are free and chat turns are billable, so the
natural way to snapshot a document you are editing over a year is to export it,
and an export has lost its section identity. That is a five-line change that
unlocks a whole workflow.

---

## 7. Where it is weakest — say these before he finds them

**The archive summaries are not fact-checked.** The model writes a 20-word
summary of the outgoing week; I verify the structure and the coverage, not
whether the summary is a fair précis. A wrong summary would pass all thirteen
invariants. Honest answer: checking it needs a second model call and a rubric,
and I would rather ship a verified structure with an unverified sentence than
claim both.

**Arm B is a bounded sample.** The agent account has 500 operations a month, arm
A had to run in full, so the control arm runs a prefix of weeks and the 52-week
figure is an extrapolation — labelled as one everywhere. If he only trusts
measured values, point him at the like-for-like line, which compares only the
weeks both arms actually ran.

**There is no cross-document consistency engine in build 2.** Change the cooldown
in Mechanics and never mention the GDD, and the GDD keeps the old number. The
scenario changes both because the instruction changes both. Detecting divergence
automatically is the obvious next build. Do not oversell it as already solved.

**The concept art is placeholders**, generated in pure Python. The image *path*
is real — upload, stable URL, embedded `<img>`, exported into the `.docx`. The
art is a gradient with a silhouette.

**The multi-document session is worked around, not solved.** If B10 is fixed, the
right architecture is different from the one here, and I would change it.

**Latency is not a headline.** One machine, one connection, a few hours. The
per-call seconds are in the raw data; no argument is built on them.

---

## 8. If he says "change something, live"

Ordered by how likely they are to work first time.

1. **`gdd ask narrative "give Vex a reason to lie in Act I" --only "Act I"`** —
   one operation, ~30 s, and it prints a PASS/FAIL from the bytes. Best single
   demo of the whole idea.
2. **`digest diff --week 30`** — free, instant, shows week-over-week change with
   only the intended sections moving.
3. **Add a sub-document**: add an entry to `corpus.LINKS` and a `DOCUMENTS` key.
   Configuration over code — a new sub-document is a dict entry.
4. **Change the archive policy**: `ARCHIVE_MAX_DETAIL_ROWS` and
   `ARCHIVE_ROLLUP_SIZE` in `document.py`, then run the offline archive test and
   watch it re-verify all 52 weeks in milliseconds.
5. **Break it on purpose**: hand-edit a saved week's HTML to rename a heading,
   then `digest verify`. The invariant fires and names the section.

Have `make test` ready as the zero-risk opener — 61 tests, ~0.05 s, no key.
Then `make demo`, which re-verifies every saved week and prints a week-over-week
diff without spending anything.

---

## 9. Numbers to have in your head

| | |
|---|---|
| Graded scenario (build 2) | **18/18 checks, 6 operations, 368 s** |
| Digest, per week | **1 operation** (2 when a week needs repair) |
| Archive at week 52 | **18 rows instead of 51** |
| Invariants per week | **13**, re-derived from the bytes |
| Tests | **61**, no key, no network, **~0.05 s** |
| Bugs found and logged | **12**, with repro steps; one with a runnable script |
| Free-tier budget | **500 operations a month** — which is why everything that loops has a cap and a stopping rule |

`bugs.md` also ends with a section headed **"My own bugs"** — four of them: a
live key committed as a test fixture (caught by my own pre-PR check, history
rewritten), a CLI default that spent money on what looked like a dry run, a test
that hung building its own input, and the time I treated one passing week as
evidence and had to revert. If he notices them, that is the answer: the same
hours that found twelve bugs in someone else's product should be honest about
the ones they created. A bug log containing only other people's bugs is a
marketing document.
