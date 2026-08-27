# Plumbline

**Documentation that stays true to the code.**

A plumb line tells you whether a wall is true. This tells you whether a document
still is.

You change a default from `30` to `45`. Six months later the reference page still
says 30, and nobody notices until a customer builds against it. Plumbline reads
what the code actually says, extracts what the document *claims*, and reports
every place the two disagree — with the sentence that claims it and the file and
line that settles it. Then it drafts the correction through SuperDocs, holds it
at a human gate, and writes it back only once someone approves.

Built for coding agents: it ships as an **MCP server**, so Cursor or Claude Code
can ask "which docs did my change just make false?" without leaving the editor.

---

## The one idea

**The model reads English. The AST decides the truth.**

A language model is good at reading prose and pulling typed claims out of it. It
is a poor authority on a function signature, which can simply be looked up.
Python's `ast` is the reverse. So the work is split along that line and never
crosses it:

| Job | Done by | Why |
|---|---|---|
| What does the code say? | `ast` (`codefacts.py`) | A signature is not a matter of opinion |
| What does the document claim? | SuperDocs | Reading English is a language job |
| Do they agree? | Plain Python (`claims.py`) | Must be arguable, so it must be deterministic |
| Write the correction | SuperDocs | Editing prose in place is the product's whole job |
| Decide whether it ships | A person | The gate |

Because the verification half is deterministic, it is fully tested with no API
key and no network:

```
$ python test_plumbline.py
  ok    test_a_claim_about_a_constant_is_checked_as_one
  ok    test_collateral_guard_works_at_sentence_granularity
  ok    test_false_claims_drift
  ...
all 11 checks pass — no API key, no network
```

---

## What a run looks like

The shipped `sample-repo/` is a fabricated SDK whose reference page has drifted
from it in five places. Nothing here talks to a real service.

```
$ plumbline scan                      # what the code says — zero API calls
  client.py:9    DEFAULT_TIMEOUT = 45
  client.py:30   def Client.__init__(self, api_key: str, region: str = DEFAULT_REGION,
                     timeout: int = DEFAULT_TIMEOUT, max_retries: int = 3) -> None
  client.py:43   def Client.list_ledgers(self, page_size: int = 100, ...) -> list[dict]
                 raises ValueError
  ...
Read from the AST. No model was involved and no API call was made.
```

```
$ plumbline check
22 checkable claim(s) extracted from the document
  16 verified against the code
  6 drifted

  [breaking    ] Client.close_ledger.effective_date
      document :
      code     : ledger_id, reason   (client.py:80)
      quote    : "A reason is required, and an effective_date may be supplied to backdate the closure."

  [stale       ] Client.__init__.max_retries
      document : 5
      code     : 3   (client.py:30)
      quote    : "The constructor also accepts region, timeout and max_retries, which defaults to 5."
  ...
```

`fix` drafts the corrections and parks them; `decide approve` verifies and stages
them; `apply` writes them into the repository with the previous version kept
beside it so `git diff` shows exactly what moved. The corrected page from a real
run is in [`samples/`](samples/), along with the claims table SuperDocs produced.

---

## Two guards, both earned the hard way

**Nothing ships that does not carry the code's values.** On the first live run
the model corrected one paragraph and stopped. The approval was refused:

```
The approved edit does not contain the values it was supposed to correct to:
  - 3
  - 100
  - 'EUR'
Nothing was written. Run `fix` again.
```

A half-applied fix written silently to the repo is worse than no fix: the
document goes on lying about three things while everyone believes it was
corrected. `fix` now checks the draft for completeness *before* the gate and
sends it back automatically, so a reviewer only ever sees a whole one.

**Nothing else may move.** Verifying that the corrections landed says nothing
about what else changed. On a later run the tool corrected all five drifts and
also quietly deleted the word "region" from a sentence, and added a parameter to
another. Both passed every check, because every check was looking at what was
*supposed* to change. `collateral_edits()` now compares the document sentence by
sentence and refuses any edit to a sentence the fix did not name.

That guard was written twice. The first version compared paragraphs and found
nothing — the deletion had happened inside the same paragraph as a legitimate
correction, so the whole paragraph counted as fair game. Precision has to match
the size of the thing being protected.

---

## The false positive that did real damage

Worth its own section, because it is the most instructive thing that happened.

