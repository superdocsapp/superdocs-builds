# CLAUDE.md — how to work with me on this repo

Auto-loaded by Claude Code every session. Keep current.

## What we're building

SuperDocs Round 2, Task 2 assigned build: Collective agreement redliner.
Full context: `README.md` (architecture + why), `docs/superdocs-api-reference.md`
(the real API shapes — treat this as ground truth over anything you'd
otherwise assume about the API), `docs/brief-task2-excerpt.md` (the relevant
brief text).

## Ground rules

1. **SuperDocs owns the document and the diff. We own the domain layer.**
   Don't build change-tracking that duplicates what `GET
   /v1/sessions/{id}/jobs` already gives us — reconcile against it, don't
   re-derive it. If you're about to persist something SuperDocs already
   tracks, stop and check the API reference first.
2. **The open-items tracker staying accurate across many rounds is the
   one thing this card is graded on** ("what strong looks like" per the
   assignment card). Every other feature is secondary to that being
   genuinely, testably correct.
3. **Mock the SuperDocs client in tests, don't hit the live API by default.**
   Same discipline as Task 1: tests must pass with zero API calls. One
   `@pytest.mark.live` test per major flow is fine, guarded the same way
   Task 1's `DOCTASK_LIVE_MODEL_CALLS` was — use `REDLINER_LIVE_CALLS=1`.
4. **The JSON-string-inside-JSON quirk is real** — the brief and the API
   reference both warn about it. Build `superdocs_client.py` to always
   double-parse `pending_changes` content; don't discover this the hard way.
5. **Log every assumption in PROGRESS.md as you make it.** Same as Task 1.
6. **Small, verifiable commits. One stub, one scope, one session.**

## Code style

Same as Task 1: short single-line comments explaining *why*, not what.
Docstrings on modules/public functions are fine. No comment blocks.

## Time budget — read this before starting any session

This build has roughly 2 days total, not 9. If a session is sprawling past
its stated scope, stop and flag it rather than pushing through — a modest,
correct build beats an ambitious, half-finished one, per the brief's own
grading language. When in doubt, cut breadth before cutting the tracker's
correctness.

## Current phase

See PROGRESS.md.

## Do not

- Do not build a self-hosted MCP server for this — out of scope for this
  card, REST is sufficient and faster to ship.
- Do not add real union/employer contract data — synthetic only, per the
  brief ("invent them... real third-party data is not welcome").
- Do not commit the SuperDocs API key. `.env` is gitignored.
