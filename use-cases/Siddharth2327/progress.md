# Progress Log

Format: `[STAGE] what happened — decisions/assumptions made, in the moment they were made.`
This file is append-only in spirit; entries are not rewritten after the fact.

---

### Entry 1 — Research
- Fetched `docs.superdocs.app` overview + `llms-full.txt` + the HITL guide directly.
  Confirmed `superdocs.app` (this task's product) is **not** the same project as the
  similarly-named open-source `superdoc.dev` DOCX editor library that dominates a
  plain web search for "SuperDoc" — the docs page itself has a note warning about
  this confusion. Used only `docs.superdocs.app` as source of truth from here on.
- Confirmed the "minimum contract" (upload, chat, approve, export) plus the specific
  endpoints needed for multi-document, search, memory, and review, per the card's
  "Surfaces it touches" line.
- **Assumption logged:** the user has no live `SUPERDOCS_API_KEY` yet ("build against
  mocked/documented API contracts, add key later" — confirmed via clarifying question
  before starting). This shapes everything: real API calls are never made by this
  agent; the client is built strictly to the documented contract and tested against
  fixtures derived from that documentation, not against a live server.

### Entry 2 — Architecture & task breakdown
- Wrote `architecture.md` before any code, per the user's explicit instruction.
- Decision: REST over MCP for our own implementation (architecture.md §2)  — testable
  without a live MCP transport, and building our own MCP server on top would itself
  be the kind of overbuild the assignment explicitly warns against.
- Decision: push counting/matching out of the LLM and into deterministic Python
  wherever possible (index aggregation, small-sample flags, redaction scan, evidence
  quote matching) — this is the direct implementation of "grounded, not fabricated"
  and "verifiably stripped," not just a prompt asking the AI to be careful.
- Wrote `task.md` with an explicit "out of scope" section, so scope decisions are
  visible up front rather than justified after the fact if something gets cut.

### Entry 3 — Core client, templates, schema, verification, redaction, index
- Built `client.py` strictly against the documented request/response shapes for
  every endpoint in architecture.md §3 (upload, attachments, chat/chat_async,
  approve, sessions.init, documents, export), including the documented HITL footgun
  (top-level `approved` required even for batch approve calls) and retry/backoff
  honoring `Retry-After` on 429.
- Built `templates.py` as the single source of truth for both document schemas, so
  `schema.py`'s comparability check and the actual generation prompt can never
  drift apart (both import the same `REQUIRED_*_SECTIONS` / `*_SECTION_HEADINGS`
  constants).
- Built `verification.py` (evidence quote fuzzy-match, synthesis number cross-check)
  and `redaction.py` (structural non-exposure + post-hoc scan) as pure, dependency-
  light modules — no LLM involved in either, per architecture.md §4/§5.
- Built `index.py` as a single JSON file, not a database, per the assignment's own
  "do not build unnecessary databases."

### Entry 4 — Orchestration, CLI, tests
- Built `review.py`, `debrief.py`, `synthesis.py`, `cli.py`.
- Wrote 76 unit tests across 9 files, all mocked (no network): client (HTTP shapes
  + error codes + retry + budget), schema, verification (incl. fabricated-quote
  detection), redaction (incl. adversarial customer-name-smuggled-into-a-quote
  case), index (aggregation + small-sample thresholding + idempotent upsert),
  review (all 5 HITL branches: happy path, single approval, deny-with-feedback,
  failed job, continue_prompt refusal, multi-round), templates, debrief
  orchestration (incl. injection-attempt fixture proving outcome isn't derived from
  transcript text), synthesis orchestration (incl. redaction gate blocking export,
  and the empty-quarter honest-no-findings path).
- **First full test run: 73/73 passed, no failures to debug.** This is worth
  stating plainly rather than implying a struggle that didn't happen — it's a
  result of writing schema.py/templates.py's constants to be shared before writing
  either the generator prompts or the checks against them, so they couldn't drift
  apart during development.
- Found one real gap while writing the demo script: `redact-check` on a `.docx`
  file would have decoded raw zip bytes as text and silently produced a
  meaningless (likely false "clean") result. Added `extract_text_from_file()`
  (docx via its `word/document.xml`, plain text formats as-is, clear error
  otherwise) plus 3 new tests. Re-ran full suite: 76 passed, 1 skipped
  (integration, no key). This is exactly the kind of thing `--dry-run`/demo
  rehearsal is supposed to surface before a real demo recording does.

### Entry 5 — Fixtures, demo, docs, final validation
- Wrote 6 synthetic fictional transcripts across two quarters (2025Q4 x5, 2026Q1
  x1), covering: a clean win, a clean loss to a capability gap, a win with no
  competitor mentioned, a loss to a small-sample/rare competitor, a same-competitor
  win in a later quarter (for cross-quarter comparability), and one deliberate
  prompt-injection attempt transcript.
- Ran the CLI's `--dry-run` path for real (not just under pytest) for both
  commands, with zero credentials set, confirming: (a) no network call is attempted,
  (b) the debrief instruction correctly embeds the fixed deal record and forbids
  transcript-as-instructions, (c) the synthesis instruction's ground-truth counts
  and small-sample flags come out correct against a hand-seeded 3-record index, and
  (d) no customer name appears anywhere in the synthesis instruction text. Output
  captured in this repo's README "Try it with zero credentials" section reflects a
  real run, not a hypothetical one. The seeded demo index was deleted afterward so
  the shipped repo starts with an empty index, not fabricated "real" data.
- Wrote README.md with the full requirement checklist, mapping every card
  requirement to its implementation, its test, and how to demonstrate it.
- **Final validation pass against the assignment card** (re-read line by line):
  - Standard template, comparable fields — met (`schema.py` enforced).
  - Quarterly synthesis with competitor/segment patterns, wording that worked,
    capability-gap losses — met.
  - Every claim linked to supporting debriefs — met via deal-code citation
    requirement + deterministic number cross-check.
  - Small-sample labelling — met, deterministic, not AI-counted.
  - Customer identity verifiably stripped — met via two independent layers
    (structural non-exposure + blocking post-hoc scan), both unit-tested including
    an adversarial case.
  - Surfaces touched (multi-document, search, chat, memory, Review, export) — all
    six genuinely exercised, not just nominally referenced.
  - Minimum four-call contract (upload, chat, approve, export) — met and exceeded
    (attachments, sessions, documents-list also used where they earn their keep).
  - "Do not overbuild" — held to: no database beyond a JSON file, no web server, no
    frontend, no MCP server of our own, no Task-1 agentic machinery pulled in.
- **What is NOT verified:** the actual live SuperDocs API call/response shapes,
  because no `SUPERDOCS_API_KEY` was available during this build (confirmed via
  clarifying question at the start of the session). The client is written strictly
  from the documented contract at docs.superdocs.app (fetched directly, twice, for
  the overview/endpoint list and the full HITL guide) and is architecturally
  designed to fail loudly and specifically (`SuperDocsAPIError`, clear messages) if
  reality diverges from the docs — but "designed to fail clearly if wrong" is not
  the same claim as "confirmed correct." This is stated here and in README/
  architecture.md rather than glossed over.

### Entry 6 — Real-run bug: fabricated debrief, root cause and fix

A real live run (`bash scripts/demo.sh` against a genuine API key) surfaced a
serious grounding failure. What looked at first like a competitor-naming
inconsistency ("Comp" vs "Comp Corp" in the quarterly brief) turned out, on direct
inspection of the actual exported `.docx` files the user uploaded, to be a symptom
of something much worse: `DEAL-2025Q4-001.docx` contained a fully fabricated
debrief — plausible prose, correct schema, well-formed evidence quotes — none of
it grounded in the real transcript. `DEAL-2025Q4-002.docx`, generated moments
later in the same run, was completely correct and verbatim-grounded. This
asymmetry, plus SuperDocs' own documented behavior ("the first request in a fresh
session can be slow or fail while things warm up" and "if something goes wrong,
the AI automatically tries alternative approaches"), pointed at the real bug:
`create_debrief()` called `wait_for_attachment()` and **discarded its return value
without checking status**, so a debrief could be (and was) generated from a chat
call with no confirmed source material behind it.

Fix implemented in `debrief.py`:
- New `AttachmentProcessingFailed` exception, raised immediately if
  `wait_for_attachment()`'s returned status is anything other than the literal
  string `"completed"` — not just on `"failed"`, on *any* other value including
  unrecognized/future/malformed ones. This is a hard stop: `chat_async` is
  structurally unreachable in the failure path (verified by
  `client.chat_async.assert_not_called()` in tests, not just by an exception being
  raised somewhere).
- `templates.py`: added an explicit "do not fabricate if source content is
  unavailable" clause to the debrief prompt, documented in-line as a **secondary**
  safety net, not the primary defense — the primary defense is the hard stop above,
  which runs before any chat call is made at all.
- Logging added throughout `create_debrief()` (attachment status, evidence
  verification counts, and an explicit pre-export check of whether
  "Verification Notes" text is present in the HTML about to be exported) so the
  next real-run anomaly is diagnosable from logs alone rather than requiring
  another round of downloaded-docx forensics.

**What this fix does and does not explain:** it closes the confirmed root cause —
a debrief could previously be generated without confirmed source material, and now
structurally cannot be. It does **not** yet explain a second, smaller anomaly:
`verify_evidence_quotes()`, tested directly against the real transcript and the
real (approximated-from-docx-text) fabricated quotes, correctly flagged all 5 as
unverified — yet the exported `.docx` had no "Verification Notes" section. Given
`_append_verification_notes()` is deterministic, dependency-free Python (it always
includes the literal substring "Verification Notes" whenever its input list is
non-empty), this branch is not reachable from a bug in that function itself. The
most likely explanation is that the real HTML SuperDocs returned split that
fabricated content into several *shorter* blockquote fragments than the single
long one this agent approximated from the flattened docx text, and shorter
fragments are more exploitable by the fuzzy-match's sliding-window ratio check —
a real, separate weakness in `verification.py`, not yet fixed, tracked below. The
new logging will confirm this precisely (or rule it out) on the next real run: if
`evidence verification: ... unverified=0` appears in the logs for a debrief that
is later found to be fabricated, that confirms the fuzzy matcher is the gap, not
the append/export path.

`verify_synthesis_numbers`'s header-row/substring-matching bug (identified in
Entry 5's predecessor analysis, before the docx inspection revised the root-cause
understanding) is **still real and still unfixed** — deliberately deferred per
explicit instruction, to validate the attachment-processing fix on its own before
introducing a second code change. Tracked as follow-up work, not forgotten.

