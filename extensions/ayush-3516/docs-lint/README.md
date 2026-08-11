# docs-lint

A house-style gate for Markdown documents in a repository. Runs as a pre-commit hook and in CI,
checks changed documents against your team's style guide, and proposes corrections as a reviewable
change set that a human approves item by item.

It never rewrites your prose behind your back. `check` cannot write to a file at all, and `fix`
cannot write without a recorded human decision — that is enforced by the types, not promised in a
paragraph.

Built on [SuperDocs](https://use.superdocs.app). Built for the SuperDocs task.

```
$ docs-lint check -v

 selected — 1 document(s)
 miss docs/getting-started.md — checking
 checked docs/getting-started.md — 7 local finding(s)
 instructed docs/getting-started.md — job bf81ebb9
 escalate docs/getting-started.md — 1 proposal(s) awaiting human review

docs/getting-started.md
     1  warning heading-case (rule)  Heading looks like Title Case; sentence case
                                     reads 'Getting started with the widget.'.
        - Getting Started With The Widget.
        + Getting started with the widget.
     3  error   banned-terms (rule)  Avoid 'utilise'; the style guide prefers 'use'.
        - utilise
        + use
     3  warning style-guide (ai)     Rewrite to match the style guide.

7 findings in 1 files (2 at gating severity)
6 of these can be fixed. Run `docs-lint fix` to review them one by one.
```

See [`examples/sample-repo/`](examples/sample-repo/) for three committed transcripts of real runs:
failing, partially approved, then passing.

## Why it is built this way

A style guide nobody follows is the normal state of affairs, and the reason is not laziness. Most
prose linters make you express your house style as configuration — a regular expression per rule —
so the guide your team actually wrote sits in a wiki, drifting away from what the tool enforces.

Here the guide is **a Markdown file you write in prose**, uploaded to SuperDocs once and consulted
by the model on every run. Adding a rule means adding a sentence to the guide. No code changes, no
regex.

But not every rule wants a model. "Never write *utilise*" has one right answer that never varies,
costs nothing to check, and should not be non-deterministic or billable. So docs-lint runs two
passes:

- **Deterministic rules**, locally, free and instant, for the mechanical things
- **The style-guide review**, through SuperDocs, for anything requiring judgement

Both feed one findings list with one severity scheme, and the report labels every finding `(rule)`
or `(ai)` so a reviewer knows which kind of claim they are looking at.

## Install

```bash
pip install ./extensions/ayush-3516/docs-lint
export SUPERDOCS_API_KEY=your-key-here
```

Python 3.11+. Nothing else to install.

## Use

```bash
docs-lint init --styleguide styleguide.md   # write config, upload the guide
docs-lint check                             # detect only; never writes
docs-lint check --since origin/main         # only what this branch changed
docs-lint fix                               # propose corrections for review
docs-lint apply <decisions.json>            # apply exactly what was approved
docs-lint resume                            # continue an interrupted run
docs-lint report                            # what a run cost, stage by stage
docs-lint rules                             # list the built-in rules
```

### Reviewing proposed fixes

`docs-lint fix` opens a review page on `127.0.0.1` (ephemeral port, single-use token in the URL)
showing every proposed correction as a card with its before and after, the rule that raised it, and
whether it came from a deterministic rule or the style-guide review. Approve and reject
individually, then apply.

```
┌──────────────────────────────────────────────────────────────────┐
│ docs-lint review      3 of 6 decided · 2 to apply   [Apply]      │
├──────────────────────────────────────────────────────────────────┤
│ docs/getting-started.md                                          │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │ ERROR   RULE   banned-terms · line 3                         │ │
│ │ Avoid 'utilise'; the style guide prefers 'use'.              │ │
│ │  - utilise                                                   │ │
│ │  + use                                                       │ │
│ │            [ Approve ]  [ Reject ]                           │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │ WARNING  STYLE GUIDE REVIEW   style-guide · line 3           │ │
│ │ Rewrite to match the style guide.                            │ │
│ └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

The page is a thin client over the same API `docs-lint apply` uses — it posts the identical
decisions structure. That ordering was deliberate: the machine path was built first, so the gate is
fully testable without automating a browser, and the browser cannot do anything the API does not
already permit. Closing the tab changes nothing; the proposals are written to a decisions file
first either way, so a review can always be finished later with `docs-lint apply`.

Prefer the file? `docs-lint fix --plan decisions.json` skips the browser entirely.

### As a pre-commit hook

```yaml
repos:
  - repo: https://github.com/ayush-3516/superdocs-builds
    rev: main
    hooks:
      - id: docs-lint-local   # deterministic rules only: fast, offline, free
```

`pre-commit` passes staged files as arguments, so only touched documents are ever checked. Use
`docs-lint-local` on commit and the full `docs-lint` in CI — the style-guide review took between 20
and 135 seconds per document in testing, which is fine for a pull request and not fine for a commit.

### In CI

Copy [`examples/github-workflow.yml`](examples/github-workflow.yml). It narrows the run with
`--since`, emits SARIF, and uploads it to code scanning so findings appear inline on the diff.

## Configuration

Everything a team owns lives in `docs-lint.toml` and the style guide. Both are data.

```toml
[docs-lint]
include  = ["docs/**/*.md"]
error_on = ["error"]            # only these severities fail the build

[styleguide]
path           = "styleguide.md"
content_sha256 = "..."          # edit the guide and every cached verdict invalidates

[superdocs]
budget_operations = 100          # hard ceiling; the run stops and says what it skipped
sample            = 0            # check at most N files; 0 means all

[rules.banned-terms]
severity = "error"
terms    = { utilise = "use", leverage = "use", "in order to" = "to" }

[rules.passive-voice]
severity = "off"                 # disable any rule you disagree with
```

Severity is per rule, including for the model-driven ones (`style-guide`,
`unanchored-proposal`). A misspelled setting is an error, not a shrug — a rule name with a typo in
it silently doing nothing is how people stop trusting a linter.

## Scope

**Accepts** `.md`, `.mdx`, `.markdown`.

**Does not accept DOCX**, deliberately. The card's definition of strong includes findings that map
to precise locations and a `--fix` that can be shown not to have touched anything else. In Markdown
those are provable: character offsets are real, and `git diff` settles the argument. In a binary
committed to git they are much harder to *prove*, and an unproven claim is worse than a declared
limitation. SuperDocs accepts `.docx` on the same endpoints, so this is a config change rather than
a rewrite if it is ever worth doing.

## What it does about the hard parts

| Requirement | How |
|---|---|
| **Visible stages** | Seven stages, each announcing what it decided. Real branches: skip on cache or lock, retry on transient failure, degrade to local rules, stop on budget, escalate to a human. |
| **Survives being stopped** | State written atomically after every transition. The SuperDocs job id is persisted *before* the first poll, so `docs-lint resume` reattaches to work already paid for instead of buying it twice. Proven by a test that `SIGKILL`s a real process mid-run. |
| **A human holds the gate** | Per-item approve/reject through SuperDocs' own HITL API. Rejecting one finding leaves the rest untouched, because that is the API's native batch shape, not something reconstructed locally. |
| **A machine can drive it** | `fix --plan` writes a decisions file; `apply` consumes one. JSON and SARIF output, meaningful exit codes. No interface to click through. |
| **Never bluffs** | Every file ends with exactly one verdict, and a clean verdict must name the checks that ran. A pass that failed is never counted as a check that happened; the run is marked partial and says why. |
| **A stranger can run it** | `pip install`, then `docs-lint init && docs-lint check`. Sample repo included. |
| **Proves itself** | 227 tests, green with **no API key set**, driving the real client over real HTTP against a stateful fake service. Response shapes are pinned against cassettes recorded from the live API. |
| **Takes no orders from documents** | Fixed instruction that never interpolates file content; every proposal must target a chunk from the manifest of the document actually uploaded. Anything else is discarded *and reported*. |
| **Concurrent runs stay separate** | One SuperDocs session per document, `O_EXCL` locks per file, atomic cache writes. Proven by a test running two real processes at once. |
| **Knows what it cost** | Per-stage timings and operations charged, on every run and retrievable later with `docs-lint report`. |

## Where it fails, and what it cannot do

Written down because knowing where a tool breaks is more useful than a feature list.

**The style-guide review is not repeatable.** The same document, guide and instruction produced
seven proposals on one run, zero on the next, and one on the third
([BUGS.md](BUGS.md) #11). The deterministic rules are unaffected, which is precisely why they are
not delegated to the model — but do not build a hard CI gate on the `style-guide` rule alone.

**Applying a model fix re-exports the whole document, and the export is not byte-preserving.** It
was observed inserting a blank line inside a fenced code block and splitting a paragraph
mid-sentence ([BUGS.md](BUGS.md) #10). docs-lint diffs the result and warns about every region that
changed without an approval behind it, but it cannot prevent it. If that matters to you, run with
`--no-ai` and take only the deterministic fixes, which are applied surgically by offset and never
re-export anything.

**Two rules can target the same text.** The first approved fix wins and the rest report as
superseded; a second run catches what remains. It converges, but not in one pass.

**`heading-case` guesses.** It tolerates a single capitalised word mid-heading, because one is
usually a proper noun it does not know about. Two or more it calls Title Case. That threshold is a
judgement call and it will occasionally be wrong in both directions; add your own words under
`proper_nouns`.

**`passive-voice` is a heuristic** and says so in every finding. It is `info` by default and worth
turning off unless your team actually wants the nudge.

**Nothing is verified about the model's judgement.** Where the review claims a sentence violates
the guide, docs-lint reports the claim and shows you the before and after. It does not check
whether the claim is true. That is what the approval gate is for.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

pytest                  # 227 tests, no API key needed, no operations spent
pytest -m resume        # kills a real process mid-run and resumes it
pytest -m concurrency   # two real processes over one repository
pytest -m injection     # documents that try to give the linter orders
ruff check . && ruff format --check .
```

`tests/fake_superdocs/` is a stateful fake of the SuperDocs API served over real HTTP, with
injectable faults. Tests drive the actual client against it, so request construction, retry policy
and parsing are genuinely under test. `tests/fixtures/cassettes/` holds responses recorded from the
live service; where the fake and a cassette disagree, the cassette wins.

See [TASK.md](TASK.md) for how to work in this codebase, [PROGRESS.md](PROGRESS.md) for the
assumptions made along the way, and [BUGS.md](BUGS.md) for everything found in SuperDocs while
building.

## SuperDocs features used

Reference-file attachments (the style guide), document upload with chunk-id structural editing,
async chat jobs with `approval_mode: "ask_every_time"`, the human-in-the-loop per-item approval API,
Markdown export, and `whoami` for quota.

## License

MIT, per this repository.

---

Built by Ayush Chaudhari for the SuperDocs task.
