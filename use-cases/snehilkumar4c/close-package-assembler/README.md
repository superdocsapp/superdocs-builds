# Close-Package Assembler

A month-end close package for revenue recognition: the memo, a verified period-by-period recognition schedule, and a formal audit trail, assembled into one reviewable document and drafted through SuperDocs. Built directly on top of a companion project in this repo — [`revenue-recognition-drafter`](../revenue-recognition-drafter) — which supplies the already-analyzed, already-cited memo this project packages.

## Who this is for

A controller or assistant controller at a mid-market company running monthly close (Series B–D SaaS finance teams are the clearest fit) needs more than a memo at close time — they need a schedule showing how much revenue lands in which period, and a paper trail an outside auditor can follow later without redoing the analysis. This assembles all three into one package instead of leaving them as separate, disconnected artifacts.

## What it does

Given a contract's already-verified revenue recognition analysis (performance obligations, price allocations, timing conclusions — see the companion project for how that's produced and cited), the assembler:

1. **Extracts recognition-period facts** with Claude — for each already-established obligation, when its recognition period starts and how long it runs — given the obligations as fixed context so the model isn't re-deriving what they are, only finding their timing. Every citation is independently verified against the contract text in code, and every `obligation_id` the model uses is cross-checked against the obligations Task 2's analysis actually established — an obligation_id that doesn't match is never trusted even if its citation text happens to verify.
2. **Computes a period-by-period schedule** — pure arithmetic, zero additional model calls. An over-time obligation's allocated amount is split evenly across its verified term length; a point-in-time obligation gets one entry for its full amount. Anything that can't be computed (an unparseable dollar figure, a missing or unverified term) is flagged for human review, never silently guessed at.
3. **Builds a formal audit trail** — also zero additional model calls, purely re-shaping data the memo's analysis and the schedule extraction already verified into a flat, categorized record: what was concluded, from which exact clause, whether it was independently verified, and whether it required judgement. Written for a different reader than the memo — someone verifying *how* a conclusion was reached, later, rather than deciding whether to trust it now.
4. **Assembles the full package** — memo, schedule table, audit-trail table, three sections for three different questions, deterministically combined with zero additional model calls.
5. **Publishes the whole package through SuperDocs**, reusing the companion project's HITL flow verbatim: SuperDocs's own AI is used for formatting/polish only, and every proposed edit is independently checked in code against what actually changed, not what SuperDocs *says* it changed, before being auto-approved.

## SuperDocs features used

Same as [`revenue-recognition-drafter`](../revenue-recognition-drafter) — this project reuses its publishing layer directly:

- `POST /v1/chat/async` with `approval_mode="ask_every_time"` — human-in-the-loop review of every proposed AI edit.
- `GET /v1/jobs/{job_id}` — polling for job status and reading proposed changes.
- `POST /v1/chat/{session_id}/approve` — approving/denying individual proposed edits.
- `POST /v1/documents/export` — exporting the finished package (docx/pdf/html/markdown/txt).

## How to run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# fill in ANTHROPIC_API_KEY (required) and SUPERDOCS_API_KEY (only if using --publish)

# Build a close package locally (no SuperDocs call, no SuperDocs key needed):
python run_demo.py --contract hardware

# Build AND publish through SuperDocs (creates a real session/job on your account):
python run_demo.py --contract hardware --publish --auto-approve --format docx
```

`--contract` accepts `saas`, `milestones`, or `hardware` (three bundled fixtures with genuinely different obligation shapes — a subscription with an over-time obligation, milestone billing that's entirely point-in-time, and a hardware sale with a multi-year over-time warranty).

### Running the tests

```bash
pytest tests/ -v
```

Tests are split by what they need:
- **No live key needed**: everything except the files below — uses fake LLM/SuperDocs clients, or replays a pre-recorded Claude response from `tests/fixtures/cassettes/`.
- **Needs `ANTHROPIC_API_KEY` to *record* (already recorded and checked in)**: `test_drafter_analysis_real_model.py`, `test_close_package_schedule_real_model.py` — both replay from their committed cassettes by default.
- **Needs a real `SUPERDOCS_API_KEY` and an explicit opt-in flag** (creates real account state, not cassette-replayable): `test_superdocs_client_real_api.py`, `test_drafter_publish_real_superdocs.py`, `test_close_package_publish_real_superdocs.py`. Skipped by default. Run with:
  ```bash
  RUN_LIVE_SUPERDOCS_TEST=1 SUPERDOCS_API_KEY=sk_... pytest tests/test_close_package_publish_real_superdocs.py -v
  ```

## Architecture

```
core/               shared, reusable engine (idempotent + retried API clients,
                     structured logging with redaction, citation verification)
drafter/            the companion project's engine — this project imports it
                     directly rather than re-deriving analysis/synthesis logic
  analysis.py          calls core.llm, verifies every citation in code
  synthesize.py         deterministic memo assembly, zero new LLM calls
  publish.py             SuperDocs HITL publishing with content-verified
                          auto-approval — reused verbatim, not reimplemented
  runner.py                ties analysis -> synthesis -> publish together

close_package/      this project's own logic — imports drafter/, adds only
                     packaging/scheduling domain logic
  schedule.py          extracts + independently verifies recognition-period
                        facts, then computes the period-by-period schedule
                        via pure arithmetic (zero new LLM calls)
  audit_trail.py        deterministically reshapes already-verified data into
                         a formal audit trail (zero new LLM calls)
  assemble.py             combines memo + schedule table + audit-trail table
                          into one package document (zero new LLM calls)
  runner.py                 ties it all together, reusing drafter's HITL
                            publishing flow for the assembled package
```

`core/` is a genuinely shared engine — the same architecture also backs a standalone agentic pipeline and the companion revenue-recognition-drafter project, both built separately for the same submission round.

## A real bug this build caught, worth mentioning honestly

Testing directly against the real model and the real SuperDocs product (not just mocks) surfaced two things a mock-only test suite structurally could not have caught:

1. **A duplicate-schedule-fact edge case that was silently resolved, not flagged.** `compute_schedule_entries()`'s lookup dict was built via a comprehension that let a second verified schedule fact for the same obligation silently overwrite the first — no warning, no way to know an ambiguity had occurred. Fixed to log loudly and deterministically keep the first verified fact.
2. **SuperDocs's AI doesn't always honor a plain "don't change wording" instruction, even for a package containing tables, not just prose.** A real HITL run against the assembled package (memo + schedule table + audit-trail table) produced a proposed change that turned "--" into ":" mid-sentence, while treating it as pure formatting. Content verification — checking each proposed change's actual before/after text in code, never trusting SuperDocs's self-description — caught and correctly denied it while approving the genuinely formatting-only changes in the same batch.

---

Built by **Snehil Kumar** ([@snehilkumar4c](https://github.com/snehilkumar4c)) for SuperDocs's Round 2 Founding Engineer take-home.
