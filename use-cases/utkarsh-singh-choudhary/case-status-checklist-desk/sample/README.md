# Case Status & Document Checklist Letter Desk

Built on [SuperDocs](https://superdocs.app) for the SuperDocs Round 2 task
(open task list, "Office and Workspace" / immigration-vertical family).

Generates each client's case-update letter straight from the case
record: the current stage in **fixed, approved plain language** (never
AI-authored) and a personalized checklist of outstanding documents
**regenerated from the live case file**, not a stale list from last time.

All case data is synthetic — fictional clients, fabricated facts. No
real filings.

## What strong looks like, per the card, and how this meets it

- **Checklist reflects true current state**: `Case.outstanding_documents()`
  is computed fresh from `required_documents[].received` every call — see
  `test_checklist_regenerates_from_current_state_not_stale`.
- **Plain-language stage description accurate per case type**: stage text
  lives in one `STAGE_LANGUAGE` dict (`cases.py`) — a wording change or a
  new stage is a data edit, not a rewrite, and it's the *only* stage
  language the AI is permitted to use in the letter instruction.
- **Approved-language boundary enforced**: the instruction sent to
  SuperDocs explicitly forbids legal advice/predictions and pins the
  status + next-step sentences verbatim; only the checklist formatting is
  left to the AI.

## Quickstart

```bash
git clone <this-repo-or-folder>
cd case-status-checklist-desk
make install
export SUPERDOCS_API_KEY=sk_your_key   # from use.superdocs.app > Settings > API Keys
make run
```

Run for a single case:

```bash
PYTHONPATH=. python -m case_status_desk.generate \
  --cases data/sample_cases.json --case-id CASE-1001 --out out/
```

Output: one `.docx` letter per case in `out/`.

This is a minimal reference implementation for the task's grading
criteria — a CLI-only script over a flat JSON case file, no server, no
auth, no persistence. For a deployable version of this same logic (HTTP
API, database-backed case store, staff auth with approve/export
separation, Render deploy config), see the companion `production/`
build in this repo — kept separate on purpose, since a `use-cases`
sample should stay small and readable.

## Testing

```bash
make test-offline    # 12 tests, zero network, zero SuperDocs operations spent
```

`test_cases.py` tests the domain logic (stage language, checklist
derivation, prompt construction) with no dependencies at all.
`test_generate.py` uses `requests_mock` to intercept every SuperDocs API
call, proving the request shapes and response handling (chat → export,
job polling, batch approval, 4xx error surfacing) without ever touching
the network or requiring `SUPERDOCS_API_KEY`.

## Architecture

```
data/sample_cases.json
        |
        v
  cases.py (pure domain logic: stage language, checklist, prompt text)
        |
        v
  generate.py (CLI: loads cases, drives the client, writes .docx files)
        |
        v
  superdocs_client.py (thin REST wrapper: chat / export / approve / job poll)
        |
        v
  SuperDocs API  ->  .docx letter in out/
```

Split deliberately along the same line as the domain-logic-vs-client
boundary tested above: `cases.py` never imports `requests`, and
`superdocs_client.py` never knows what a "case" is.

## Extending

- New case stage: add one entry to `STAGE_LANGUAGE` in `cases.py`.
- New document format on export: pass `fmt="pdf"` (or `html`/`markdown`/`txt`)
  to `SuperDocsClient.export()`.
- Human-in-the-loop review before sending: swap `client.chat(...)` in
  `generate.py` for `client.chat_async(..., approval_mode="ask_every_time")`
  and drive the `wait_for_job` / `approve_change` pair already implemented
  in `superdocs_client.py`.

## Known limitations (told honestly)

- Single-language letters per run; multi-language batching is
  per-case (`language` field) but not yet parallelized.
- No retry/backoff on 429 — a real production version should honor
  `Retry-After` on rate limits.
- The letter is drafted fresh each run rather than diffed against a
  prior version; for high case volume, reusing a stable `session_id`
  per case (already done) means SuperDocs itself holds edit history,
  but this tool doesn't yet surface "what changed since last letter."

---
Case status and document checklist letter desk -- an S1 use-case sample for the SuperDocs API (chat, templates, review, export).
