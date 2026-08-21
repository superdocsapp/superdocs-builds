# Table fidelity benchmark

Measures whether merged cells, nested tables, spanning headers and numeric
formatting survive an edit-and-export cycle on SuperDocs — and, when they do
not, says *which stage* lost them.

Built for the SuperDocs Round 2 task (assigned build: table fidelity
benchmark, band S2, surfaces: API + export).

> Built by Siddharth Muneshwar for the SuperDocs task.

## Run it

```bash
git clone <this repo> && cd table-fidelity-benchmark
make install
make dry            # full run, entirely offline, spends nothing
```

That is the whole setup. `make dry` generates the corpus, runs every case
through an offline round-trip, and writes `results/report.md`. No API key, no
network, no operations.

Against the live API:

```bash
export SUPERDOCS_API_KEY=...        # leading space keeps it out of shell history
make live                           # 20 operations, capped at 25
```

The key is read from the environment only. It is never a command-line
argument, never logged, never written to a result file, and a test asserts
that no key-shaped string reaches any output.

## What it measures

Twenty cases across four declared axes:

| axis | cases | examples |
|---|---|---|
| merged cells | 7 | L-shaped merges, full-width dividers, a nested table inside a merged cell |
| nested tables | 3 | one level, two levels, two nested tables side by side |
| spanning headers | 4 | two- and three-tier headers, `w:tblHeader` repeat flags, rotated header cells |
| numeric formatting | 6 | `(12,400.00)`, `1.230`, `0007`, `3.2×10⁻⁶`, `$1,204,880.00`, mixed date formats |

Cases are data, in `tablebench/corpus/cases.py`. Adding a pathology is a new
entry there and touches no other file.

## Method

Each case runs twice.

```
control   upload → export                       0 operations
edit      upload → chat → approve → export      1 operation
```

The control is the point. Any difference the control also shows is a property
of ingest and export; only what the edit run adds on top is caused by the
edit. Without that separation a benchmark can report that a table broke but
not where, which is not actionable for anyone.

Each case names the cells its instruction legitimately changes — usually one,
sometimes two where the instruction asks for two figures. Those are exempt from
content comparison. Every other cell, every span, every shading value, every
column width and all the prose around the table are invariants — if they move,
that is a finding. A run that changes nothing scores no better than one that
mangles the document: the report carries both `edit_applied` and the findings,
and a case passes only when the edit landed *and* nothing else moved.

Comparison happens between two canonical grid models, never between two files
directly. Both the DOCX extractor and the HTML extractor produce that model,
so the HTML intermediate is compared as its own stage.

Spans are resolved from raw `gridSpan` / `vMerge` rather than through
python-docx's table API, which repeats merged cells instead of reporting
spans — precisely the thing under test.

Borders are compared as **drawn edges, not cell declarations**. The same rule
can be declared on the table element or on each cell, and as one cell's bottom
or the next cell's top; all three render identically. Comparing declarations
reports a re-expression as damage. On the first live run that difference was
35 false findings against 3 real ones — the noise was louder than the signal.
The comparator now folds table-level borders into each cell by position, then
compares the resolved edge grid.

## Budget

**Declared cap for a full live run: 25 operations.** A full run is 20 cases at
one chat turn each; the remaining 5 are headroom for a retry. Uploads,
approvals and exports are free per the published pricing, and the cost table
lives in one place (`OP_COST` in `client.py`).

The cap is enforced *before* each spend, not after — the run stops with the
budget intact rather than discovering it overspent. Small-sample mode is the
default way to work:

```bash
make sample                                  # first 3 cases
python -m tablebench.run --mode live --axis numeric_formatting --max-ops 6
python -m tablebench.run --mode live --cases merge_l_shaped --max-ops 1
```

State is written after every case, atomically. Every record carries the mode
it was produced in, and `--resume` only skips a case already recorded **in the
same mode** — a dry-run record is a simulation and is not evidence about the
live API, so it never stands in for one. Simulated operations do not count
against a live budget either. If a results directory ever ends up holding
both, the report says `MIXED` at the top and refuses to present them as one
run.

