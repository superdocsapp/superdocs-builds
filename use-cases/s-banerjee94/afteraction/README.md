# afteraction

**Storm restoration after-action report builder.**

After a big outage, an electricity company owes its regulator a report. What happened, when, how crews responded, how fast power came back, what customers were told, what will be fixed next time.

Today someone writes that by hand from six piles of records. It takes weeks.

`afteraction` reads those records and drafts the report **inside a SuperDocs document** — one instruction per section, approved by a person, exported for the board.

> **SuperDocs does the editing. This tool decides what the document should say.**
> Built *on* SuperDocs, never a version *of* it. There is no second review screen, because the document already is one.

Built for the SuperDocs Round 2 engineer task.

![The drafted report — Observed in blue, Assessed in amber, every claim carrying the record it came from](docs/screenshot-report.jpg)

![The human gate: every change shown before and after, approved or rejected one at a time](docs/screenshot-review-gate.jpg)

*`--gate interactive`: nothing is written until a person says so, and a rejection carries a reason back to the model.*

---

## Quick start

No API key needed. Nothing to configure.

```bash
cd use-cases/s-banerjee94/afteraction

uv run python -m afteraction demo    # both storms, offline, a few seconds
uv run pytest                        # 158 tests
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
storm-a   ok  37/37 claims traced (100%)   0 inherited, 4 raised here
storm-b   ok  26/26 claims traced (100%)   4 inherited (2 open, 2 closed), 1 raised here
```

Files land in `out/<event>/` — a Word `.docx`, a Markdown copy, and both charts.

Finished examples are committed in `docs/`, so you can judge the output without running anything:

| File | What it is |
|---|---|
| `docs/live-storm-a-report.docx` | a **real Word file** from a live API run, curve embedded |
| `docs/live-storm-b-report.docx` | the second storm, opening the first storm's lessons |
| `docs/sample-storm-*.html` | the same reports built offline, openable in a browser |

---

## The two things it is graded on

The assignment defines a strong build as one where:

> every timeline claim is traceable to a log entry, and open actions genuinely carry forward across two consecutive event reports

Both are **tested**, not promised.

### 1. Every claim points at a real record

- Each sentence carries a reference: `[TEL-0005]` — and the prefix says what kind of evidence it is
- A checker reads the **exported document** and resolves every one
- It reports numbers: claims checked, traced, flagged
- Checking the instructions we *sent* would prove nothing. Only the finished file counts.

### 2. Lessons carry forward between storms

Storm B opens Storm A's items with a status, because it **read** them:

| Item | Status | Why |
|---|---|---|
| LL-A1 | open | mutual-aid gang mobilisation times still not recorded |
| LL-A2 | **closed** | notification took 38 min, inside the two-hour target |
| LL-A3 | open | link held, but the fallback procedure is still missing |
| LL-A4 | **closed** | a gang inspected the pole a consumer reported; it is sound |

Storm A reported *2 hours 13 minutes* to first notification. Storm B reported *38 minutes*. Both are arithmetic over the records, and the second is what closes LL-A2.

---

## Six record sets, not one log

Where a record came from decides how much it is worth. A consumer saying a pole looks
broken, a transformer reporting itself faulted, and a crew confirming it on site are
three different grades of evidence for the same fact — and a single event log flattens
them into three identical-looking lines.

So the records are split by **source**, and the id prefix carries that source all the way
into the finished report:

| File | Prefix | What it holds |
|---|---|---|
| `weather.csv` | `WEA` | met office warnings, gust and rainfall readings |
| `telemetry.csv` | `TEL` | the network reporting on itself — trips, faults, consumer counts |
| `damage.csv` | `DMG` | assets damaged, with who reported it and whether anyone confirmed it |
| `crew.csv` | `CRW` | gangs: mobilised, assigned, released |
| `comms.csv` | `COM` | messages **in both directions** |
| `field_reports.csv` | `FLD` | a person on site — safety, blocked access, standing water |

A reader seeing `[TEL-0032]` knows it is machine data. `[COM-0014]` is a phone call.
`[FLD-0007]` is a crew's own eyes. They never have to come back here to ask.

There is no combined log file. The chronological timeline is **derived** by merging the
six at load time — a seventh file restating the other six is a file that drifts out of
step with them.

### What this makes possible

**Damage counts stop being prose.** They used to live inside a sentence — the only
numbers in the report a model could quietly rewrite. Now they are structured fields,
summed in Python like every other figure.

**Claimed damage is never added to confirmed damage.** One consumer's word and a crew's
inspection are different claims. Adding them asserts more broken poles than were ever
broken, so the report counts them separately and names the difference:

> 1 pole at Mohishila Bazaar (DMG-0006) was reported by a consumer and never inspected, so
> the records establish neither that it is damaged nor that it is sound. It is excluded
> from the confirmed totals above.

