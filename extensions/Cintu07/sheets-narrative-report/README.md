# sheets narrative report

turn a selected range in google sheets into a written finance report, on the
firm template, with a chart, where **every number in the prose is substituted
from a cell and nothing else is**.

built by pawan for the superdocs round 2 task, against the superdocs api.

---

## the two things this build is trying to get right

the assignment card asks for two properties. both are easy to claim and hard to
prove, so this readme leads with how they are enforced rather than with a
feature list.

### 1. the numbers in the prose match the sheet exactly

the model is never allowed to write a digit.

every figure is computed in python from the cells. the model receives a table of
tokens and writes sentences like:

```
revenue {{fact:series.revenue.direction}} to {{fact:series.revenue.latest}}
in {{fact:period.last}} ({{fact:series.revenue.delta_pct}})
```

substitution happens in code, and while substituting we record the exact
character span every value occupies. a checker then walks the finished prose and
reports any digit that is not inside one of those spans.

so a model that ignores the instruction does not produce a quietly wrong report.
it produces a located failure that the reviewer sees before anything is saved:

```
PROBLEM: unverified numeral '4.2' at 31 in "...revenue reached about 4.2 million..."
```

this holds even when the model is fully hijacked by a hostile spreadsheet cell,
which is tested directly in `tests/test_injection.py`.

### 2. re-running after a data change updates only what moved

every fact carries a hash. on a re-run the new hashes are diffed against the
stored manifest and the work splits three ways.

| what changed | what happens | operations spent |
|---|---|---|
| nothing | section kept byte for byte | 0 |
| a number, and the sentence still reads correctly | re-substituted locally | **0** |
| a word: direction flipped, item renamed, move crossed a size band | that one section is rewritten | 1 |

the third case is the subtle one. if revenue moves from `+3%` to `+41%`, the
number is not the only thing that went stale, "edged up" is now wrong too. so
qualitative words are computed as facts from bands, not chosen by the model.
when the band changes, the section's text facts change, and the planner knows
the sentence has to be rewritten rather than merely refilled.

untouched sections are verified byte identical on **every run**, not just in
tests. if one drifts, the run fails rather than shipping.

---

## quickstart

```bash
git clone <this repo> && cd sheets-narrative-report
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

export SUPERDOCS_API_KEY=sk_your_key      # or use agent signup, see below
python scripts/demo.py                     # live three run demo
```

no key? the agent signup flow gets you one in a single call:

```bash
curl -X POST https://api.superdocs.app/v1/agents/signup \
  -H "Content-Type: application/json" \
  -d '{"terms_accepted": true, "agent_name": "narrative-report"}'
```

run the tests, which need no key and spend no operations:

```bash
.venv/bin/python -m pytest        # 207 tests, offline
```

serve the api the add-on talks to:

```bash
uvicorn narrative_report.api:app --port 8000
```

---

## installing the sheets add-on

1. open your sheet, then extensions, apps script.
2. copy the three files from `apps_script/` into the project.
3. deploy the service somewhere the script can reach, then in the sheet use
   **narrative report, configure service** and paste the url and shared token.
4. select a range including its header row, then **narrative report, build report
   from selection**.

the add-on stays deliberately thin. it reads the selection, shows the review, and
nothing else. no numeric logic lives in apps script because it has no test runner
worth the name, and the guarantees above have to be testable.

---

## how a run works

```
selection
   |
   v
 parse ....... header row of periods, left column of line items
   |           hostile cell text neutralised here, once, at the boundary
   v
 facts ....... every number computed in python, each with its a1 provenance
   |           SUM(P&L!C3:F3), MAX(...), period over period, size bands
   v
 chart ....... rendered from the same table, inputs hashed so an
   |           unchanged chart is not re-uploaded
   v
 plan ........ diff fact hashes against the stored manifest
   |           decide per section: keep / re-substitute / rewrite
   v
 narrative ... superdocs writes prose containing only tokens
   |           falls back to deterministic prose if the model is unavailable
   v
 verify ...... substitute, then hunt for any digit that did not come from a fact
   |           prove untouched sections are byte identical
   v
 review ...... a human accepts or rejects each section, one at a time
   |
   v
 commit ...... assemble on the firm template, export .docx via superdocs
```

stages are timed and reported, so "what did it decide and what did that cost" is
answerable without reading a log.

