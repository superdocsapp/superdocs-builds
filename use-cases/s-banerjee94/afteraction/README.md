# afteraction

**Storm restoration after-action reports, drafted inside a SuperDocs document.**

After a big outage a utility owes its regulator a report: what happened, when, how crews responded, what customers were told, what will change. Someone writes it by hand from six piles of records, and it takes weeks. Every sentence in it can be challenged — so every sentence has to point at the record it came from.

`afteraction` reads the records, computes the figures, and has SuperDocs write the report around them. One instruction per section, approved by a person, exported for the board.

> **SuperDocs does the editing. This tool decides what the document should say.**
> Built *on* SuperDocs, not a version *of* it — no second review screen, because the document already is one.

![The drafted report — Observed in blue, Assessed in amber, every claim carrying the record it came from](docs/screenshot-report.jpg)

![The human gate: every change shown before and after, approved or rejected one at a time](docs/screenshot-review-gate.jpg)

*`--gate interactive`: nothing is written until a person says so, and a rejection carries a reason back to the model.*

---

## Quick start

No API key. No configuration. No network.

```bash
cd use-cases/s-banerjee94/afteraction

uv run python -m afteraction demo    # both storms, offline, a few seconds
uv run pytest                        # 162 tests
```

[uv](https://docs.astral.sh/uv/) builds the environment from `uv.lock` on first run.

**For a live run** — costs operations:

```bash
cp .env.example .env                 # then set SUPERDOCS_API_KEY=your-key-here
uv run python -m afteraction build storm-a --live --limit 2
```

---

## What it produces

Two storms, run in order. The second one **remembers** the first.

```
storm-a   ok  37/37 claims traced (100%)   0 inherited, 4 raised here
storm-b   ok  26/26 claims traced (100%)   4 inherited (2 open, 2 closed), 1 raised here
```

Output lands in `out/<event>/`: a Word `.docx`, a Markdown copy, both charts. Finished examples are committed in `docs/` so you can judge the output without running anything.

---

## The two things it is graded on

**1 · Every claim points at a real record.** Each sentence carries a citation like `[TEL-0005]`. A checker reads the **exported document** and resolves every one — checking the instructions we *sent* would prove nothing.

**2 · Lessons carry forward.** Storm B opens Storm A's items with a status because it read them:

| Item | Status | Why |
|---|---|---|
| LL-A1 | open | mutual-aid mobilisation times still not recorded |
| LL-A2 | **closed** | notification took 38 min, inside the two-hour target |
| LL-A3 | open | link held, but the fallback procedure is still missing |
| LL-A4 | **closed** | a gang inspected the pole a consumer reported; it is sound |

Storm A reported *2 h 13 min* to first notification, Storm B *38 min*. Both are arithmetic over the records, and the second is what closes LL-A2.

---

## How it works

```
six record sets  →  facts + figures (Python)  →  one instruction per section
                 →  SuperDocs: upload · chat · approve · export
                 →  lessons register  →  carried into the next event
```

- **Six record sets, not one log.** `WEA` weather · `TEL` telemetry · `DMG` damage · `CRW` crews · `COM` messages · `FLD` field reports. The prefix travels into the report, so `[TEL-0032]` reads as machine data and `[COM-0014]` as a phone call.
- **Numbers are never written by a model.** Percentages, counts and durations are computed in Python and handed over as correct. Reported damage is never added to confirmed damage.
- **The timeline scales with the storm, not with the log.** Over 16 hours → one bullet per 2 hours; at or under → one per hour. Storm A: 60 records → **17 bullets**. Storm B: 42 → **12**.
- **Python picks the window, SuperDocs writes the sentence.** A model choosing which twenty of two thousand records matter gives you a selection nobody can defend.
- **All windows go out in one request.** The API allows 25 targeted edits per operation, so the timeline costs **1** operation, not 17.
- **Three kinds of statement, kept apart** — Observed (traceable, carries its record), Assessed (judgement, marked as such), and what the records do not show. Enforced when the object is built, not asked for in a prompt.
- **The executive summary is written last**, from the finished document rather than from a second copy of the facts.

Design reasoning and every decision that turned out wrong is in **[PLAN.md](PLAN.md)**.

---

## Four checks that can fail a run

Each has caught a real defect on a live run.

| Check | Catches |
|---|---|
| **Traceability** | a citation that does not resolve |
| **Shape** | an invented heading, or a placeholder an edit never replaced |
| **Surgical** | an edit that changed a section it was not aimed at |
| **Retry** | an edit that reported success and did nothing — re-issued once, then reported |

A verifier that only ever says "clean" is worse than none, so the mock can be told to misbehave and the tests prove each failure is caught.

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

- **Polling, not streaming.** The SSE path nests proposed changes as a JSON string inside a JSON event; missing that second parse is the documented reason integrators see empty diff cards. Polling `GET /v1/jobs/{id}` returns real objects. Being honest: I *avoided* the double-parse rather than solving it.
- **A `503` is a retry, not a failure.** A busy instance states *"No work was performed"* — that sentence is what makes an automatic retry safe.

---

## Commands

```bash
uv run python -m afteraction demo               # every event in order, from a cleared register
uv run python -m afteraction build storm-a      # one event
uv run python -m afteraction verify storm-a     # what the records support, drafts nothing
uv run python -m afteraction lessons            # the register: open, closed, and where
```

| Flag on `build` | What it does |
|---|---|
| *(none)* | offline mock — free, instant, the default |
| `--live` | the real API. **Costs operations** |
| `--limit 2` | stop after 2 edits. Use on a first live run |
| `--gate interactive` | **you** approve or reject each change, with reasons |
| `--gate reject-all` | refuse everything, to prove rejection works |
| `--prompts` | print each instruction before the change it produces |
| `--store <path>` | carry-forward register to use |

**Offline is the default everywhere.** A tool that spends money by default spends it by accident.

Adding a storm is a data change: drop a folder into `data/` with an `event.json` and the record files.

---

## Limits, honestly

- **Traceability checks citations, not meaning.** It proves a claim points at a real record the section was given — not that the sentence describes it correctly. That is what the human gate is for.
- **Operations billed could not be confirmed.** The quota counter read `0/500` before and after full live runs. The tool reports what the API told it.
- **The committed live reports are stale.** `docs/live-storm-*.docx` and the screenshots predate the six-record rebuild. They show the pipeline working end to end against the real API; they do not show the current record structure. A live re-run is outstanding.
- **All data is invented.** Barakar Valley Power Distribution Limited, its crews and its customers are fictional. The geography around Asansol is real; the records are not.
- **No database, no UI, no agent framework.** State is two data folders and one JSON file you can read in the diff.

---

## Layout

```
data/storm-a/  data/storm-b/     six record sets each, plus lessons and event.json
state/lessons.json               the carry-forward register, committed so you can see it work
docs/                            finished reports, to judge the output without running anything

src/afteraction/
  models.py corpus.py facts.py   records in, facts and figures out
  windows.py                     the time-window rule
  curve.py                       both charts; the curve breaks across declared gaps
  sections.py template.py        what each section may say, and its instruction
  trace.py surgical.py           traceability, document shape, per-section proof
  lessons.py                     the carry-forward store
  client.py mock.py              the four SuperDocs calls, and an offline stand-in
  pipeline.py cli.py             one event end to end; demo | build | verify | lessons
```

---

Built for the **SuperDocs Round 2 engineer task**. MIT, as the repository. All data fabricated.
