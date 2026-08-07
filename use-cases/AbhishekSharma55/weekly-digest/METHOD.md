# Method — cost of editing vs. regenerating a weekly digest

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

Arm A verifies every week against thirteen invariants derived from the document
bytes and, on failure, spends a second operation retrying on stronger model
settings. **Arm B gets exactly the same treatment** — the same invariants, the
same escalation, the same accounting. Giving my own build a repair budget and
not giving one to the control would rig the measurement, and this is the axis
where it would have mattered most: regenerating a whole document gets harder as
the archive it must re-emit grows, and on the default tier week 8 of arm B came
back as a 1.2 KB document containing one of the four sections. That truncation
is a real cost of regenerating, and it is counted rather than hidden.

Both arms run attempt 1 on `core`/`balanced` and escalate to `pro`/`deep`.

## What counts as a cost in arm A

Everything arm A spends, including its failures. Arm A verifies every week
against thirteen invariants derived from the document bytes and, when a week fails,
spends **a second operation** re-issuing the instruction on a reloaded copy of
the last known-good document. Those repair operations are billed by SuperDocs
and are counted in arm A's total. Reporting arm A's cost without its repairs
would be measuring a system that does not exist.

## Sample size, and the stopping rule

The account this was run on is a free agent account with **500 operations per
month** (`bugs.md` B7). The budget is therefore:

- **Arm A runs the full 52 weeks.** It is the assigned build; the brief asks for
  one document and fifty-two weeks, and it must actually be run.
- **Arm B runs a bounded prefix of weeks** — as many as the remaining budget
  allows after arm A and build #2 are funded. Its per-week cost is measured, and
  the 52-week figure for arm B is an **extrapolation**, labelled as one
  everywhere it appears, using the fitted relationship between week number and
  operations charged rather than a flat average — because arm B's cost is
  expected to grow with the archive while arm A's is not, and averaging would
  hide exactly the effect being measured.
- Both arms stop cleanly on the cap (`--max-ops`) and resume from their ledgers.

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
