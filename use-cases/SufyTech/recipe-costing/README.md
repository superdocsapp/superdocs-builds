# Recipe Costing & Re-Cost Pass — SuperDocs Build 1

Food & Beverage use case (difficulty S2). Built by Sufiyan Khan
([@SufyTech](https://github.com/SufyTech)) for SuperDocs Round 2, Task 2.

## What this does

1. **Costs a real 5-dish bistro menu.** Every dish gets a document with
   ingredient lines (quantity, unit cost, yield/waste %), portion cost,
   sell price, gross margin against a target, and a plating note.
2. **Simulates a bulk supplier price change** (olive oil, $0.45/oz →
   $1.35/oz — a severe but realistic supply-shock scenario) and
   re-costs only the recipes that actually contain that ingredient.
3. **Produces an exceptions report**: every dish now below its own
   target margin, ranked by **dollar amount at risk per portion**, not
   percentage — with a suggested new sell price that would restore the
   target margin exactly.

## The core design decision: arithmetic never touches the LLM

Omkar's own spec for this build says _"Strong = arithmetic stays
consistent, only affected lines touched."_ That's a correctness claim
about numbers, and LLMs are not reliable calculators. So this build
splits responsibilities the same way the Task 1 submission's Ground &
Cite stage did — never trust the model for something that has to be
exactly right:

- **`recipe_costing.py`** — pure, deterministic Python. Every dollar
  figure, margin percentage, and "who's affected" decision is computed
  here, with real tests (`test_recipe_costing.py`, 12 tests) proving
  it, including a **negative-control-style identity check**: an
  unaffected recipe comes back from `apply_price_change` as the exact
  same Python object (`is`, not just `==`), the strongest possible proof
  that it was never touched.
- **`document_builder.py`** — turns those already-computed numbers into
  HTML. It never calculates anything itself; `test_document_builder.py`
  (6 tests) proves every number in the output HTML matches
  `recipe_costing.py`'s output exactly.
- **SuperDocs (`superdocs_client.py`, `run_build1.py`)** — used only for
  what it's actually good at: turning structured HTML into a formatted,
  editable document and making a **described** text edit, HITL-approved.
  The re-cost chat message hands SuperDocs the exact already-computed
  new cost/margin numbers per dish and asks it to place them — never to
  compute them. (A sync cover-intro step was tried and cut — see the
  4-calls table below.)

## The 4 required API/MCP calls

All four happen in one flow, in `run_build1.py`:

| #   | Call                                                          | Purpose                                                                                                                                                                          |
| --- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `POST /v1/documents/upload-base64`                            | Load the initial costed menu document                                                                                                                                            |
| 2   | `POST /v1/chat/async` + `POST /v1/chat/{session_id}/approve`  | Targeted, human-reviewed re-cost edit (HITL) — this is what satisfies "send an edit instruction" (see **Bug 3** below for why the plain sync `POST /v1/chat` isn't used instead) |
| 3   | `GET /v1/sessions/{id}/history` + `POST /v1/documents/export` | Verify the approved edit actually landed, then export the updated menu doc + the separate exceptions report, both as `.docx`                                                     |

## What actually happened on a real, live run

This build **has been run against the real SuperDocs API** repeatedly
(not just tested with mocks), and eight real bugs were found and fixed
along the way — most of them only surfaced by actually opening and
checking the exported files or the raw error responses, not by
trusting a call's success status. Same discipline as the rest of this
submission: a flagged bug is worth more than a hidden one.

**Bug 1 — `/approve` returning an error on a live run.** Reported to
`hello@superdocs.app` while fresh, with the exact request shape that
triggered it. `debug_history.py` (a small script that inspects a
session's raw state via `GET /v1/sessions/{id}/history`) was written to
investigate it directly against the live API rather than guessing from
docs alone.

**Bug 2 — export returning a STALE document right after approval (the
more serious one, found by actually opening the exported `.docx` and
checking it, not by trusting the API call succeeded).** The first live
export of `menu-costing-sheet-updated.docx` still showed the OLD
$0.45/oz olive oil price in all three affected dishes, and Caesar
Salad's margin showed above its target (should have been below it) —
meaning the price change genuinely never landed in that file, even
though `approve_change()` had returned success.

Root cause: calling export immediately after approval doesn't reliably
reflect the just-approved edit yet — a server-side timing issue, not
something a retry alone fixes reliably.

**The real fix, not a workaround:** `SuperDocsClient.verify_and_get_final_html()`
in `superdocs_client.py` — instead of trusting `export`'s own snapshot
of the session, it fetches the session's actual current state via
`GET /v1/sessions/{id}/history`, checks whether each approved change
genuinely landed (by looking for its `new_html` verbatim), patches it
locally if it hasn't (verbatim `old_html` → `new_html` replacement),
and **raises loudly instead of exporting** if a change can't be
verified either way. `run_build1.py`'s export step now always goes
through this verified HTML via `export_html()`, never the session's
own (possibly-stale) state via the old `export_document(session_id=...)`
path (kept only for the exceptions report, which has no approval step
before it and so isn't exposed to this race).

`test_export_staleness_fix.py` (7 tests) proves this, including a
direct regression test that reproduces the exact live scenario found
(server still returns the old price) and confirms the fix produces the
correct result anyway.

`apply_and_export.py` is kept as a standalone manual-recovery tool (not
part of the normal flow — `run_build1.py` now does this automatically)
for re-exporting a session after approval without re-running the whole
flow. An earlier version of this script had its session/job IDs
hardcoded from a specific past run, which meant a later run would
silently use stale, unrelated IDs — fixed to take them as required CLI
arguments instead.

**Bug 3 — a plain, synchronous `POST /v1/chat` call still leaves a
staged pending change behind, blocking the next call with a 409.** An
earlier version of this build called sync `/v1/chat` first (to write a
one-paragraph cover intro) before the HITL re-cost edit. On a live run
this reliably staged an AI edit that required its own approval, and the
very next `chat_async` call on the same session failed with a 409
`session_busy` — even though `/v1/chat` is documented as synchronous.
Rather than paper over this with a blind retry, the sync-chat step was
cut: "send an edit instruction" is instead satisfied entirely by
`chat_async` + `approve`, which is also the call that actually supports
this build's required HITL approval flow. This is a defended, logged
cut (per the task doc's own allowance for reasonable calls on
ambiguity), not a silent gap — and it's also a real, reportable bug in
its own right.

**Bug 4 — rejecting a previously-interrupted job via `/approve`
returns 500, and an earlier version of this README misdiagnosed why.**
Found on a real live run: `clear_stuck_jobs_for_session()`'s cleanup
path (rejecting a stuck job left over from an interrupted earlier run)
called `approve_change()` matching the documented schema
(`session_id`, `approved`, `changes`) and got back `422 Client Error:
unknown`. The first fix attempt guessed the endpoint needed an
undocumented `job_id` field and added it — that changed the error from
422 to `500 Internal Server Error` instead of resolving it, on the
same stuck job. Checking `docs.superdocs.app`'s actual OpenAPI-sourced
reference for this endpoint afterward confirmed `job_id` was never
part of its schema at all (only `approved`, `chunk_id`, `changes`,
`feedback` are documented) — the guess was wrong, and had been
sending an undocumented field that the server didn't validate but
apparently mishandled downstream (worth its own report). Reverted:
`approve_change()` calls in this build now send only the documented
fields. The underlying issue — a specific previously-stuck job
(`08846f68-0ccd-4d6f-abb2-682caa587eac`) can't be rejected via
`/approve` in any payload shape tried — is still real and still
unresolved server-side; reported to `hello@superdocs.app` with the
job ID and both payload shapes tried (with and without `job_id`).

**Bug 5 — the API reports `"in_progress"` as a busy job status, but
`wait_for_job()` only recognized `"pending"` and `"processing"` as
non-terminal.** Found on a real live run: the log showed `job
status=in_progress, 0 change(s) awaiting approval` immediately after
starting the job — meaning `wait_for_job()` returned on its very first
poll, while the edit was still running, because `"in_progress"` wasn't
in its stop-list. With zero pending changes, `run_build1.py` then
silently skipped the approval step and would have exported whatever
the session's HTML happened to be at that instant — almost certainly
the pre-edit document, presented with the same "Done" success message
as a real run. This is exactly the failure mode Bug 2 already targeted
(a success message that doesn't mean what it claims) but from a
different cause. Confirmed against `run_build1.py`'s own 409-retry
loop, which already separately polls with `status != "in_progress"` —
the inconsistency was between two pieces of this build's own code, not
a guess about the API. Fixed `wait_for_job()` to also wait through
`"in_progress"`, and added an explicit guard in `run_build1.py`: if a
job ever settles with no pending changes and isn't
`"awaiting_approval"`, the run now raises loudly instead of silently
exporting a snapshot with nothing verified against it.

**Bug 6 — a job left stuck by Bug 5 couldn't be cleared on the next
run either, matching Bug 4's pattern on a second, unrelated job ID.**
After Bug 5's fix, the very next live run hit the same 500 on
`/approve` as Bug 4, this time against
`8440a5f3-002e-4537-b883-b9bc84ea3d83` (a job that only existed because
of the Bug 5 timing issue in the first place). Manually bumping the
hardcoded `SESSION_ID` constant a second time is what surfaced this as
a pattern rather than a one-off, but doing that by hand every time it
recurs just treats the symptom. The real fix: `SESSION_ID` is now
generated fresh per run (`uuid.uuid4().hex[:8]` suffix) instead of
being a hardcoded constant, so a normal invocation of this script
structurally never has a leftover job to clean up in the first place.
`clear_stuck_jobs_for_session()` is kept as defensive code for the
case where a single run is itself interrupted and re-run against that
_same_ session, and stays covered by
`test_superdocs_client_and_orchestration.py` against a mocked 409 —
but it's no longer load-bearing for a normal run.

**Bug 7 — the documented `/approve` payload shapes are two distinct
modes, not fields to combine, and this build was combining them.**
Found on a real live run: with `job_id` correctly removed (Bug 4's
fix), a genuine 9-item batch approval on a real job still got `422
Client Error: unknown`. The payload being sent was
`{"approved": true, "changes": [...]}` — a top-level `approved` field
_and_ a `changes` array in the same request. Re-reading the docs
carefully: _"For single changes: set approved=true/false... For batch
decisions: provide a 'changes' array"_ describes two separate modes,
not a combined shape — this build's `approve_change()` always set the
top-level `approved` field regardless of whether `changes` was also
present. Fixed to send exactly one mode per call: `{"changes": [...]}`
(+ optional `feedback`) for batch, or `{"approved": ..., "chunk_id":
...}` (+ optional `feedback`) for a single decision — never both in
one request. `test_superdocs_client_and_orchestration.py` now asserts
this directly (`"approved" not in` the batch payload), so this exact
regression can't silently come back.

**Bug 8 — the AI's own approved edit updated Unit Cost correctly, but
left Line Cost, Portion cost, and Gross margin stale or inconsistent
for the same dish.** Found on a live run AFTER Bug 2's fix was already
confirmed working (all three affected dishes correctly showed the new
$1.35/oz olive oil Unit Cost) — a closer inspection, decompiling the
actual exported `.docx` cell-by-cell rather than eyeballing it, found
that the numbers _derived from_ Unit Cost hadn't reliably updated to
match in the same approved edit. `verify_and_get_final_html()` (Bug 2's
fix) was working exactly as designed — it exports precisely what was
approved. The bug is that what got approved was itself incomplete.

An earlier fix attempt tried patching this with exact byte-matching
against expected old/new HTML fragments (the same technique
`verify_and_get_final_html` uses for Unit Cost), but that proved too
fragile here — the AI's inconsistent edit meant there was no single
reliable "old" fragment to match against for the derived values.

**The real fix:** `value_patch.py` — same "arithmetic never touches
the LLM" principle as the rest of this build, applied one layer
further. Instead of trying to verify or patch the AI's specific HTML
byte-for-byte, it locates each affected dish's section purely by its
`<h2>{dish name}</h2>` marker (which comes from _our own_
`document_builder.py` template, never from anything the AI wrote) and
_forces_ that dish's Portion cost, Gross margin, and the changed
ingredient's own Line Cost to the correct value computed directly by
`recipe_costing.py` — regardless of whatever the AI's edit did or
didn't get right on its own. Raises loudly (never silently skips) if
an expected marker can't be found. `run_build1.py` now runs this
immediately after `verify_and_get_final_html`, before every export.

`test_value_patch.py` (7 tests) proves this, including a direct
regression test that reproduces the exact scenario found live (Unit
Cost correct, everything derived from it still stale) and confirms the
fix forces every derived number to the correct value — plus a
never-touches-other-dishes isolation test, matching the same
`is`-identity discipline `recipe_costing.py`'s own tests already use
for "only affected lines touched."

**Bug 9 — a corrected dish's Portion cost/Gross margin leaked into a
completely unaffected dish, found by cell-by-cell verification, not by
trusting the export log.** After Bug 8's fix was confirmed working on
a live run (all three affected dishes correctly showing updated
derived values), decompiling and checking the exported `.docx`
cell-by-cell caught something worse: **Truffle Fries**, which contains
no olive oil and should have been completely untouched by the price
change, showed the _exact same_ Portion cost ($8.30) and Gross margin
(65.4%) as Grilled Salmon, an affected dish.

Root cause: `value_patch.py`'s `_find_dish_section()` located each
dish's section boundaries with literal, byte-exact `"<div>"` and
`"<hr/>"` string matches. But SuperDocs' server adds tracking
attributes (e.g. `data-chunk-id`) to elements in a real document — the
exact reason the `<h2>` dish-name marker was already matched
attribute-tolerantly (`<h2[^>]*>`). The `<div>`/`<hr/>` boundary
matches were never given the same treatment, so on a real document a
boundary match could silently fail, and one dish's "section" would
balloon to swallow every dish after it. Combined with the Portion
cost/Gross margin `re.subn` calls having no `count` limit — unlike the
Unit Cost/Line Cost patches, which were already scoped to `count=1`,
exactly why only those two derived fields ever leaked — one dish's
correct value got stamped onto every matching line inside the
oversized section.

**Fixed two ways, deliberately redundant, same principle as the rest
of this build's fail-closed discipline:** (1) `<div>`/`<hr/>` matching
made attribute-tolerant, same treatment as `<h2>`; (2) `count=1` added
to every substitution in `value_patch.py`, so even if a boundary is
ever wrong again, a patch can never bleed into a second dish's line.
Reproduced the leak directly against the pre-fix code with a
standalone script before fixing it, confirmed the fix resolves it, and
confirmed it a second time on a real live-API export afterward.

**Bug 10 — a one-cent double-rounding mismatch between the menu
document and the exceptions report for the same dish, same
recipe object.** Caesar Salad's Portion cost showed $3.64 in the menu
document but $3.65 in the exceptions report, despite both ultimately
calling `portion_cost()` on the identical `Recipe` object.

Root cause: `rank_exceptions()` stored `portion_cost`/`current_margin`
pre-rounded to 4 decimal places before the exceptions-report display
layer rounded that already-rounded value to 2 decimals again — classic
double rounding. Caesar Salad's raw float
(`3.6449999999999996`) rounds correctly to `$3.64` when rounded
directly to 2 decimals, but to `$3.65` when rounded to 4 decimals
first and then 2 again. The menu document's Portion cost line never
went through this intermediate round, which is why it disagreed.

**Fixed by storing the raw, unrounded float in the exceptions dict and
rounding exactly once, at display time** — matching the "round exactly
once, at the point of display" discipline `document_builder.py`
already followed everywhere else. Confirmed via direct calculation
that the fix produces identical values in both documents, then
confirmed on a live run: Caesar Salad now reads $3.64 in both the menu
document and the exceptions report.

## Known gaps against the assignment's "surfaces it touches" list

The assignment names five surfaces this build should touch:
multi-document, chat, templates, review, export. Chat (via
`chat_async` + `approve`, not the plain sync endpoint — see **Bug 3**
above), review, and export are all genuinely used. Two are not, and
are logged honestly rather than left silent:

- **Multi-document (tabs)** — not currently used. The menu sheet and
  exceptions report run in two separate sessions right now, despite
  being the same workflow. SuperDocs does support this for real (a
  documented `open_mode` field), but the specific upload endpoint this
  build uses (`/v1/documents/upload-base64`) doesn't accept it per
  SuperDocs' own docs — only the multipart `/v1/documents/upload`
  endpoint does. A real fix, not yet done here.
- **Templates** — not used. Defensible given this build's core design
  (arithmetic and layout are deterministic Python, never LLM-authored),
  since SuperDocs templates are for the AI to draft new documents from.
  Noted here as an explicit, reasoned decision rather than an
  unexplained silence.

## How to run this

```bash
python -m venv venv
venv\Scripts\activate        # or: source venv/bin/activate
pip install -r requirements.txt

# Run the test suite first - should show 43 passed
pytest . -v

export SUPERDOCS_API_KEY=sk_your_real_key_here   # PowerShell: $env:SUPERDOCS_API_KEY="sk_..."

python run_build1.py
```

This produces two files: `menu-costing-sheet-updated.docx` and
`exceptions-report.docx`. An earlier version of `menu-costing-sheet-updated.docx`
in this folder was found, on inspection, to still show the stale
pre-change olive oil price — a leftover from before a code fix, not
representative of the current code. It's been removed rather than
shipped stale. Both files need to be regenerated with a fresh live run
of the current code and manually opened and checked (olive oil at
$1.35/oz across Margherita Pizza, Caesar Salad, and Grilled Salmon;
Caesar Salad appearing in the exceptions report) before either goes
into the PR.

## Files

```
recipe_costing.py        - deterministic cost/margin/exceptions math (the source of truth for every number)
sample_menu.py            - 5-dish bistro menu used to demonstrate the build
document_builder.py       - turns Recipe objects + costing results into SuperDocs-ready HTML
value_patch.py            - forces derived numbers (Line Cost, Portion cost, Gross margin) to match
                             recipe_costing.py after an AI edit, per-dish, regardless of what the AI got right
superdocs_client.py       - wrapper around the real SuperDocs REST API, including the
                             export-staleness fix (verify_and_get_final_html / export_html)
run_build1.py              - orchestrates the full upload -> chat_async -> approve -> verify ->
                             patch -> export flow
apply_and_export.py       - standalone manual-recovery tool (not part of the normal flow)
debug_history.py          - small script used to inspect a session's raw state while
                             investigating the /approve bug
tests/
  test_recipe_costing.py                     - 12 tests, the arithmetic proof
  test_document_builder.py                   - 6 tests, the "numbers match exactly" proof
  test_superdocs_client_and_orchestration.py - 11 tests, the wiring proof (mocked HTTP)
  test_export_staleness_fix.py               - 7 tests, the export-staleness bug fix proof
                                                (Bug 2), including a direct regression test
  test_value_patch.py                        - 7 tests, the derived-value staleness bug fix
                                                proof (Bug 8), including a direct regression test
requirements.txt
```