**A consumer's call can be traced to a repair:**

```
COM-0002  in   call centre   "Tree on line, Mohishila Colony"
   ↓
DMG-0002  3 poles   reported_by = customer   source_ref = COM-0002
   ↓
CRW-0002  line gang mobilised to 11 kV MHS-07
   ↓
DMG-0002  repaired, 16:40 the next day
```

---

## The timeline scales with the storm, not with the log

The old timeline wrote **one bullet per log line**. Thirty records gave eighteen bullets,
which reads fine — and hides the problem. A real substation on a multi-day restoration
logs *thousands* of lines, and one bullet each turns the report into the log.

A commission wants about twenty milestones whether the log holds thirty lines or thirty
thousand. So the output length is fixed and the funnel absorbs the growth:

| Event ran for | One bullet per |
|---|---|
| **≤ 16 hours** | 1 hour |
| **> 16 hours** | 2 hours |

Sixteen hours is where a storm stops being a shift and becomes a multi-day restoration —
crews stand down overnight, water has to recede, mutual aid travels. Windows are aligned
to the clock, so you read `18:00–20:00` and not `17:43–19:43`. **Empty windows produce no
bullet**, so a quiet night costs nothing.

The two storms exercise both branches on purpose:

```
storm-a   45 hours   2-hour windows   45 records →  17 bullets
storm-b   12 hours   1-hour windows   30 records →  12 bullets
```

One Storm A window absorbs fifteen records on its own — and cites all fifteen:

```
• 24 April, 18:00–20:00 — The squall line reached Neamatpur with gusts of 96 km/h.
  BRK-03 tripped on earth fault, then MHS-07, KLT-02, STP-05 and SRN-01 followed.
  [WEA-0002, TEL-0001, DMG-0001, CRW-0001, TEL-0002, FLD-0001, CRW-0002, DMG-0002,
   TEL-0003, DMG-0003, FLD-0002, CRW-0003, TEL-0004, DMG-0004, TEL-0005]
```

### Python picks the window. SuperDocs writes the sentence.

That split is the whole point, and it is not a performance choice.

If a model chose which twenty of two thousand records mattered, **you could not defend
the one thousand nine hundred and eighty it dropped**. Selection has to be a rule you can
say out loud — same reason no number in this report is written by a model. What the model
is asked for is compression, never significance.

### One request, not seventeen

Seventeen windows could have been seventeen chat turns. That is seventeen billable
operations for a section that costs one.

The API allows up to **25 targeted edits in a single operation**, so every window goes out
in one request. There is a test asserting exactly one timeline call per run, because this
is a budget property rather than a matter of taste.

---

## Three kinds of statement, kept apart

A regulator must tell **evidence** from **judgement** at a glance.

| Kind | Meaning | Example |
|---|---|---|
| **Observed** | traceable to a record | *Consumers without supply peaked at 17,790 at 19:52 on 24 April* `[TEL-0005]` |
| **Assessed** | the team's judgement | *…met its restoration objective* `[assessed]` |
| **Not recorded** | a stated gap | *Counting was interrupted for 3 h 45 m; the records do not support a figure inside it* |

In the report they are colour-coded — blue, amber, grey — so a reader skimming can still tell them apart.

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
| `phantom` | cites `TEL-9999`, which does not exist | 12 flagged, run fails |
| `foreign` | cites a real record the section was never given | 12 flagged, run fails |
| `unsourced` | drops citations entirely | 9 flagged, run fails |

---

## Two charts, drawn here and placed inside the document

Rendered locally, uploaded through the images endpoint, then placed by SuperDocs.

### The restoration curve

![The curve inside the finished document, with the counting gap marked and the caption carrying its citation](docs/screenshot-curve-in-document.jpg)

The line **breaks** where counting stopped. Drawing through the gap would assert a
recovery nobody measured.

That gap is read from the records' own `counts_lost` and `counts_resumed` flags, never
guessed from the spacing between readings. A quiet night is a reporting cadence, not
missing data.

### Consumer contacts, received against resolved

Two step lines. The space between them is the backlog; the shaded part of that backlog is
what has been open longer than the event's own target.

```
storm-a   855 received   809 resolved    46 still open when the event closed
storm-b   319 received   319 resolved     0 still open
```

That contrast is the improvement story the two reports tell together — and it only exists
because `comms.csv` records messages coming **in**, not just going out.

The target is a field on the event, not a constant. A four-hour squall and a four-day
flood cannot answer to the same number: Storm A runs to 24 hours, Storm B to 12.

