# Revenue Recognition Memo Drafter

Turns a commercial contract into a revenue recognition memo — performance obligations, transaction price allocation, recognition timing, and areas of judgement — with every conclusion tied to the exact clause that drove it.

## What it does

Given a contract's text, the drafter:

1. **Analyzes** the contract with Claude to identify performance obligations, how the transaction price is allocated across them, and when revenue may be recognized for each — every conclusion required to carry a verbatim quote from the contract.
2. **Verifies every citation in code**, independently of the model — a quote is only accepted if it's a genuine, whitespace-normalized substring of the actual contract text. An unverifiable citation is never silently dropped; it's flagged and surfaced in the memo's own "Items Requiring Verification" section.
3. **Flags judgement calls as judgement**, not as settled fact. Determining whether something is a distinct performance obligation, or which recognition pattern applies, is treated as requiring professional accounting judgement even when the contract states its own reasoning — a contract's self-characterization is the counterparty's position, not authoritative treatment. Every judgement call carries its own reasoning, rendered in a dedicated "Areas of Judgement" section.
4. **Deterministically assembles the memo** — no additional model call, since by this point every fact has already been verified.
5. **Publishes the memo through SuperDocs**, using SuperDocs's own AI for formatting/polish only — never to re-author content. Every proposed edit from SuperDocs is independently checked in code (`change_is_formatting_only()`) against what actually changed, not what SuperDocs *says* it changed, before being auto-approved; anything that alters real text is denied automatically.

Three bundled fixture contracts (deliberately different shapes) exercise this end to end: a SaaS subscription with bundled deliverables, a professional-services agreement with milestone billing, and a hardware sale with a separately-priced extended warranty. All three produce genuinely different memos — different obligation counts, different recognition patterns, different judgement calls.

## SuperDocs features used

- `POST /v1/chat/async` with `approval_mode="ask_every_time"` — human-in-the-loop review of every proposed AI edit before it applies. Used instead of the simpler synchronous chat endpoint specifically because SuperDocs's own docs call this out as required for regulated workflows (legal, medical, compliance) — a revenue recognition memo is exactly that.
- `GET /v1/jobs/{job_id}` — polling for job status and reading proposed changes.
- `POST /v1/chat/{session_id}/approve` — approving/denying individual proposed edits.
- `POST /v1/documents/export` — exporting the finished memo (docx/pdf/html/markdown/txt).
- `POST /v1/documents/upload`, `POST /v1/chat` (sync), `POST /v1/jobs/{job_id}/cancel` — also wrapped and tested, available for other flows built on this same client.

## How to run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# fill in ANTHROPIC_API_KEY (required) and SUPERDOCS_API_KEY (only if using --publish)

# Draft a memo locally (no SuperDocs call, no SuperDocs key needed):
python run_demo.py --contract hardware

# Draft AND publish through SuperDocs (creates a real session/job on your account):
python run_demo.py --contract hardware --publish --auto-approve --format docx
```

`--contract` accepts `saas`, `milestones`, or `hardware` (the three bundled fixtures).

### Running the tests

```bash
pytest tests/ -v
```

Tests are split by what they need:
- **No live key needed**: everything except the files below — uses fake LLM/SuperDocs clients, or replays a pre-recorded Claude response from `tests/fixtures/cassettes/`.
- **Needs `ANTHROPIC_API_KEY` to *record* (already recorded and checked in)**: `test_drafter_analysis_real_model.py` — replays from its committed cassette by default.
- **Needs a real `SUPERDOCS_API_KEY` and an explicit opt-in flag** (creates real account state, not cassette-replayable): `test_superdocs_client_real_api.py`, `test_drafter_publish_real_superdocs.py`. Skipped by default. Run with:
  ```bash
  RUN_LIVE_SUPERDOCS_TEST=1 SUPERDOCS_API_KEY=sk_... pytest tests/test_superdocs_client_real_api.py tests/test_drafter_publish_real_superdocs.py -v
  ```

## Architecture

```
core/               shared, reusable engine (idempotent + retried API clients,
                     structured logging with redaction, citation verification)
  llm.py              Claude wrapper — analyze_revenue_recognition() is the
                       method this use case exercises
  superdocs_client.py  idempotent, retried wrapper around SuperDocs's REST API
  citations.py         shared quote-verification logic
  idempotency.py       Postgres-backed idempotency store
  logging.py            structured logging with automatic PII/content redaction
  config.py              fail-fast Pydantic Settings

drafter/            this use case's own logic — imports core/, adds only
                     domain-specific reasoning
  state.py              typed schema: obligations, allocations, timing,
                         judgement notes
  analysis.py            calls core.llm, verifies every citation in code
  synthesize.py           deterministic memo assembly, zero new LLM calls
  publish.py               SuperDocs HITL publishing with content-verified
                            auto-approval
  runner.py                 ties analysis -> synthesis -> publish together
```

`core/` is a genuinely shared engine, not specific to this use case — the same architecture also backs a standalone agentic pipeline built separately for the same submission round. Only `analyze_revenue_recognition()` and the SuperDocs-facing methods are exercised here.

## A real bug this build caught, worth mentioning honestly

Testing directly against the real API (not just mocks) surfaced two things a mock-only test suite structurally could not have caught:

1. **SuperDocs's AI doesn't always honor a plain "don't change wording" instruction.** A real HITL run proposed an edit that reworded a sentence ("recognition" → "Recognition timing") while its own `ai_explanation` still described the change as pure formatting. Fixed by verifying each proposed change's actual before/after text in code, never trusting the AI's self-description of what it did.
2. **`/v1/documents/export`'s real response is the raw exported file, not JSON** (`Content-Type: text/html` for HTML, the real docx MIME type for docx). An earlier version of this client called `.json()` on it unconditionally, which would have failed on every real call — invisible because `export()` had no test coverage at all until this was caught.

---

Built by **Snehil Kumar** ([@snehilkumar4c](https://github.com/snehilkumar4c)) for SuperDocs's Round 2 Founding Engineer take-home.
