# afteraction — plan

Storm restoration after-action report builder. The assigned build for SuperDocs Round 2, Task 2.

This file is the plan and the decision log: what is being built, for whom, and why each choice is
the right one. It is kept current, so it describes the design as it stands rather than the order in
which it was arrived at.

---

## What it is

After a major outage, a utility owes its regulator and its board an after-action report: what
happened, when, how crews were mobilised, how quickly power came back, what customers were told,
and what the organisation learned. Today somebody assembles that by hand out of three record sets,
and it takes weeks.

`afteraction` reads those records and drafts the report **inside a SuperDocs document**. It decides
what each section should say and sends targeted edit instructions; SuperDocs performs the edits, a
person approves them, and the finished file is exported for the board.

**SuperDocs does the editing. This tool does not.** That line is the whole design, and the brief is
blunt about it: *build ON SuperDocs, never a version OF SuperDocs.*

## Who it serves

An emergency-response manager at an electric or water utility.

Their problem is not writing prose. It is that **the commission will challenge specific claims**,
and every sentence has to be defensible against a log line they can point to. A report that reads
well and cannot be defended is worse than no report.

## What the card requires

| | |
|---|---|
| 1 | Takes the event log, crew records and customer-communication archive |
| 2 | Renders the restoration timeline **as a diagram inside the document** |
| 3 | Drafts each narrative section **against the logged facts** |
| 4 | **Separates what the records show from what the team concluded** |
| 5 | Lessons-learned items **carry forward into the next event's report** as open or closed |

## What "strong" means

The card names it, so this is what gets built first and demonstrated last:

> every timeline claim in the narrative is traceable to a log entry, and open actions genuinely
> carry forward across two consecutive event reports.

Two things follow from that sentence.

**Traceability is a test, not a promise.** Every drafted claim carries a log-entry reference, and a
verification pass resolves each one. A claim whose reference does not resolve is reported, not
quietly shipped. The number it reports — claims checked, claims traced, claims flagged — is the
evidence.

**The demo is two storms, not one.** "Carry forward across two consecutive event reports" cannot be
shown with a single run. Storm A produces lessons-learned items with identities and a status; Storm
B opens with those items marked open or closed, because it read them, not because they were typed
in again.

Requirement 4 is a structural decision rather than a prompt. The report template holds two visibly
different kinds of statement:

- **Observed** — traceable to a log entry, and marked as such.
- **Assessed** — the team's judgement, marked as judgement.

A regulator can then tell at a glance which is which. Blending them is the failure mode this build
exists to avoid.

## Shape

```
six record sets, split by where the record came from    (synthetic, committed)
  weather · telemetry · damage · crew · comms · field reports
                    │
                    ▼
        parse ──► merged chronological spine + facts, each keyed to a record
                    │
                    ├──► restoration curve   ──► PNG ──► uploaded as an image
                    ├──► consumer contacts   ──► PNG ──► uploaded as an image
                    │
                    ├──► templates/report.html ──► the styled skeleton that is uploaded
                    │
                    ▼
        Python groups the timeline into time windows (1h or 2h, from the
        event's own length) and hands each window's raw records over
                    │
                    ▼
   SuperDocs:  upload ──► chat ──► approve ──► export
                    │       │
                    │       └── one turn per section, one turn for ALL windows,
                    │           and a last turn that summarises the finished
                    │           document into the Executive Summary
                    ▼
        lessons-learned store ──► carried into the next event
```

### The four calls

The minimum contract, and what each is for here:

| Call | Used for |
|---|---|
| `upload` | The report skeleton, and the restoration-curve image |
| `chat` | One instruction per section, carrying the log lines that section may use |
| `approve` | The human gate — accepted or rejected per proposed change |
| `export` | The finished report |

Everything else on the surface is optional depth, and comes only after these four work.

## Stack

| | | Why |
|---|---|---|
| Python 3.13 | the tool | Same language as the rest of this round's work |
| httpx | the four calls | Synchronous is enough; there is no concurrency to win here |
| pydantic | records and facts | Turning three messy record sets into typed facts is most of the work |
| matplotlib | the restoration curve | The card asks for a diagram inside the document, so it is rendered and uploaded |
| a JSON file | lessons-learned | The carry-forward state. Small, inspectable, and diffable in the pull request |
| typer | the CLI | `afteraction build storm-a` |
| pytest | tests | The round asks for tests that run without a live key |
| uv | the environment | One command from clone to running, in an isolated venv, against pinned versions |

