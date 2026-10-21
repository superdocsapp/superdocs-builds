# Self-Healing Document Agent for Structure and Numbering

Built by Shivansh Kalra for the SuperDocs task.

Takes a document whose internal structure has drifted -- Section numbers
with a gap, a duplicate, and a run past the real count; two body
cross-references that point at the wrong Section by number; a Table of
Contents that's stale in three independent ways (a wrong number, a wrong
title, a missing entry) -- and asks the real, hosted SuperDocs product to
repair all three problem classes against a fully known, exact ground
truth (all ten Sections are already in the correct reading order, so the
correct final number for each one is just its position).

All content is synthetic: a fictional company (NorthPeak Logistics) and a
fictional driver safety manual.

Deliberately a single document, single session, with no
`cross_session_search` anywhere -- the sibling
[owner-contractor-redline-workspace](../owner-contractor-redline-workspace/)
build found that `cross_session_search` can cause SuperDocs to silently
re-open a stale snapshot of a document already open in the current
session. This build's task never needs data from another session, so it
can't hit that specific bug -- and, as it turned out, still surfaced a
different, real problem on its own.

## What it does

1. Uploads the broken manual to a session.
2. **Renumber step**: asks SuperDocs to renumber the ten Section headings
   sequentially 1-10, in the order they already appear, without touching
   titles, body text, or the Table of Contents. Wrapped in a
   verify-then-retry loop (up to 3 attempts, each from a fresh session and
   a fresh copy of the source) since this exact instruction showed real
   run-to-run non-determinism -- see [Verified result](#verified-result-fail-and-a-genuinely-interesting-one).
3. **Cross-reference step**: asks SuperDocs to find two body sentences
   that reference another Section by number and correct each number to
   match its target Section's new, corrected number.
4. **Table of Contents step**: asks SuperDocs to bring every Table of
   Contents entry's number and title in line with its Section, and add
   an entry for the one Section that has none.
5. Exports the result and verifies it programmatically against 8 checks
   by inspecting the real returned HTML -- not asserted, checked.

`verify()` was validated in both directions before any real API call:
run against the known-broken source (all 8 checks correctly `false`) and
against a hand-repaired copy built with `sed`, not the API (all 8
correctly `true`). One real bug in the verification script itself was
caught this way, for free: a case-insensitive regex boundary was matching
the Table of Contents' own first entry instead of the real heading below
it, collapsing the captured TOC region to nothing. Fixed before spending
anything.

## How to run it

```bash
python -m venv .venv
.venv/Scripts/activate    # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env      # then set SUPERDOCS_API_KEY
python build.py --dry-run # prints the full plan, zero API calls
python build.py           # runs it for real: 1 upload, 3 chat turns, 1 export
```

## SuperDocs features used

- **Chat / async edit** (`POST /v1/chat/async`) with
  `approval_mode: "ask_every_time"` across three sequential instructions
  on the same document, in the same session
- **Export** (`POST /v1/documents/export`, `.docx`)
- **Job introspection** (`GET /v1/sessions/{id}/jobs`) -- used to
  chronologically diff all three turns' own reported changes against
  what they actually claimed, which is how the real finding below was
  caught

## Verified result: FAIL, and a genuinely interesting one

Two real runs against the live API, same instructions both times.

**Run 1**: 6 of 8 checks passed. Renumbering and both cross-reference
fixes landed correctly. The Table of Contents fix was silently dropped --
the step's own response said `"Successfully updated all 2 sections"`,
meaning it had quietly narrowed a two-part instruction (fix cross-refs
*and* fix the TOC) down to just the first part while still reporting full
success. Diagnosed via the job's own response text, no extra API cost.
Fixed by splitting into two single-purpose turns instead of one bundled
one -- the same narrowing pattern already proven reliable on the
redline-workspace build.

**Run 2**, same split instructions, same document: 0 of 8 checks passed
-- and wrong in ways Run 1 never was. The renumber turn claimed
`"Successfully updated all 10 sections"` while making almost no real
progress: 9 of its 10 changes were unrequested Table-of-Contents edits
(explicitly out of scope for that step), and the one change that touched
an actual Section heading left its number unchanged and instead silently
rewrote its *title* (`TERMINATION` -> `Miscellaneous Provisions`), leaving
that heading's body paragraph as the original Termination text -- a
mismatch that didn't exist in the source. The cross-reference turn then
trusted that false claim rather than checking the real document, decided
"no edits were required," and made none. The Table of Contents turn
deleted the entire hand-authored TOC and replaced it with an empty
`<div data-toc>` placeholder -- apparently a native live-TOC feature --
leaving zero literal entries where nine had been.

The renumber instruction's text was byte-identical between the two runs.
One execution was clean; the other was wrong in three independent,
compounding ways. That's evidence of real run-to-run non-determinism in
how SuperDocs executes structural edit requests, not something this
build's instruction wording controls -- so a third run wasn't attempted:
Run 1 already proves the same instruction *can* succeed, meaning a third
attempt would be spending operations on a re-roll with no new diagnostic
basis, not a verified fix. Full turn-by-turn diagnosis, including the
exact job diffs, is in [`PROGRESS.md`](PROGRESS.md).

| Check | Run 1 | Run 2 | Run 3 (retry wrapper) |
|---|---|---|---|
| Headings renumbered 1-10 sequentially | PASS | FAIL | PASS |
| Titles unchanged and in order | PASS | FAIL | PASS |
| Confidentiality cross-ref -> Section 8 | PASS | FAIL | PASS |
| Termination cross-ref -> Section 9 | PASS | FAIL | PASS |
| TOC: stale title fixed | FAIL | FAIL | FAIL |
| TOC: stale number fixed | FAIL | FAIL | FAIL |
| TOC: missing entry added | FAIL | FAIL | FAIL |
| TOC: exactly 10 entries | FAIL | FAIL | FAIL |
| **Overall** | **FAIL (6/8)** | **FAIL (0/8)** | **FAIL (4/8)** |

### Run 3: a verify-then-retry wrapper around the one non-deterministic step

Run 1 and Run 2 used the byte-identical renumber instruction and got very
different results -- real non-determinism, not a wording problem. Run 3
wraps just that step (the only one that showed non-determinism) in a
verify-then-retry loop: each attempt starts from a fresh session and a
fresh copy of the source document, and the result gets checked against
ground truth before deciding whether to keep it or discard and try again,
up to 3 attempts. Cross-refs and TOC are unchanged, single-shot turns.

It converged on the first attempt: `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]`,
correct, no retry needed. That's a real result, not a non-event -- Run 1
already showed the instruction can succeed cleanly; Run 3 confirms it
again under the same fresh-session conditions. Every attempt's real
outcome is logged to `output/renumber_attempts.json` regardless of
whether a given run needs 1 attempt or all 3.

The Table of Contents step failed again, the same way as Run 2: no edits
to any of the nine existing TOC lines, and an empty auto-generated
`<div class="table-of-contents">` widget inserted instead. Two real runs
that reached this step, two different instruction phrasings, the same
outcome both times -- this now reads as a specific, reproducible platform
behavior around editing a literal, hand-authored Table of Contents,
not a fluke. Out of scope for this pass (the retry wrapper was scoped to
renumbering only); fixing the TOC step is separate, not-yet-scoped work.

## Honest limitations

- Single-shot structural repair (renumbering specifically) was not
  reliable run-to-run against the live API, based on two identical
  attempts producing very different outcomes. The retry wrapper (Run 3)
  mitigates this for renumbering by discarding a failed attempt and
  trying again fresh, up to 3 times -- but that's a mitigation, not proof
  the underlying non-determinism is gone; a run where all 3 attempts fail
  is still possible and would be reported honestly if it happened.
- The Table of Contents step still fails, the same way, on both real runs
  that reached it: given a literal, hand-authored TOC to edit, it replaces
  the whole thing with an empty auto-generated widget rather than editing
  the existing text -- something this build's HTML-based verification has
  no way to see through, and not yet mitigated (out of scope for the
  retry-wrapper pass).
- `output/` is gitignored; run `python build.py` to regenerate
  `repaired_manual.docx`, `final_document.html`,
  `verification_result.json` (now also carries the renumber retry log),
  and `renumber_attempts.json`.

## Files

- `build.py` -- upload -> renumber (verify-then-retry, up to 3 attempts)
  -> fix cross-refs -> fix TOC -> verify -> export flow, plus `--dry-run`
- `content/manual.html` -- the driver safety manual, authored with the
  three planted structural defects described above
- `PROGRESS.md` -- full diagnostic trace of both runs, including the
  exact job diffs behind both findings
