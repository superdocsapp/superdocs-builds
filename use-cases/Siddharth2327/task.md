# Task Breakdown — Win-Loss Debrief & Quarterly Competitive Brief

Checked items are done. This file is updated as work proceeds; see `progress.md` for
the running log of what happened and why.

## Phase 0 — Research (must finish before coding)
- [x] Read the full Task 2 assignment card + global engineering task doc
- [x] Identify Task 2 is standalone (not Task 1's agentic-system requirements)
- [x] Research SuperDocs docs at docs.superdocs.app (llms-full.txt) — confirm it is a
      *different* product from the unrelated open-source `superdoc.dev` editor
- [x] Identify the real REST endpoints: upload, attachments, chat, chat/async,
      approve, export, sessions.init, documents list/get, cross-session flags
- [x] Read the HITL guide in full (approve request shape, `awaiting_kind`, batch vs
      single, polling loop) — this is the trickiest part of the contract to get wrong
- [x] Write `architecture.md`

## Phase 1 — Project scaffold
- [x] `task.md` (this file)
- [x] `progress.md`
- [x] Directory structure (`src/`, `tests/unit`, `tests/integration`, `data/`,
      `outputs/`, `scripts/`)
- [x] `.env.example`, `.gitignore`, `requirements.txt`, `README.md` skeleton

## Phase 2 — Core client
- [x] `config.py` — env loading, key presence check with a **clear failure**, base
      URL, operation budget config
- [x] `client.py` — `SuperDocsClient`: `upload_attachment`, `attachment_status`,
      `chat`, `chat_async`, `get_job`, `approve_change`, `export`, `sessions_init`,
      `list_documents`, `get_document`; retry/backoff honoring `Retry-After`; usage
      tracking + `OperationBudgetExceeded`
- [x] Unit tests for `client.py` against mocked HTTP fixtures (success, 401, 413, 429,
      `awaiting_approval` → `approve` → `completed`)

## Phase 3 — Templates & schema
- [x] `templates.py` — debrief prompt/template builder, quarterly-brief
      prompt/template builder (fixed field list, matches the card's required fields)
- [x] `schema.py` — required-section presence check for both document types
- [x] Unit tests: schema pass/fail on synthetic HTML fixtures

## Phase 4 — Grounding & redaction
- [x] `verification.py` — evidence-quote fuzzy match against source transcript;
      synthesis-number cross-check against the local index
- [x] `redaction.py` — customer-identity scan + `[CUSTOMER]`-substitution helper for
      building the synthesis prompt context
- [x] Unit tests, including the adversarial "customer name smuggled into a quote"
      leak case, and a case where an evidence quote is fabricated (must be flagged)

## Phase 5 — Local index
- [x] `index.py` — parse a debrief's structured HTML table into a record; append/
      upsert into `data/index/debriefs.json`; aggregate counts per competitor/segment
      for a given quarter; small-sample flagging; simple search (`by_competitor`,
      `by_segment`, `by_outcome`)
- [x] Unit tests: aggregation correctness, small-sample threshold behavior, idempotent
      upsert (re-indexing the same debrief doesn't duplicate)

## Phase 6 — Review (HITL) orchestration
- [x] `review.py` — poll a `chat_async` job; on `awaiting_approval` with
      `awaiting_kind` != `continue_prompt`, print each proposed change and either
      auto-approve (`--auto-approve` / non-interactive demo mode) or prompt the
      operator y/n/feedback; handle `continue_prompt` separately; loop until
      `completed`/`failed`/`cancelled`
- [x] Unit tests against mocked poll sequences (single change, batch, deny-with-
      feedback → second round, `continue_prompt` branch)

## Phase 7 — Orchestrations
- [x] `debrief.py` — `create_debrief(transcript_path, deal_code, quarter, segment,
      outcome, review=True, dry_run=False)`: attach transcript → chat_async with
      template+instructions → review loop → schema check → verification check →
      export .docx → index upsert. Idempotency: skip/require `--force` if deal_code
      already indexed with identical transcript hash.
- [x] `synthesis.py` — `create_quarterly_brief(quarter, review=True, dry_run=False)`:
      pull index stats for the quarter → open all matching debrief Files in one
      multi-document session (`sessions.init`) → build `[CUSTOMER]`-redacted context →
      chat_async with cross_session_search/memory → review loop → schema +
      verification + **redaction gate** → export .docx + .pdf
- [x] Unit tests for both, fully mocked (no network), covering: happy path, schema
      failure path, redaction-block path, empty-quarter "no findings" path

## Phase 8 — CLI
- [x] `cli.py` — `winloss debrief create`, `winloss debrief list`,
      `winloss brief quarterly`, `winloss search`, `winloss redact-check <file>`,
      all with `--dry-run`
- [x] Unit tests: argument parsing, `--dry-run` makes zero network calls

## Phase 9 — Fixtures & demo data
- [x] 6–8 synthetic fictional transcripts across 2 quarters, ≥3 competitors, mixed
      win/loss, at least one small-sample-only competitor, one prompt-injection
      attempt transcript
- [x] `scripts/demo.sh` — the exact commands for the demo video, in order

## Phase 10 — Documentation
- [x] `README.md` — purpose, prerequisites, install, env setup, run, test (mock vs
      integration), demo steps, expected output, troubleshooting
- [x] Assignment requirement checklist table (Implemented / Tested / Demonstrated)
- [x] Known limitations section (mirrors architecture.md §12, kept honest)

## Phase 11 — Validation pass
- [x] Re-read the assignment card line by line against what was built
- [x] Run full unit test suite, record pass/fail counts in `progress.md`
- [x] `--dry-run` walkthrough of both commands, capture output as a transcript in
      `progress.md`
- [x] Final status determination (COMPLETE / PARTIALLY COMPLETE / BLOCKED) — expected
      **PARTIALLY COMPLETE** given no live API key, stated honestly, not hidden

## Explicitly out of scope (see architecture.md §2, and global "do not overbuild")
- No FastAPI server, no database, no React frontend, no MCP server of our own
- No Task 1 agentic-system machinery (concurrency locks, resumable job store, cost
  dashboards) — Task 2 is a standalone CLI build, not Task 1
- No GitHub PR automation — this agent cannot create GitHub accounts/PRs; the project
  is structured to be dropped into `superdocs-builds/use-cases/<name>/` by the user