The extractor reported the region default as `"eu-west-1 region"` — it took the
next noun along with the value. The code says `'eu-west-1'`. My comparison was
strict, so it reported drift. `fix` then obediently edited a perfectly correct
sentence to make it match, **deleting the word "region"**.

A false positive in a tool like this is not a harmless bit of noise. It causes a
real edit to correct prose. The comparison now tolerates a claimed value that is
the real value plus ordinary words, exactly as it already tolerated `30 seconds`
against `30`. Both directions are pinned in `test_prose_that_names_a_thing_is_not_drift`.

---

## Running it

```bash
cp .env.example .env          # then put your SuperDocs key in it
python test_plumbline.py      # deterministic checks, no key needed
python plumbline.py scan      # what the code says, zero API calls
python plumbline.py check     # the drift report
python plumbline.py fix       # draft corrections, held at the gate
python plumbline.py decide approve --by you@example.com
python plumbline.py apply     # write it back
```

No local Python? `./run.sh scan` / `run.cmd scan` do the same inside
`python:3.12-slim`. Standard library only — nothing to install but Docker.

`check` returns exit 1 while the document is untrue, so it drops straight into CI
as a build step.

### As an MCP server

```bash
claude mcp add plumbline -- python /absolute/path/plumbline.py serve
```

Six tools: `plumbline_scan`, `plumbline_check`, `plumbline_fix`,
`plumbline_decide`, `plumbline_apply`, `plumbline_status`. The MCP layer speaks
JSON-RPC over stdio directly — no `mcp` package, no install.

**The gate is a tool, not a flag.** `plumbline_apply` refuses to write anything
that has not been through `plumbline_decide`, so an agent cannot quietly rewrite
a repository's documentation on its own initiative.

---

## SuperDocs surfaces used

| Surface | Where |
|---|---|
| **Chat** | Generating the claims table; correcting the document in place |
| **Async chat + HITL** | Every correction is drafted with `ask_every_time` and parks at `awaiting_approval` |
| **Approve / deny with feedback** | The gate, and the automatic completeness round-trip |
| **Export** | Reading the claims table back as Markdown; exporting the corrected page |
| **Sessions** | One per document, so a document's correction history is revisitable |
| **Model tiers** | `pro` throughout — the prose is customer-facing reference material |

### A note on how the extraction works

The first attempt asked the chat surface to reply with JSON. It declined:

> *I found what I needed, but I wasn't able to put together a safe reply to share here.*

Fair enough — SuperDocs is a document editor, not a general-purpose
structured-output API, and building *on* a product means using the shape it
actually has. So the extraction is itself a document: Plumbline asks SuperDocs to
write a claims **table**, exports it as Markdown, and parses it. One operation,
and the intermediate artefact is a real document a person can open and argue
with, which turned out to be a better audit trail than a hidden JSON blob.

---

## Where it falls short

- **Extraction recall varies between runs.** One run pulled 22 claims from the
  sample page, another 19. The *verification* is deterministic; which claims get
  extracted is not. A claim not extracted is a drift not caught. This argues for
  running `check` on every build rather than once — what is missed one day is
  caught the next — but it is a real ceiling on the guarantee, and it is why the
  tool reports "drift found", never "this document is correct".
- **Five claim kinds, Python only.** Parameters, defaults, return types, raised
  exceptions, module constants. Not: behaviour, ordering, thread-safety, units,
  or anything about what a function *means*. A claim type with no verifier is an
  opinion and is discarded rather than half-checked.
- **`raises` is shallow.** It reports what a function raises directly, not what
  anything it calls might raise. Claiming more would be guessing.
- **HTML documents.** SuperDocs takes DOCX, PDF, Markdown and more; Plumbline
  only round-trips HTML today, because that is what round-trips cleanly.
- **No git integration yet.** The obvious next step is a hook that runs `check`
  only for documents whose mapped symbols appear in the diff.

---

## Layout

```
plumbline/
├── plumbline.py       the CLI and the fix/gate/apply pipeline
├── codefacts.py       the AST reader — the authority on what the code says
├── claims.py          claim types, comparison, and drift detection
├── extract.py         the claims-table prompt and its Markdown parser
├── mcp_server.py      JSON-RPC over stdio, stdlib only
├── superdocs_client.py
├── test_plumbline.py  11 checks, no key, no network
├── sample-repo/       a fabricated SDK and its drifted reference page
└── samples/           real output from a live run
```

Built for the SuperDocs Round 2 engineering task, Task 2.2 — an own invention.
