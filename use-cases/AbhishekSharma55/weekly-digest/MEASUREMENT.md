# Measurement — cost of editing vs. regenerating a weekly digest

*Written and committed before the numbers were collected. `MEASUREMENT.md` is
this file with the results appended by `digest report`; if you want to check
that the method was not reverse-engineered from the answer, `git log METHOD.md`
predates the arm-B ledger.*

## The question

A team publishes a weekly update. Over a year, is it cheaper to **edit one
standing document fifty-two times** or to **regenerate it fifty-two times**?

## The unit

**Billable SuperDocs operations**, taken from `usage.ops_charged` on each
response. Not tokens, not wall-clock, not my estimate.

Reasons for this choice, and its limits:

- It is the unit the customer is billed in, so it is the number that shows up
  on an invoice.
- It is reported by the server, not computed by me, so I cannot flatter my own
  arm by mismeasuring it.
- SuperDocs bills **one operation per document-modifying turn, and one extra
  per 25 sections changed in that turn**. So the meter is sensitive to *how
  many sections a turn touches*, which is precisely the axis the two arms
  differ on.
- **Limit:** it is insensitive to prompt length. Arm B's instruction is much
  longer than arm A's, and that costs nothing here but would cost real money if
  you drove either arm with your own model. Instruction length is therefore
  reported separately as `instruction_chars`, unweighted, so a reader can apply
  their own token price.

Wall-clock seconds and document size are recorded alongside every operation and
reported, but they are *not* the headline: they depend on model tier, server
load and my home broadband, and I ran this on one machine over a few hours.

## The two arms

Both arms consume the **same 52-week synthetic corpus**
(`data/weeks.json`, regenerable with `data/build_corpus.py`, fixed seed),
in the same order, and are asked for the **same document**: same four sections,
same table columns, same formatting brief.

| | Arm A — edit | Arm B — regenerate |
|---|---|---|
| Session | one session, all 52 weeks | a fresh session per week |
| Document | one document, edited in place | produced from scratch each week |
| Instruction | five targeted changes | the whole document restated |
| Archive | already in the document | supplied as input, re-emitted each week |

**Why arm B is given the archive as input.** A regenerating system has no
memory of last week's document. If I withheld the archive, arm B would emit a
shorter document every week and would win the comparison by producing less. It
is given exactly the information arm A's document already contains.

**Why arm B gets a fresh session each week.** Reusing one session would let the
server carry document state across turns, which is *editing*. The whole point
of the control arm is that it does not.

## Both arms are verified, and both may retry

Arm A verifies every week against fourteen invariants derived from the document
bytes and, on failure, decomposes the week into two simpler turns. **Arm B gets
the same treatment** — the same invariants, a second attempt on the same
escalation, the same accounting. Giving my own build a repair budget and not
giving one to the control would rig the measurement, and this is the axis where
it matters most: regenerating a whole document gets harder as the archive it
must re-emit grows. The per-week arm-B table in the Results section shows how
often its second attempt was needed and how often the result was still invalid;
the document sizes in that table are worth reading next to arm A's, because a
regenerated week that comes back a third of the expected size has dropped
sections rather than saved money.

Both arms run on `pro`/`deep`.

## What counts as a cost in arm A

Everything arm A spends, including its failures. Arm A verifies every week
against fourteen invariants derived from the document bytes and, when a week fails,
spends **a second operation** re-issuing the instruction on a reloaded copy of
the last known-good document. Those repair operations are billed by SuperDocs
and are counted in arm A's total. Reporting arm A's cost without its repairs
would be measuring a system that does not exist.

## Sample size, and the stopping rule — a cut, defended

The account this was run on is a free agent account with **500 operations per
month** (`bugs.md` B7), and a week on the settings that pass reliably takes
20–300 seconds of wall clock. A full 52-week arm A is therefore around 55
operations and **two to four hours** of continuous running, with arm B on top.

**So the live run is bounded by an explicit rule rather than by whenever I got
bored.** The rule, fixed before the run:

- **Arm A runs until `--max-ops` or week 20, whichever comes first**, and the
  week it actually reached is in the Results section below — generated from the
  ledger, not typed by me. If those two numbers ever disagree, believe the
  ledger.
- **Week 20 is not arbitrary.** The archive rollup fires at weeks 10, 14 and 18,
  so a 20-week run exercises the growth policy **three times** and ends with the
  archive in its steady state — detail rows plus rolled-up rows, which is the
  shape it holds for the rest of the year.
- **The 52-week behaviour is proved offline, not asserted.** The archive policy
  is simulated for all 52 weeks in
  `tests/test_transport_and_archive.py::test_fifty_two_weeks_of_archive_growth_offline`,
  feeding each week's planned rows back in as the next week's input and asserting
  that every past week is accounted for exactly once and the table never grows
  without bound. That is where a 52-week claim belongs: in a test that runs in
  milliseconds, not in an hour of API calls that proves the same property once.
