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
event log + crew records + customer comms      (synthetic, committed)
                    │
                    ▼
        parse ──► facts, each keyed to a log entry
                    │
                    ├──► restoration curve ──► PNG ──► uploaded as an image
                    │
                    ├──► templates/report.html ──► the styled skeleton that is uploaded
                    │
                    ▼
        one instruction per section, carrying only that section's log lines
                    │
                    ▼
   SuperDocs:  upload ──► chat ──► approve ──► export
                    │
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
