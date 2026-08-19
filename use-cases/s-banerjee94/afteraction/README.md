# afteraction

**Storm restoration after-action report builder.**

After a big outage, an electricity company owes its regulator a report. What happened, when, how crews responded, how fast power came back, what customers were told, what will be fixed next time.

Today someone writes that by hand from three piles of records. It takes weeks.

`afteraction` reads those records and drafts the report **inside a SuperDocs document** — one instruction per section, approved by a person, exported for the board.

> **SuperDocs does the editing. This tool decides what the document should say.**
> Built *on* SuperDocs, never a version *of* it. There is no second review screen, because the document already is one.

Built for the SuperDocs Round 2 engineer task.

![The drafted report — Observed in teal, Assessed in amber, every claim carrying its log entry](docs/screenshot-report.jpg)

> 📸 **Screenshot placeholder** — the interactive review gate, showing a proposed change before and after, with the approve/reject prompt.

---

## Quick start

No API key needed. Nothing to configure.

```bash
cd use-cases/s-banerjee94/afteraction

uv run python -m afteraction demo    # both storms, offline, a few seconds
uv run pytest                        # 138 tests
```

That is the whole setup. [uv](https://docs.astral.sh/uv/) builds the environment from `uv.lock` on first run.

<details>
<summary>Without uv</summary>

```bash
python -m venv .venv && .venv/Scripts/activate   # bin/activate on macOS and Linux
pip install -e ".[dev]"
python -m afteraction demo
```
</details>

---

## What it produces

Two storms, run in order. The second one **remembers** the first.

```
storm-a   ok  28/28 claims traced (100%)   0 inherited, 3 raised here
storm-b   ok  22/22 claims traced (100%)   3 inherited (2 open, 1 closed), 1 raised here
```

Files land in `out/<event>/` — a Word `.docx`, a Markdown copy, and the chart.

Finished examples are committed in `docs/`, so you can judge the output without running anything.

---

## The two things it is graded on

The assignment defines a strong build as one where:

> every timeline claim is traceable to a log entry, and open actions genuinely carry forward across two consecutive event reports

Both are **tested**, not promised.

### 1. Every claim points at a real log entry

- Each sentence carries a reference: `[EL-0008]`
- A checker reads the **exported document** and resolves every one
- It reports numbers: claims checked, traced, flagged
- Checking the instructions we *sent* would prove nothing. Only the finished file counts.

### 2. Lessons carry forward between storms

Storm B opens Storm A's items with a status, because it **read** them:

| Item | Status | Why |
|---|---|---|
| LL-A1 | open | crew arrival times still not recorded |
| LL-A2 | **closed** | notification took 38 min, inside the two-hour target |
| LL-A3 | open | link held, but the fallback procedure is still missing |

Storm A reported *2 hours 41 minutes* to first notification. Storm B reported *38 minutes*. Both are arithmetic over the records, and the second is what closes LL-A2.

---

## Three kinds of statement, kept apart

A regulator must tell **evidence** from **judgement** at a glance.

| Kind | Meaning | Example |
|---|---|---|
| **Observed** | traceable to a log entry | *Consumers without supply peaked at 74,600 at 20:15 on 24 April* `[EL-0008]` |
| **Assessed** | the team's judgement | *…met its restoration objective* `[assessed]` |
| **Not recorded** | a stated gap | *Counting was interrupted for 3 h 30 m; the records do not support a figure inside it* |

In the report they are colour-coded — teal, amber, grey — so a reader skimming can still tell them apart.

This is structural, not a request in a prompt:

- an **observed** claim cannot exist without a source
- an **assessed** claim cannot carry a citation

Breaking either is a crash when the object is built, not a bad report later.

**No number is written by a model.** Percentages, counts and durations are computed in Python and handed over. The model writes prose around figures it is given, so a wrong restoration percentage is impossible rather than unlikely.

---

## Four checks that can fail a run

A verifier that only ever says "clean" is worse than none. Each of these has caught a real defect on a live run.

| Check | Catches |
|---|---|
| **Traceability** | a citation that does not resolve, or one the section was never given |
| **Shape** | a heading the model invented, or a placeholder that never got filled |
| **Surgical** | an edit that changed a section it was not aimed at |
| **Retry** | an edit reported as applied that changed nothing — re-issued once |

The offline mock can be told to misbehave, and the tests prove each failure is caught:

| Mode | What the model does | Result |
|---|---|---|
| `phantom` | cites `EL-9999`, which does not exist | 25 of 26 claims flagged |
| `foreign` | cites a real entry from another section | 7 flagged |
| `unsourced` | drops citations entirely | run fails |

---

## The restoration curve

Drawn here, then placed **inside** the document through the images endpoint.

![The curve inside the finished document, with the counting gap marked and the caption carrying its citation](docs/screenshot-curve-in-document.jpg)

The line **breaks** where counting stopped. Drawing through the gap would assert a recovery nobody measured.

That gap is read from the log's own `counts_lost` and `counts_resumed` flags, never guessed from the spacing between readings. A quiet night is a reporting cadence, not missing data.

---

## The design is a file

`src/afteraction/templates/report.html` holds the whole look — masthead, metadata block, colour-coded headings, the carry-forward table. Open it in a browser and you see the report with its slots showing.

**Styling is inline, because that is what SuperDocs keeps:**

| Sent as | Survives upload | Reaches the `.docx` |
|---|---|---|
| `<style>` block in the head | no, dropped | no |
| `style="…"` on the element | yes | yes |

Measured before the template was written, by uploading the same document three ways. Inline styles arrive as **native Word formatting** — `background-color` becomes cell shading, `border-bottom` becomes a cell border, `font-family` becomes the font.

---

## Commands

Prefix each with `uv run python -m afteraction`.

| Command | What it does |
|---|---|
| `events` | List the storms with data on disk, oldest first |
| `verify <event>` | Show what the records support. Drafts nothing, calls nothing. **Best place to start** |
| `build <event>` | Draft one event's report |
| `demo` | Run every event in order, from a cleared register |
| `lessons` | Show the register: what is open, what is closed, and where |

### Flags on `build`

| Flag | What it does |
|---|---|
| *(none)* | offline mock — free, instant, the default |
| `--live` | the real SuperDocs API. **Costs operations** |
| `--limit 2` | stop after 2 edits. Use this on a first live run |
| `--gate interactive` | **you** approve or reject each change, with reasons |
| `--gate reject-all` | refuse everything, to prove rejection really works |
| `--model-tier` | `core` (default), `turbo`, `pro`, `max` |

```bash
cp .env.example .env                                             # then set SUPERDOCS_API_KEY
uv run python -m afteraction build storm-a --live --limit 2      # cheap first live run
uv run python -m afteraction build storm-a --gate interactive    # approve changes yourself
```

Offline is the default everywhere. **A tool that spends money by default spends it by accident.**

Adding a storm is a data change: drop a folder into `data/` with an `event.json` and the record files, and every command picks it up. Events are ordered by their start date, never by folder name.

---

## SuperDocs features used

| Feature | Endpoint | Used for |
|---|---|---|
| **Upload** | `/v1/documents/upload-base64` | the styled report skeleton |
| **Chat** | `/v1/chat/async` | one instruction per section |
| **Approve** | `/v1/chat/{id}/approve` | the human gate, change by change |
| **Export** | `/v1/documents/export` | `.docx` and `.md` — never costs operations |
| **Images** | `/v1/documents/images/upload-base64` | the restoration curve |
| **Memory** | — | two events sharing one register |

**On approval: polling, not streaming.** The SSE path sends proposed changes as a JSON string nested inside a JSON event, and missing that second parse is the documented reason integrators see empty diff cards. Polling `GET /v1/jobs/{id}` returns real objects instead. Being honest about it: I *avoided* the double-parse rather than solving it.

**Capacity is a retry, not a failure.** A busy instance refuses with `503` and states *"No work was performed"*. That sentence is what makes an automatic retry safe — a retry cannot duplicate an edit that never happened. The client backs off, re-submits, and gives up after a bounded number of attempts.

---

## Trade-offs, stated plainly

- **No database.** State is two data folders and one JSON file you can read in the pull request.
- **No UI.** The document *is* the interface. A second review screen would rebuild the product this is built on.
- **No agent framework.** The model work happens inside SuperDocs. Wrapping it in another agent earns nothing.
- **Instructions are bounded per section.** A section only ever sees its own log lines, which is what makes "cited an entry from elsewhere" a real signal rather than a formality.
- **Log notes are data, not orders.** Every instruction says that anything instruction-shaped in the source is quoted evidence, never a direction.
- **Retries are one pass.** A section that fails twice is reported, not retried forever. Each retry costs money.
- **Three pages, not two.** A4, narrow margins, lists where lists belong. Getting to two would mean dropping timeline entries — a content decision, not a formatting one.

## Limits, honestly

- **Traceability checks citations, not meaning.** It proves a claim points at a real entry the section was given. It does not prove the sentence describes that entry correctly. That is what the human gate is for.
- **Operations billed could not be confirmed.** The quota counter read `0/500` before and after full live runs. The tool reports what the API told it rather than guessing.
- **All data is invented.** Barakar Valley Power Distribution Limited is fictional, as are its crews and customers. The geography around Asansol is real; the records are not.
- **Sentence splitting is deliberately simple.** Good enough for bracketed citations in report prose. A cleverer tokeniser would add a dependency and a failure mode without changing a verdict.
- **The lessons table is written by the tool, not the model.** A status is a matter of record, and asking a model to restate one is a way to lose one.

---

## Layout

```
data/storm-a/       Kalbaisakhi squall, Apr 2026 — 32 log entries, 11 crews, 8 messages
data/storm-b/       August monsoon depression, Aug 2026 — 22 log entries, 8 crews, 5 messages
state/lessons.json  the carry-forward register, committed so you can see it working
docs/               finished reports, to judge the output without running anything

src/afteraction/
  models.py         typed records; observed/assessed enforced at construction
  corpus.py         load three record sets, cross-check every reference
  facts.py          compute every claim and gap from the records
  curve.py          the restoration curve, broken across declared gaps
  sections.py       what each section may say, and its instruction
  template.py       fills the design's slots; holds no styling itself
  templates/        report.html — the design; every style attribute lives here
  trace.py          traceability, plus the document-shape check
  surgical.py       proof that each edit stayed inside its own section
  lessons.py        the carry-forward store
  client.py         the four SuperDocs calls
  mock.py           offline stand-in, with drafting failure modes
  pipeline.py       one event, end to end
  cli.py            demo | build | verify | lessons | events
```

MIT, as the repository. All data fabricated.