- **The run is resumable, so this is a stopping point rather than a limit.**
  `make run` continues from `state.json` and the ledger; the remaining weeks cost
  roughly one operation each. Anyone who wants the full 52 can have them.
- **Arm B runs a bounded prefix** for the same reason. Its per-week cost is
  measured and any 52-week figure for it is an **extrapolation**, labelled as one
  everywhere it appears, fitted against week number rather than averaged —
  because arm B's cost is expected to grow with the archive it must re-emit while
  arm A's is not, and averaging would hide exactly the effect being measured.
- Both arms stop cleanly on `--max-ops` and resume from their ledgers.

**What this costs the result, stated plainly:** a run of this length cannot show
a slow degradation that only appears at week 40. If one exists, this measurement
would miss it. What it can show — and does — is whether the per-week cost is flat
and whether the document survives the archive growth policy firing repeatedly.

**One thing this measurement is NOT.** It is not a claim that the archive
*summaries* are correct. Every invariant on the archive is structural — coverage,
bounds, labels, no stray header row — and none of them reads the sentence the
model wrote. That gap let a real defect through for seven weeks and is written up
as `bugs.md` M7; the fix was to hand the model the text to summarise instead of
naming a place in a document the same turn was rewriting. If you want to attack
this measurement, that is still the softest part of it.

## What would falsify the claim

Stated in advance so the result is not unfalsifiable:

1. If arm A's per-week operations grow with week number the way arm B's do,
   there is no structural advantage and the whole build is a worse UI over the
   same cost.
2. If arm A needs a repair operation in a large fraction of weeks, its effective
   per-week cost approaches 2 and the gap narrows sharply.
3. If arm A's document fails its invariants by week 52, the cheaper arm is
   cheaper because it is producing a worse artefact, and cost is the wrong
   comparison entirely. This is why the drift report is part of the result and
   not an appendix.

## Raw data

Everything needed to recompute the tables is committed:

- `out/arm-a-edit/ledger.jsonl` — every call, its label, ops charged, seconds
- `out/arm-a-edit/records.json` — per-week verification results
- `out/arm-b-regenerate/ledger.jsonl`, `out/arm-b-regenerate/records.json`
- `out/arm-a-edit/html/week-NN.html` — the document after every week
- `out/arm-a-edit/md/week-NN.md` — the free Markdown export of every week
- `out/arm-a-edit/diff/week-NN.diff` — week-over-week unified diff


---

# Results

*Generated by `digest report` from the committed ledgers. Do not hand-edit; re-run the command.*


## Headline

- Arm A ran **18 weeks** (weeks 2-19), costing **22 operations** in total — **1.22 per week**, including repairs.
- Arm B ran **18 weeks** (weeks 1-18), costing **35 operations** — **1.94 per week**.
- **Like for like**, over the 17 weeks both arms ran: arm A **21 ops**, arm B **33 ops** (1.57x).
- Arm A's document passed all fourteen invariants in **18/18** weeks; **2** week(s) needed a repair operation, **0** ended rolled back.
- **Arm B's document passed in 0/18 weeks**, against the same fourteen invariants. That, not the operation count, is the result: the two arms are within a small multiple of each other on cost, and the regenerated document is not a document you could publish. Read the per-week tables before the cost tables.

## Arm A — every week, no rows omitted

| Week | ops | attempts | seconds | doc bytes | sections changed | sections byte-identical | unintended | verdict |
|---|---|---|---|---|---|---|---|---|
| 2 | 1 | 1 | 132.8 | 5403 | 5 | 6 | 0 | clean |
| 3 | 1 | 1 | 287.1 | 5557 | 5 | 6 | 0 | clean |
| 4 | 1 | 1 | 155.8 | 5983 | 5 | 6 | 0 | clean |
| 5 | 3 | 2 | 210.2 | 6773 | 5 | 6 | 0 | repaired |
| 6 | 1 | 1 | 363.1 | 7465 | 5 | 6 | 0 | clean |
| 7 | 1 | 1 | 126.6 | 8482 | 5 | 6 | 0 | clean |
| 8 | 1 | 1 | 142.9 | 8445 | 5 | 6 | 0 | clean |
| 9 | 1 | 1 | 177.2 | 10080 | 5 | 6 | 0 | clean |
| 10 | 1 | 1 | 102.6 | 8131 | 5 | 6 | 0 | clean |
| 11 | 1 | 1 | 195.0 | 8713 | 5 | 6 | 0 | clean |
| 12 | 1 | 1 | 135.2 | 9250 | 5 | 6 | 0 | clean |
| 13 | 1 | 1 | 132.4 | 9796 | 5 | 6 | 0 | clean |
| 14 | 3 | 2 | 459.1 | 8762 | 5 | 6 | 0 | repaired |
| 15 | 1 | 1 | 202.1 | 9348 | 5 | 6 | 0 | clean |
| 16 | 1 | 1 | 162.9 | 10503 | 5 | 6 | 0 | clean |
| 17 | 1 | 1 | 130.3 | 10493 | 5 | 6 | 0 | clean |
| 18 | 1 | 1 | 135.4 | 9418 | 5 | 6 | 0 | clean |
| 19 | 1 | 1 | 118.9 | 9937 | 5 | 6 | 0 | clean |