**The environment is uv, with `uv.lock` committed.** `uv run python -m afteraction demo` creates the
virtualenv, installs the locked versions and runs, in one command on a machine that has never seen
the project. Nothing is installed into system Python. A stranger reaching a working system in
minutes is graded, and a lockfile is what makes their run match this one. The README documents a
`python -m venv` plus `pip install -e` route for anyone without uv.

**No UI.** The document is the interface: SuperDocs already has review, version history and export.
A second review screen would duplicate the product this is meant to be built on.

**No database.** State is two event folders and one JSON file. A reviewer can open it and see the
carry-forward working.

**No agent framework.** Task 1 needed a visible multi-stage graph because its brief demanded one.
This brief does not. The model work happens inside SuperDocs through `chat`, so orchestrating a
second agent around it would add a layer that earns nothing.

## Plan

**1 — Prove the pipe.** Account, key, and all four calls working end to end on one trivial
document. Nothing else starts until that runs.

**2 — The corpus.** Two synthetic storm events: event log, crew records, customer communications.
A fictional utility. Realistic enough that a timeline and a restoration curve fall out of it, and
with deliberate gaps, so that "the records do not say" has something to point at.

**3 — Facts and traceability.** Records parsed into facts, each keyed to a log entry. The graded
property comes before any prose.

**4 — Sections.** One instruction per section, each carrying only its own log lines. Observed and
Assessed kept structurally apart.

**5 — The curve, and the gate.** Restoration curve rendered and inserted. Approval flow with
**reject** working, not only accept.

**6 — Carry-forward.** Storm B opens Storm A's lessons-learned as open or closed. Run both twice,
so it is a property and not a coincidence.

**7 — Verify and ship.** The traceability pass reports its numbers. README with a screenshot, the
run commands, and the SuperDocs features used. Pull request into `superdocsapp/superdocs-builds`.

## Decisions taken before starting

- **A mock stands in for SuperDocs from day one.** Parsing, facts, the curve and the carry-forward
  all run and are tested with no key and no network. Only the four calls touch the API. This is
  what lets a stranger run the tests, which the round grades, and it is what keeps the operation
  budget from being spent on debugging.
- **A small-sample mode and a stopping rule exist before the first loop.** The brief warns to learn
  this on day one rather than day nine. One operation covers up to twenty-five sections of edits,
  and two events multiply everything.
- **All data is fabricated.** A fictional utility, fictional crews, fictional customers. No real
  outage data, no third party's records.
- **Numbers are never written by a model.** Restoration percentages, customer counts and durations
  are computed from the records and passed in. The model writes prose around figures it is given.
- **The report's design is a file, not a string in Python.** `src/afteraction/templates/report.html`
  holds every style attribute in the project; `template.py` fills its slots and adds none. Changing
  how the report looks is an edit to a file a designer can open in a browser. What *appears* — which
  sections get an Assessed heading, which get a gaps heading — stays in `sections.py`, because that
  is decided from the records, not from taste.
- **Styling is inline, because that is the kind that survives.** Measured before the template was
  written: the same document was uploaded three ways and the parsed result read back. A `<style>`
  block in the head is dropped on upload; `style="…"` attributes are kept, and arrive in the `.docx`
  as native Word formatting (`w:shd`, `w:tcBorders`, `w:tcMar`, `w:rFonts`). A stylesheet would look
  correct locally and arrive unstyled — a failure visible only in the exported file, which is the
  worst place to find one.
- **Observed, Assessed and gaps are colour-coded.** Teal, amber and grey. The distinction the build
  exists to protect should survive a reader who skims.
- **SuperDocs is an AI editor, so form is asked for rather than assembled.** Each instruction states
  the shape its section should take — a bulleted list for the timeline and the restoration figures,
  a short paragraph elsewhere — and the concision rules travel with it. Building the markup here and
  sending it as text would waste the one thing the service is for. The offline mock obeys the same
  directive, so the two paths produce the same document rather than only the same words.
- **The finished document is checked for shape, not only for citations.** Every heading must be one
  the skeleton wrote, and no drafted section may still hold its placeholder. Citations inside known
  sections say nothing about content invented outside them, and a model that adds its own heading
  can write anything underneath it.
