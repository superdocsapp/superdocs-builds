# Build 2 — Procore/Autodesk-Construction RFI App

Built for the SuperDocs Round 2 engineer task. See task card: "Your
Second Assigned Build: Procore/Autodesk-Construction RFI app."

## What this does

Pulls project data shaped like a real Procore/Autodesk Construction
Cloud RFI (RFI number, spec section, drawing reference, question,
submission dates and parties) and drafts a formal RFI document from it.
When the architect's response arrives — a second, later event — the app
sends a targeted edit instruction, gets it reviewed and approved
(human-in-the-loop) before it lands, and exports the finished, answered
RFI as a `.docx`.

## What "strong" means for this build, per the task card

> "Reviewer supplies one fictional RFI payload with a spec section and
> a drawing reference, and the generated document carries both
> references correctly into the formal RFI format."

Both fields get their own labeled row in the document
(`document_builder.py`), and `tests/test_document_builder.py::
test_spec_section_and_drawing_reference_carry_through_verbatim` checks
this directly and by name, not incidentally.

## Assumptions logged (per the task doc: "make a reasonable call, write

it and your reasoning in your README, and keep building")

**No real Procore/Autodesk API integration.** The task doc explicitly
says: _"Where your build needs a client, a company, or data, invent
them. Fictional clients and fabricated test data are expected."_
`construction_data.py` is a fictional payload, shaped field-for-field
like Procore's real public `rfi` API resource (id, number, subject,
question, custom fields for spec section/drawing reference, assignees,
dates, status) — so swapping this module for a real OAuth-authenticated
Procore/Autodesk client later is a drop-in replacement at the data
layer, not a rewrite of the document-building or SuperDocs-orchestration
logic. A real integration was out of scope for the time available and
wasn't needed to demonstrate the actual thing being graded: whether the
generated document carries the pulled fields through correctly.

**Two events, not one.** Rather than generate a single static document,
this build models the RFI lifecycle's two real events: initial
submission (upload) and the architect's response arriving later
(a targeted chat_async edit, reviewed and approved). This mirrors
Build 1's "initial state, then one real targeted update" shape
deliberately — it's what lets the build prove data fidelity on a real
edit, not just on document generation, and it's also what actually
exercises all four required call types (upload, chat, approve, export)
honestly rather than trivially.

**Response-field patching, applied up front rather than discovered
live.** Build 1's live testing found, more than once, that SuperDocs'
AI edit doesn't reliably update every field it's asked to touch in one
instruction. Given that's now a known class of bug rather than a
one-off, `rfi_patch.py` defends against it from the start: after the
AI's edit is approved, every Response field (Status, Responded By,
Date Responded, Cost Impact, Schedule Impact, and the response text
itself) is force-patched to the known-correct value from the response
event, and the function raises loudly if any field can't be located
rather than silently leaving something stale. This is a logged,
deliberate design choice made before writing the orchestration code,
not a patch bolted on after finding a live bug the way Build 1's
value_patch.py was.

## Architecture

- `construction_data.py` — fictional Procore/Autodesk-shaped RFI data
  (pure, no network).
- `document_builder.py` — RFI object → formal RFI document HTML (pure,
  deterministic, no network).
- `rfi_patch.py` — force-patches the Response block to known-correct
  values after the AI's edit lands (pure, deterministic, no network).
- `superdocs_client.py` — reused unmodified from Build 1's final,
  live-verified version (session-per-run pattern, the `wait_for_job`
  `"in_progress"` fix, the confirmed `job_id`+`approved` always-required
  `/approve` payload shape, the batch-approve `change_id` fix with
  per-item fallback, the export-staleness fix, and the ambiguous-match
  fail-closed guard). These are confirmed facts about the live API from
  Build 1's testing, not assumptions to re-derive per build.
- `run_build2.py` — orchestrates the 4 required calls in order: upload
  → chat_async (targeted response edit) → approve (HITL) → export,
  with the same fail-closed guards as Build 1 (never export on an
  unverified job state, never proceed past an unverified upload).

## What's verified vs. what needs a live run