## Arm B — every week, no rows omitted

| Week | ops | attempts | seconds | doc bytes | instruction chars | verdict |
|---|---|---|---|---|---|---|
| 1 | 2 | 2 | 69.2 | 1567 | 1536 | FAILED |
| 2 | 2 | 2 | 44.4 | 4421 | 1818 | FAILED |
| 3 | 2 | 2 | 43.3 | 4106 | 2000 | FAILED |
| 4 | 2 | 2 | 81.2 | 5738 | 2122 | FAILED |
| 5 | 2 | 2 | 47.5 | 1292 | 2351 | FAILED |
| 6 | 2 | 2 | 125.3 | 5544 | 2746 | FAILED |
| 7 | 1 | 2 | 478.6 | 6478 | 3079 | FAILED |
| 8 | 2 | 2 | 87.4 | 7232 | 3109 | FAILED |
| 9 | 2 | 2 | 95.3 | 7597 | 3593 | FAILED |
| 10 | 2 | 2 | 202.2 | 8377 | 3762 | FAILED |
| 11 | 2 | 2 | 229.3 | 4844 | 4126 | FAILED |
| 12 | 2 | 2 | 154.4 | 9563 | 4334 | FAILED |
| 13 | 2 | 2 | 93.0 | 9986 | 4582 | FAILED |
| 14 | 2 | 2 | 93.9 | 9805 | 4848 | FAILED |
| 15 | 2 | 2 | 114.8 | 9488 | 5087 | FAILED |
| 16 | 2 | 2 | 63.4 | 10858 | 5295 | FAILED |
| 17 | 2 | 2 | 150.0 | 3898 | 5481 | FAILED |
| 18 | 2 | 2 | 317.2 | 16477 | 5809 | FAILED |

Arm B needed a repair operation in **18/18** weeks and ended valid in **0/18**, checked against the same fourteen invariants as arm A.

## Distribution, both arms

| | n | total ops | mean | median | min | max | sd | mean s | median s | max s |
|---|---|---|---|---|---|---|---|---|---|---|
| A - edit in place | 18 | 22 | 1.222 | 1.0 | 1 | 3 | 0.629 | 187.2 | 149.3 | 459.1 |
| B - regenerate weekly | 18 | 35 | 1.944 | 2.0 | 1 | 2 | 0.229 | 138.4 | 94.6 | 478.6 |

The max column is the tail. With this many samples a percentile beyond the maximum would be invented precision, so the full per-week series is printed above instead and you can compute whatever you like from it.

## Does cost grow with the document?

- **Arm A**: ops = -0.0083 x week +1.309 (R2 = 0.005). A slope at or near zero is the structural claim: the cost of editing one section does not depend on how many sections came before it.
- **Arm B**: ops = +0.0052 x week +1.895 (R2 = 0.014).

### Projecting to 52 weeks — and why the projection is weak

**Neither fit supports a trend** (arm A R2 0.005, arm B R2 0.014). arm A slope -0.0083, arm B slope +0.0052 — both close enough to zero, at these R2 values, to be noise rather than a direction. So extrapolating either arm along its fitted line would be inventing precision. What each arm's measured mean supports is a flat projection, and it is shown for both arms the same way or not at all.

| | measured | flat projection to 51 edited weeks |
|---|---|---|
| A - edit in place | 22 ops over 18 weeks (1.22/week) | ~62 ops (**projection**, not measured) |
| B - regenerate weekly | 35 ops over 18 weeks (1.94/week) | ~99 ops (**projection**, not measured) |

Both projection cells are that arm's measured mean times 51. Neither is a measurement. They differ by 1.59x, against 1.57x on the measured like-for-like line above (17 weeks, the ones both arms actually ran). The two multiples are close, which is the most this sample supports: the projection adds no information the measurement did not already carry, and a reader who distrusts projections loses nothing by ignoring this table.

**And a 1.59x difference in operations is not the headline.** Regenerating cost roughly half as much again per week; it also produced a document that failed verification every single week. A cost comparison between a valid artefact and an invalid one is the wrong comparison, and saying so is more useful than a bigger multiple would have been.

## Against the falsification criteria set out in the method

1. *Arm A's cost grows with week number.* Measured slope -0.0083 ops/week. Not falsified.
2. *Arm A needs frequent repairs.* Repair rate 11.1% (2/18). Not falsified.
3. *The cheaper arm is cheaper because it produced a worse artefact.* Arm A: **18/18** weeks valid. Arm B: **0/18** weeks valid. **Not falsified — and it landed the other way up.** The cheaper arm is the valid one and the dearer arm is the invalid one, so the cost comparison understates the difference rather than flattering it. See `out/arm-a-edit/drift-report.md` for arm A week by week, and the arm-B table above for the control.