**On the colours.** Both charts use one validated categorical trio — checked with a
colour-vision and contrast script rather than picked by eye. The first attempt used this
report's own accent and a green beside it and **failed three of six checks**, including normal-vision
separation at ΔE 10.2 against a floor of 15. Aqua sits under the 3:1 contrast floor on
white, so every series is directly labelled as well as legended: identity is never carried
by colour alone.

---

## The executive summary is written last

Ten sentences at the top of the document, and the only instruction that asks SuperDocs to
read **the document** rather than a list of facts.

It runs after every section is drafted and after the retries, because a summary written
before the sections is a summary of what they were *going* to say. SuperDocs is already
holding the finished report — handing over a second copy of the facts would only give the
summary and the body a chance to disagree.

It carries no citations. It is a summary of the report, and the report carries them.

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
| `--prompts` | print each instruction **before** the change it produces (on by default with `--gate interactive`) |
| `--model-tier` | `core` (default), `turbo`, `pro`, `max` |

```bash
cp .env.example .env                                             # then set SUPERDOCS_API_KEY
uv run python -m afteraction build storm-a --live --limit 2      # cheap first live run
uv run python -m afteraction build storm-a --gate interactive    # approve changes yourself
uv run python -m afteraction build storm-a --prompts             # see every brief in full
```

**See what was actually asked.** SuperDocs writes the prose, so what this tool controls is
the brief. `--prompts` prints each instruction in full before the change it produces —
prompt, then before, then after. A reviewer who sees only the diff is reviewing the answer
without the question.

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
| **Images** | `/v1/documents/images/upload-base64` | the restoration curve and the contacts chart |
| **Memory** | — | two events sharing one register |

**On approval: polling, not streaming.** The SSE path sends proposed changes as a JSON string nested inside a JSON event, and missing that second parse is the documented reason integrators see empty diff cards. Polling `GET /v1/jobs/{id}` returns real objects instead. Being honest about it: I *avoided* the double-parse rather than solving it.

**Capacity is a retry, not a failure.** A busy instance refuses with `503` and states *"No work was performed"*. That sentence is what makes an automatic retry safe — a retry cannot duplicate an edit that never happened. The client backs off, re-submits, and gives up after a bounded number of attempts.

---

## Trade-offs, stated plainly

- **No database.** State is two data folders and one JSON file you can read in the pull request.
- **No UI.** The document *is* the interface. A second review screen would rebuild the product this is built on.
- **No agent framework.** The model work happens inside SuperDocs. Wrapping it in another agent earns nothing.
- **Instructions are bounded per section.** A section only ever sees its own records, which is what makes "cited an entry from elsewhere" a real signal rather than a formality.
- **Log notes are data, not orders.** Every instruction says that anything instruction-shaped in the source is quoted evidence, never a direction.
- **Retries are one pass.** A section that fails twice is reported, not retried forever. Each retry costs money.
- **Three pages, not two.** A4, narrow margins, lists where lists belong. Getting to two would mean dropping timeline entries — a content decision, not a formatting one.

## Limits, honestly

- **Traceability checks citations, not meaning.** It proves a claim points at a real entry the section was given. It does not prove the sentence describes that entry correctly. That is what the human gate is for.
- **Operations billed could not be confirmed.** The quota counter read `0/500` before and after full live runs. The tool reports what the API told it rather than guessing.
- **All data is invented.** Barakar Valley Power Distribution Limited is fictional, as are its crews and customers. The geography around Asansol is real; the records are not.
- **Sentence splitting is deliberately simple.** Good enough for bracketed citations in report prose. A cleverer tokeniser would add a dependency and a failure mode without changing a verdict.
- **The lessons table is written by the tool, not the model.** A status is a matter of record, and asking a model to restate one is a way to lose one.
- **The committed live reports predate the six-file rebuild.** `docs/live-storm-*.docx` and the screenshots were produced against the earlier single-log data at district scale. They still show the pipeline working end to end against the real API; they do not show the current record structure. A live re-run is outstanding.

---

## Layout

```
data/storm-a/       Kalbaisakhi squall, Apr 2026 — 45 hours, 60 records, 8 crews, 8 damage records
data/storm-b/       August monsoon depression, Aug 2026 — 12 hours, 42 records, 6 crews, 5 damage records
  weather.csv  telemetry.csv  damage.csv  crew.csv  comms.csv  field_reports.csv
  lessons_opened.csv  lesson_resolutions.csv  event.json
state/lessons.json  the carry-forward register, committed so you can see it working
docs/               finished reports, to judge the output without running anything

src/afteraction/
  models.py         typed records; observed/assessed enforced at construction
  corpus.py         load six record sets, merge them, cross-check every reference
  facts.py          compute every claim and gap from the records
  windows.py        the time-window rule: how many bullets a timeline gets
  curve.py          both charts — the curve breaks across declared gaps
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