**Verified offline, no live key, 14/14 tests passing:** every "must
never" guarantee of `document_builder.py` and `rfi_patch.py` — data
fidelity for the spec section/drawing reference (the build's explicit
strong bar), no fabricated response text on an open RFI, the defensive
Response-field patching working correctly against simulated stale-field
scenarios (both in the Response block and, separately, in the header
table's own Status cell — see Bug 4 below) — plus a full orchestration
test (`test_run_build2_orchestration.py`) that mocks every HTTP call
and proves `run_build2.py` calls upload → chat_async → approve →
history → export in the right order, with the right payload shapes,
and that the exported HTML carries both the strong-bar fields and the
correctly patched response fields through to the final export.

**Confirmed live, including a re-run after the Bug 4 fix:** a full live
run against the real SuperDocs API produced a clean
`rfi-0142-answered.docx`. Manually reading that first export
field-by-field (not just trusting the "Done" message) surfaced Bug 4
below, which the automated checks at the time didn't catch. After
fixing it, the build was re-run live a second time; the current
`rfi-0142-answered.docx` in this folder is from that re-run, and its
header table's Status cell reads "Answered," matching the Response
block — confirming the fix holds on a real export, not just in tests.
See the screenshot below.

## Bugs found and fixed, logged honestly

1. **Serialization mismatch.** SuperDocs self-closes `<br>` → `<br/>`
   and escapes `&` → `&amp;` on storage, so a genuinely-landed AI edit
   was failing verification on formatting differences alone. Fixed
   with a normalization helper used before every landed/pending
   comparison.
2. **Wrong structural assumption.** Early code assumed a `<table>`
   layout for the Response block that was never actually checked
   against a real document; the real layout is a single `<p>` with
   inline fields.
3. **AI output isn't deterministic.** A second live run produced a
   `<ul><li>` list for the identical instruction, not the `<p>` from
   run 1. Fixed by no longer parsing the AI's wording at all —
   `rfi_patch.py` replaces the whole tagged element, by `chunk_id`,
   whatever tag the AI used, with a block built deterministically from
   known-correct values.
4. **Stale header Status cell.** `document_builder.py`'s header table
   writes `rfi.status` once at initial upload; nothing ever revisits
   it. The Response block correctly says "Answered" after the patch,
   but the header a few lines above kept saying "Open" — an
   internally-contradictory exported document a reviewer could catch
   by eye. Caught by manually reading a live export, not by the test
   suite: an older test had guarded against exactly this scenario but
   used a signature that predated the `chunk_id` redesign and had
   silently stopped running. `rfi_patch.py` now patches the header
   cell too, and the regression test
   (`test_patch_response_fields_fixes_a_stale_header_status_cell`)
   reproduces the exact failure mode: header still "Open" while the
   Response block is already correct.
5. **Latent `NameError` in a retry path.** While removing debug
   output, found a debug block inside `wait_for_upload_to_settle`
   that referenced `chunk_id`, `old_html`, `new_html` — none of which
   are parameters of that function; it had been copy-pasted from a
   different method. If the retry loop had ever actually needed a
   second iteration (the exact slow-upload race that function exists
   to guard against), it would have crashed with an unrelated
   `NameError` instead of retrying and eventually raising the intended,
   clear `RuntimeError`. Removed rather than patched, since it never
   belonged in that function.
6. **Missing `.env` loading.** The project ships a `.env` file with
   `SUPERDOCS_API_KEY`, and the README's own run instructions assume
   it's picked up automatically — but `run_build2.py` never called
   `load_dotenv()`, so the key was silently never read from the file
   at all; only an explicit shell-level environment variable worked.
   The documented setup path looked correct and simply didn't function.
   Fixed by adding `python-dotenv` to `requirements.txt` and calling
   `load_dotenv()` at the top of `run_build2.py`, before anything reads
   the key. This is an environment/setup fix, not an application-logic
   change, so it isn't covered by a dedicated unit test — the 14/14
   test count above reflects application-logic coverage only.

## How to run this

```bash
pip install -r requirements.txt
pytest tests/ -v          # offline, no key needed, 14/14 passing
export SUPERDOCS_API_KEY=sk_your_real_key_here
python run_build2.py      # live run, produces rfi-0142-answered.docx
```

## Formats and domains this build accepts

Per the task doc's instruction to declare this: this build accepts one
RFI shape (the fields Procore/Autodesk expose for an RFI resource:
number, spec section, drawing reference, question, submission/response
metadata, cost/schedule impact) and drives it through exactly the
lifecycle modeled in `construction_data.py`. A second run with a
different fictional RFI (different spec section, drawing reference,
question, and response) is a straightforward substitution in
`construction_data.py` and requires no changes to `document_builder.py`,
`rfi_patch.py`, or `run_build2.py` — those are all generic over any RFI
matching the `RFI` dataclass shape.

## Scope note

This build implements the RFI path of the assigned card in full,
matching the card's own "what strong looks like" bar exactly. The
card's "what to build" text also names submittals and change orders;
those aren't implemented here — logging that honestly rather than
implying broader coverage than what's actually built and tested.

---

Built by Sufiyan Khan ([@SufyTech](https://github.com/SufyTech)) for
the SuperDocs Round 2 engineer task.

**Screenshots:** see `rfi-0142-answered-status-field.png` — header
table's Status field reading "Answered," confirming the Bug 4 fix held
on a live, re-exported document. A second screenshot,
`rfi-0142-answered-response-block.png`, shows the Response section's
own Status field ("Answered") alongside the full architect response,
so the header and Response block can be seen agreeing with each other
— the exact contradiction Bug 4 fixed.