`--resume` skips work already done, so a crash or a kill costs nothing already
paid for:

```bash
python -m tablebench.run --mode live --max-ops 25 --out results --resume
```

Actual spend is printed at the end of every run and reported at the top of
`results/report.md` alongside the results.

## Tests

```bash
python -m pytest tests/ -q     # 26 tests, no API key, no network, no operations
```

The tests do not assert that the fake returns what it was handed. The offline
round-trip is verified lossless first — 0 findings across all 20 cases — and
then each fault with known ground truth (`flatten_merges`, `drop_nested`,
`strip_trailing_zero`, `drop_shading`, `rewrite_body`) is injected and the
comparator is checked for detecting it in every case that contains the
pathology and in none that does not. If the control ever drifts, every
detection result becomes unattributable, so that test is the load-bearing one.

You can watch a fault land:

```bash
python -m tablebench.run --mode dry --fault flatten_merges --axis merged_cells
```

## Capturing evidence for a bug report

```
python -m tablebench.capture --case merge_l_shaped --out evidence
python -m tablebench.capture --case header_repeat_flag --out evidence --control-only
```

Writes the source file, the HTML the upload endpoint returned, the exported
file, and a stage-by-stage list of every difference. `--control-only` sends no
edit and spends no operations, which is what shows a loss belongs to the
round-trip rather than the model.

The ingest HTML is the useful artifact: for the merge bugs the `rowspan`
attribute is already absent there, before any edit is requested, which locates
the fault in the parser rather than leaving a maintainer to find it.

## Assumptions logged while building

- **One chat turn is one operation; upload, approve and export are free.**
  From the published pricing. If it changes, `OP_COST` is the single edit.
- **The comparison of record is the exported DOCX**, not the HTML
  intermediate. Attributes plain HTML cannot express — `tblHeader`, column
  widths, `textDirection`, per-cell borders — are withheld at the HTML stage
  and listed as *not measurable* rather than counted as losses.
- **Approve-all, not approve-selectively.** The card is about fidelity, not
  about the review UI, so every proposed change is approved. Partial approval
  is a natural extension and is not built.
- **Whitespace is normalised, unicode is not.** An em dash becoming a hyphen,
  or a non-breaking space becoming a space, is a finding. Trailing spaces are
  not.
- **A long silence is a timeout, not a failure.** The docs note that large
  documents can run for minutes with no visible progress, so the client polls
  to a deadline and reports a timeout as exactly that.

## What this does not measure

- **Rendering.** Two files that parse identically could still paginate
  differently. Out of scope, and stated rather than implied.
- **Whether the edit was *correct*** — only whether it landed in the target
  cell and nothing else moved. Judging the model's wording is a different
  benchmark.
- **Two false-positive bugs found by capturing real evidence.** Alignment was
  read only from the cell, while the API puts it on the paragraph inside, so
  centred headings were reported as lost when they had survived correctly. And
  `header_rows` was withheld at the HTML stage as unrepresentable, when the API
  in fact returns a real `<thead>` -- withholding it hid the useful finding that
  the header marking survives ingest and is lost on export. Both were reporting
  against output that was right.
- **A third confusion between "unmeasurable" and "fine".** The capture summary
  reported `text_direction` as surviving ingest when the HTML stage had merely
  withheld it -- plain HTML has no property for rotation, so nothing was
  measured either way. It now reports withheld codes separately and says they
  locate nothing. The same mistake in different clothes each time: silence
  read as a pass.
- **The fault injector is coarse.** `drop_nested` is a regex and surfaces as
  `table_count` rather than `nested_table_count`. The fault is detected in
  every nesting case, but the code it reports is less precise than the
  comparator is capable of. Real API output is parsed properly; this affects
  the test harness only.
- **Corpus realism.** These are synthetic fixtures built to be pathological.
  They cover the constructs real documents contain, not the mess real
  documents are.

All figures, companies and part numbers in the corpus are fabricated.

---

Built by Siddharth for the SuperDocs Round 2 task.