**Test results after this fix:** 89 passed, 1 skipped (integration, no key set in
this environment) — up from 76 passed. 13 new tests: 5 covering the hard stop
(explicit `"failed"`, 6 parametrized "any non-completed status" cases collapsed
into one test, chat_async-not-called, happy-path-still-works, and error-message
diagnostic-content), 3 covering the new logging (evidence summary, notes-appended
confirmation, attachment-status-before-hard-stop). No existing test needed to
change to accommodate this fix — `make_fake_client()`'s existing default of
`{"status": "completed"}` already matched the new, stricter check, so the fix is
backward-compatible with every previously-passing scenario.

**Explicitly not done, per instruction:** `verify_synthesis_numbers` was not
touched. The live debrief was not regenerated. Both are follow-up steps for the
user to run once this fix is reviewed.

## Final status: PARTIALLY COMPLETE (updated after live-run bugfix)

Every requirement in the Task 2 card has a working, tested implementation. A live
run against the real API surfaced a genuine grounding bug (Entry 6), which has
been root-caused from actual exported documents (not inferred from logs or index
state) and fixed with a hard stop plus 13 new regression tests, all passing (89
total, 1 skipped without a key). Two items remain open, tracked explicitly rather
than silently: (1) `verify_synthesis_numbers`'s header-row/substring bug, deferred
by instruction pending validation of this fix in isolation; (2) the exact mechanism
behind the missing "Verification Notes" section on the fabricated debrief is
narrowed to a likely cause (short-fragment fuzzy-match weakness) but not yet
confirmed — the new logging will confirm or rule this out on the next real run.
Nothing here is being claimed as fixed beyond what's actually been verified by a
passing test or a direct file inspection.