- **An edit that reports success and changes nothing is re-issued once.** Exports are free, so the
  document is read back before it is called finished. Bounded to one pass: a second failure is
  reported, because each retry costs an operation. A section a *person* rejected is never retried —
  that is a decision the gate exists to record.
- **The number of events is data, not code.** `demo` reads `data/` rather than naming storms, so
  nought, one, three or twenty all work; only the two committed events happen to be two. Ordering
  is by the event's start date, never by folder name, because carry-forward is only meaningful in
  chronological order and a folder name is a naming convention rather than a fact.
- **An event that raises nothing must still read as finished.** Zero is a valid answer, so the
  skeleton states the absence rather than leaving a placeholder for an edit that will never
  arrive, and an assessed judgement is only made about something that actually happened — an
  event handled without mutual aid says nothing about the mutual-aid decision.
- **Page count is a property of the deliverable.** A4, narrow margins, a wide and short curve.
  Three pages for both storms.
- **"Change nothing outside this section" is measured, not asserted.** The document is
  fingerprinted per section between turns, and an edit that moves a section it was not aimed at
  fails the run. The brief asks for exactly this — *byte-identical where you promise untouched* —
  and a promise the tool makes in every instruction is the wrong thing to leave unchecked. The
  comparison ignores blank-line placement and the regenerated signature on a hosted image URL,
  because neither is content.
- **Nothing an edit could land in is allowed to be ambiguous.** Every live defect found in this
  build had the same root cause: the edit had more than one plausible target. Five sections carried
  the identical paragraph "Placeholder for observed statements.", and "Restoration Curve" sits one
  word from "Restoration Performance" — which is how the chart came to overwrite the restoration
  figures on a live run. So each placeholder names its own section, and every section is named to
  the model exactly as its heading reads, number included; `heading_for()` is the single source of
  that name so an instruction and the document cannot drift apart. Three consecutive runs had
  needed a retry before this; afterwards, none did. The retry stays as a safety net, but it was
  treating a symptom.

## Risks

**Latency reads as a hang.** Operations on large documents can take from thirty seconds to several
minutes with no visible progress. That is documented behaviour, not a crash, and the CLI should say
so rather than look frozen.

**The double parse.** Proposed-change content arrives as a JSON-encoded string and needs a second
parse; the final result is already an object. Missing it is the most common reason integrators see
empty diff cards with every field undefined. Worth hitting on day one, deliberately.

**Operations budget.** Two events, several sections each, plus reruns. Capped from the start.

## Notes from reading the other submissions

Twenty-three pull requests were open on the public repository when this plan was written. Three
patterns were common to the strongest, and are adopted here:

- **An offline mock, so the work runs with no key.** The two strongest builds both ship one.
- **One sentence naming what "strong" means, then evidence for it** — not a feature list.
- **Bugs found in SuperDocs are reported.** Two submissions did, and the brief says reported bugs
  earn points everywhere.

One warning was also clear. The largest submission was an agentic pipeline with its own retrieval,
its own state store and its own review dashboard. It is impressive work, and it reads as a version
*of* SuperDocs rather than a build *on* it. The temptation to reshape a Task 1 system into this
slot is real and is being deliberately declined: here, SuperDocs does the document work.

---

## Correction, 21 August: one log file was the wrong shape

Everything above was built against a single `event_log.csv` per event. Three problems
surfaced when the data was looked at properly, and all three were structural rather than
cosmetic.

### 1. The timeline was the log, reprinted

The old `_timeline` wrote one bullet per record. Thirty-two records gave eighteen
bullets, which reads well and hid the defect: a real substation running a multi-day
restoration logs **thousands** of lines, and one bullet each would make the report the
log. A commission wants roughly twenty milestones whether the log holds thirty lines or
thirty thousand — the output length is fixed by what a person will read, so the funnel
has to absorb the growth.

**Decision.** Group the timeline into fixed time windows and write one bullet per
window, with the window size taken from the event's own length:

| Event duration | Bullet window |
| --- | --- |
| <= 16 hours | 1 hour |
| > 16 hours | 2 hours |

Sixteen hours is where a storm stops being a shift and becomes a multi-day restoration:
crews stand down overnight, water has to recede, mutual aid travels. Past that an
hour-by-hour account is mostly empty hours. Windows are clock-aligned, so a reader sees
`18:00-20:00` and not `17:43-19:43`, and empty windows produce no bullet at all.