---

## superdocs surfaces used

all four calls the task brief names as the minimum contract, plus three more.

| what | endpoint |
|---|---|
| upload | `POST /v1/documents/upload` |
| chat | `POST /v1/chat/async` |
| approve | `POST /v1/chat/{session_id}/approve` |
| export | `POST /v1/documents/export` |
| chart images | `POST /v1/documents/images/upload-base64` |
| firm template | `POST /v1/templates/upload` |
| free local save | `POST /v1/sessions/{id}/documents/{doc}/save` |

that last one is what makes a value only update cost zero operations. the
substitution happens locally and lands through the non ai autosave path, so the
model is never called for work it does not need to do.

---

## things it does that were not asked for, but a finance user needs

**a totals column is not a period.** finance selections routinely end in
`FY total`. treating it as a period makes the total the latest period and turns
every comparison into nonsense. detected two ways, by header wording and by
checking whether the column is actually the sum of the others.

**a stated total that disagrees with its own periods is reported, not fixed.**
if the sheet says the year is 8,305,000 but the quarters sum to 8,290,000, the
reviewer is told. we never silently pick one.

**a closing balance is not a sum.** headcount's `FY total` of 103 is the closing
headcount, not four quarters added up. flagging that would be a false alarm, and
false alarms are how a findings list gets ignored.

**growth from zero is not a percentage.** no `delta_pct` fact is produced, so the
narrative has to describe the move in words instead of printing infinity.

**a claim about a pattern is a claim.** the model once wrote "the fourth
consecutive period of growth". the figure was grounded and correct; the claim
that the growth ran for four periods was its own inference and nothing checked
it. grounding every number is not sufficient on its own. runs are now computed
as a `streak` fact, and words like "consecutive", "consistently" and "every
quarter" are reported when the model types them itself.

---

## honest limits

- the outline is fixed at three sections. it is data in `narrative.py`, not code,
  but there is no ui for editing it yet.
- one header row and one label column. a selection with merged cells or two
  header rows is rejected rather than guessed at, which is deliberate but does
  mean some real sheets will not parse.
- the review ui is the sidebar. rejecting a section reverts it to its previous
  text, it does not let you edit the wording inline.
- the firm template is one html file. swapping it is a content edit, but there is
  no per client template picker.
- the injection filter is a pattern list. it catches the obvious attempts and
  everything it misses is still caught by the numeric check, but the pattern list
  alone is not a security boundary.
- currency symbol is a setting, not detected per column. a sheet mixing dollars
  and euros in one row will render both with the same symbol.

---

## bugs and rough edges found in superdocs while building this

reported so the team can see them, all hit during real integration.

1. the task document warns that proposed change content arrives json encoded and
   needs a second parse. on `GET /v1/jobs/{id}` it does not, `pending_changes` is
   already a list. the warning appears to apply only to the sse event.
2. `Content-Disposition` was absent on a successful export even though the docs
   say it always carries the filename. `X-Export-Warnings` was absent too.
3. **`data-section-id` does not survive a round trip reliably.** in one document
   the same call preserved the attribute on one section and stripped it from
   another, and dropped the wrapping div entirely. anchoring on headings instead
   was the fix.
4. `approval_mode: "approve_all"` still parks a long authoring turn at
   `awaiting_approval` with `awaiting_kind: "continue_prompt"`. correct
   behaviour, but the mode name makes it look like a bug until you read the
   metadata.
5. a job left paused makes the whole session reject later instructions with
   `session_busy`. easy to strand a session if a client does not cancel on
   failure.

---

## layout

```
src/narrative_report/
  facts.py         read the range, compute every fact with provenance
  numbers.py       formatting, span tracked substitution, the integrity check
  incremental.py   the diff planner and the byte identical proof
  narrative.py     prompts, section extraction, deterministic fallback
  sanitize.py      one chokepoint for hostile cell text
  chart.py         chart rendering and input hashing
  superdocs.py     async api client, retries, error taxonomy
  pipeline.py      the run, stages, human gate
  store.py         crash safe json state
  template.py      the firm letterhead
  api.py           the http surface apps script calls
apps_script/       the sheets add-on
tests/             207 tests, no key required
scripts/demo.py    live end to end demo
```

---

built for the superdocs round 2 task by pawan.