Storm A is 45 hours, so 2-hour windows: **45 records become 17 bullets**, one window
absorbing 15 records on its own. Storm B is 12 hours, so 1-hour windows. The pair
deliberately covers both branches of the rule.

**Python picks the window and which records fall in it; SuperDocs writes the sentence.**
That split is the whole point. A model choosing which twenty of two thousand records
matter produces a selection nobody can state and nobody can defend to a regulator — so
selection stays in code, and compression is what the model is asked for.

**The cost this avoided.** Seventeen windows could have been seventeen chat turns, which
is seventeen billable operations for a section that costs one. The API allows up to 25
targeted edits in a single operation, so every window goes out in **one** request. There
is a test for it, because it is a budget property rather than a style one.

### 2. Evidence and hearsay looked identical

The damage figures — "34 poles, 52 spans, 9 transformers" — lived as **prose inside a
note**. Every other number in the report is computed in Python and handed to the model;
those three rode along inside a quoted string where nothing could check them. And the log
could not distinguish a consumer saying a pole looks broken from a transformer reporting
itself faulted from a crew confirming it on site. Three grades of evidence, one
indistinguishable line each.

**Decision.** Split the single log into six sets by **where the record came from**, and
merge them back into one chronological spine at load time:

| File | Prefix | What it is |
| --- | --- | --- |
| `weather.csv` | `WEA` | an external feed: the met office, a monitoring mast |
| `telemetry.csv` | `TEL` | the network reporting on itself: trips, faults, counts |
| `damage.csv` | `DMG` | an asset recorded as damaged, with its own provenance |
| `crew.csv` | `CRW` | gang mobilisation and release |
| `comms.csv` | `COM` | messages in **both** directions |
| `field_reports.csv` | `FLD` | a human on site: safety, access, standing water |

The id prefix carries the grade of evidence into the finished document, so a reader
seeing `[TEL-0032]` knows it is machine data and `[COM-0014]` knows it is a phone call,
without coming back to the source. Damage counts are now structured (`asset_type`,
`count`, `status`, `reported_by`, `source_ref`) and summed in Python like every other
figure. `DamageStatus.REPORTED` and `CONFIRMED` are **never added together** — counting
one consumer's word alongside a crew's inspection asserts more broken poles than were
ever broken.

There is no `event_log.csv` any more. A seventh file restating the other six is a file
that drifts out of step with them, so `Corpus.log` is derived by merging.

The chain this unlocks, and the reason it was worth the rework:

```
COM-0002  in   call centre  "Tree on line, Mohishila Colony"
   -> DMG-0002  3 poles  reported_by=customer  source_ref=COM-0002
   -> CRW-0002  line gang mobilised to 11 kV MHS-07
   -> DMG-0002  repaired 16:40 the following day
```

A consumer's call traced through to a repair, every step citable.

**Two consequences worth writing down.**

*A citation resolves to a record, not to a position on a timeline.* A crew with no
mobilisation time has no place in a chronological merge — but the record exists, and
LL-A1 is a lessons-learned item about exactly that missing time. So `entry_ids` spans all
six sets while `log` stays the timeline.

*A gap that names a record is citing it.* "Crew CRW-0005 has no release time" reads as an
unsourced foreign citation unless the gap declares `CRW-0005` as a source. `Gap` gained a
`sources` field for this, and the need for it was found by the traceability pass flagging
this build's own report.

### 3. Inbound messages were missing entirely

`customer_comms.csv` held eight rows, all outbound. The event log's `communication`
entries recorded the same eight facts a second time — the duplication that made the whole
structure feel wrong. Nothing recorded consumers contacting the utility, which in a real
storm is the largest stream of all and the first thing a commission asks about: *how many
consumers called, and how long did they wait?*

`comms.csv` now carries `direction` (in/out), the inbound channels a consumer actually
uses (call centre, SMS, WhatsApp, email), and `resolved_at`. Storm A ends with 46 contacts
still open and one batch closed past its target; Storm B closes every one inside twelve
hours. That contrast is the improvement story the two reports tell together.

`complaint_target_hours` is a field on the event rather than a constant: a four-hour
squall and a four-day flood cannot answer to the same number, and the utility already
knows which it is operating under.

### 4. Two things the new shape supports

**An executive summary, written last.** Ten sentences at the top of the document. It is
the only instruction that asks the model to read *the document* rather than a list of
facts — SuperDocs is already holding it, so handing over a second copy of the facts would
only give the summary and the body a chance to disagree. It runs after the retries,
because a summary written before the sections is a summary of what they were going to say.

It is a real `<h2>`, not a styled table cell. That is functional rather than visual: the
export becomes `## Executive Summary`, which is what the per-section fingerprint splits on
and what the placeholder check searches under. As a table it would have been invisible to
both, and a summary that silently failed to write would have shipped.

**A second chart.** Consumer contacts received against contacts closed, with the backlog
as the space between the two step lines and the overdue part of that backlog shaded. Both
charts moved to a validated categorical palette — the trio was run through a colour-vision
and contrast check rather than picked by eye, and the first attempt (the report's own accent
and green) failed three of six checks including normal-vision separation at delta-E 10.2,
well under the floor of 15. Aqua sits below the 3:1 contrast floor on white, so every
series is directly labelled as well as legended: identity is never carried by colour alone.

### 5. Scale: one substation, not a district

The old data covered a whole distribution division, 342,000 consumers. Real reporting runs
substation by substation — each substation writes its own after-action report and the
parent circle combines them for the public. Both storms were rebuilt at **Neamatpur 33/11
kV**, 28,400 consumers, five feeders. Smaller area, tighter numbers, and a rollup to a
circle-level report becomes the obvious next feature rather than a rewrite.

### 6. The prompt is now on screen

SuperDocs is an AI editor, so what this tool actually controls is the brief. Until now the
CLI printed what came *back* and never what was asked, which meant a reviewer at the
interactive gate was reviewing the answer without the question. Every turn now announces
its instruction first: `--prompts` on `build` and `demo`, on by default under
`--gate interactive`. It is printed whole, for the same reason the gate refuses to
truncate proposed text.

### What this cost

The two live reports in `docs/`, both report screenshots and the verified 28/28 and 23/23
figures were all produced against the old data and are stale. They need a live re-run.
Offline the suite is green at 162 tests and both storms build clean end to end.

### Not built, deliberately

A report re-issued at 24 hours and again at 48 as the logs grow. It needs no feature: the
pipeline is a pure function of the data folder, so re-running after the records grow
produces the updated report. The property is worth *keeping* — it is the reason nothing
here caches parsed state between runs — but there is nothing to write.

---

## Correction, 22 August: the two chart sections were outside the safety net

A live run failed the surgical check: the turn aimed at `7. Restoration Curve` also
changed `6. Consumer Communications`. That much worked as designed. What did not is that
section 7 kept its placeholder, the run exported a `.docx` with "Placeholder for the
restoration curve" sitting where the chart belongs, and **nothing in the output mentioned
it**. The failure that got reported was the collateral edit; the missing chart went
unremarked.

The cause is a gap in a list. `unfilled()` only inspects sections passed to it, and the
pipeline passes `drafted` — which is built from `SECTION_TITLES`. The curve and contacts
sections are not in `SECTION_TITLES`; they are placed by their own turns after the loop.
So both sat outside the placeholder sweep **and** outside the one-pass retry, which is
the exact mechanism built earlier for exactly this failure. The retry was written after a
live run left the lessons section holding its placeholder, and the same blind spot was
left in place two sections further down.

**Decision.** Track the chart turns as they run, as `(title, instruction)` pairs, and feed
them into the mid-run sweep, the retry, and the final shape check — the pattern the
lessons section already uses. A chart carries no citations to reject, so there is no
refusal to respect: an empty chart section only ever means the image did not land.

Two smaller things the same run exposed, both the terminal saying something untrue:

- The first summary line took its marker from the **run** verdict, so a surgical failure
  printed `FAIL` beside a clean `37/37 claims traced (100%)`. A reader would blame
  traceability for another check's failure. Each check now carries its own verdict, and
  the run verdict is its own last line naming what failed.
- `retried` listed every section that *qualified* for a retry, including ones the
  `--limit` budget stopped before reaching. It now records what was actually re-issued.

**The general lesson, worth stating because it will recur.** Every check here takes a list
of what to check, and every list is built from `SECTION_TITLES`. Any section that arrives
by another route is invisible to all of them by default, and invisible in the quiet
direction — the run passes. A new section type needs adding to those lists, not just to
the pipeline.
