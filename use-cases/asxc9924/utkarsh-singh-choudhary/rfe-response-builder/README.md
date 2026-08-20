# RFE (Request for Evidence) Response Builder

Built on [SuperDocs](https://superdocs.app) for the SuperDocs Round 2 task
(open task list, immigration-vertical family, band S3).

Parses an officer's RFE notice into its discrete numbered requests,
retrieves what the original petition already argued and evidenced on
each point, drafts a response that **addresses the officer's specific
concern directly** (not a restatement of the petition), **identifies the
new evidence needed** from a supplied evidence catalog, **assembles the
response with a new, numbered exhibit set**, and produces a **coverage
checklist mapping every request in the notice to the part of the
response that answers it** — so nothing in the notice goes unanswered,
per the card's own bar for "what strong looks like."

All case data (notice, petition arguments, evidence catalog, client) is
synthetic — fictional client, fabricated facts. No real filings.

`usecases/rfe-response-builder/` has the vertical-mini-app-catalog entry
(one-paragraph summary, sample inputs, buyer profile) pointing back at
this code — see that folder's README if you found this repo through a
use-case listing rather than directly.

## What strong looks like, and how this meets it

- **Every request maps to an answer, honestly**: `build_coverage_checklist`
  marks each parsed request answered/unanswered based on whether a
  response turn both (a) succeeded and (b) passed `is_substantive_reply`
  — a 200 response containing a hedge/refusal ("I don't have enough
  information...") is NOT ANSWERED, not a false success. For real runs,
  a third gate applies: a human must have explicitly approved the
  section in the review UI (see "Human review gate" below); silence is
  treated as rejection, never approval. `CoverageRow.response_section`
  points at the exact heading in the exported document that answers
  each item, using the same string SuperDocs was instructed to title
  that section with, so the mapping is a real, checkable link rather
  than two independently-worded strings that happen to agree today.
- **Responses engage the specific concern, not the original petition**:
  `build_response_instruction` explicitly forbids restating the prior
  argument verbatim and instructs the AI to address the officer's
  stated concern; when there's no prior-petition match it says so
  explicitly instead of inventing one.
- **Prior-petition citations are accurate**: matching is deterministic
  keyword-overlap scoring (`PriorPetition.best_matches`), not an LLM
  guess — the same input always produces the same citations, up to
  `top_n` ranked matches, and a `source_ref` is only ever one already
  present in the supplied petition-arguments file or an uploaded
  supporting document, never fabricated.
- **Multiple source documents, not just one JSON file**:
  `arguments_from_free_text` lets any number of free-text supporting
  documents (petition letter, employer letter, expert opinion, etc.) be
  parsed into candidate arguments and merged with the structured
  petition JSON — each `source_ref` traces to a real paragraph in a
  real uploaded document (`"employer_letter.txt, ¶3"`), so matching
  stays keyword-level rather than semantic/embeddings-based on purpose:
  a citation can never point at text that doesn't exist in the record.
  The webapp's `supporting_docs` field and the CLI's repeatable
  `--supporting-doc` flag both feed this.
- **New evidence needed is identified, and its status is explicit**:
  `NewEvidenceCatalog` matches each request against a supplied catalog
  of evidence *categories* (deterministic keyword overlap, same
  approach as petition matching) — the tool only ever surfaces evidence
  types it was actually given, never guesses at case-specific facts.
  `classify_evidence_status` then labels each item
  `already_submitted` / `new_evidence_identified` / `needs_attorney_review`
  so an attorney can immediately see which requests have no supporting
  match at all, rather than that gap being implicit.
- **A real exhibit set is assembled**: `build_exhibit_list` turns
  matched evidence into a numbered exhibit list, deduped so evidence
  supporting multiple RFE items becomes one exhibit referenced by all
  of them. The exhibit list is appended to the response document and
  also written as a machine-readable `*-exhibit-manifest.json` next to
  the `.docx`, so a paralegal (or another tool) can act on it directly.
- **A single failed drafting turn doesn't sink the whole response**:
  each RFE item is its own chat turn; transient failures (429/5xx) are
  retried with exponential backoff inside `SuperDocsClient.chat`, and
  only a failure that survives retries is caught, logged, and shown as
  `NOT ANSWERED` in the final checklist rather than aborting or
  silently passing.

## Human review gate

Every real (non-dry-run) run in the web app goes through
`rfe_response_builder/review.py` instead of drafting-and-exporting in
one shot:

1. `start_review()` opens the document and drafts every RFE item as an
   async SuperDocs turn with `approval_mode="ask_every_time"`, so
   SuperDocs holds each proposed section pending rather than
   auto-applying it.
2. The web app renders a review page (`/review/<id>`) showing every
   drafted section with its prior-petition citations and matched
   evidence, each behind its own approve checkbox and optional feedback
   field.
3. `finalize_review()` only calls `approve_change` for sections the
   human actually checked; a request left unchecked is rejected, never
   silently approved. Only approved-and-substantive sections count as
   ANSWERED in the coverage checklist, and only then does the app
   append the checklist/exhibit list and export.

This was previously dead code — `approve_change` and
`chat_async(approval_mode=...)` existed on `SuperDocsClient` but nothing
called them, so every drafted section reached the export unreviewed.
The pending-change JSON shape SuperDocs returns for an
`awaiting_approval` job is inferred from the documented `chat_async` /
`approve_change` contract, not confirmed against a live response (this
sandbox's network egress allowlist blocks `api.superdocs.app` — see
"Known limitations"). `review._interpret_job` is deliberately defensive
about this: it tries several plausible field names and falls back to
showing the reviewer the raw job JSON rather than crashing or silently
treating an unrecognized shape as approved.

The CLI's `build_response_packet` (in `generate.py`) still exists as
the non-interactive, single-shot path for batch/CI use — it now also
uses `is_substantive_reply` to gate what counts as answered, it just
skips the human-approval step entirely (there's no human in a batch
job). Use `review.py`'s two functions directly if you want a
review-gated CLI flow too; the web app is the only caller today.

## Web app (deploy on Render)

`webapp/` wraps the same package in a small Flask UI: upload a notice +
petition (+ optional evidence catalog), fill in case ID / client name, and
either see a dry-run breakdown in the browser or download the generated
`.docx`. Nothing in `rfe_response_builder/` is touched by the web layer.

**Deploy via Render Blueprint:**

1. Push this repo to GitHub/GitLab.
2. In Render: New → Blueprint → point at the repo (uses `render.yaml`).
3. Set the `SUPERDOCS_API_KEY` env var on the service (Render will prompt
   for it since it's marked `sync: false`). Without it, the app still
   works in dry-run-only mode.
4. Deploy. Render runs `pip install -r webapp/requirements.txt` then
   `gunicorn --chdir webapp --bind 0.0.0.0:$PORT app:app`.

**Run locally:**

```bash
pip install -r webapp/requirements.txt
cp .env.example .env   # then edit .env, or just export the vars below
export SUPERDOCS_API_KEY=sk_your_key   # optional, dry-run works without it
export FLASK_SECRET_KEY=some-random-value
python webapp/app.py                    # http://localhost:5000
```

### Production hardening in `webapp/app.py`

- **Timeouts on every SuperDocs HTTP call** (`superdocs_client.py`): none of
  the original calls passed `timeout=`, so a stalled connection would hang
  a gunicorn worker (and therefore a chunk of the app's capacity)
  indefinitely. All five endpoints now default to a 60s timeout.
- **No default secret in production**: boot fails loudly if
  `FLASK_SECRET_KEY` is unset while `RENDER` or `FLASK_ENV=production` is
  set, instead of silently signing cookies with the placeholder value
  that's sitting in this repo.
- **CSRF protection** on the `/generate` form via `flask-wtf`.
- **Per-IP rate limiting** on `/generate` via `flask-limiter`
  (`GENERATE_RATE_LIMIT`, default `10 per hour`) — a real run spends
  SuperDocs operations, so this is the endpoint worth protecting from
  abuse or retry storms.
- **Upload validation by extension and encoding**, not just size — wrong
  file type or non-UTF-8 content now returns a clear flash message
  instead of an unhandled exception.
- **Sanitized case ID** is used for both the output filename (already the
  case before) and the SuperDocs session ID (new), and a garbage case ID
  is now rejected with a clear error rather than silently accepted.
- **Security response headers** (`X-Content-Type-Options`,
  `X-Frame-Options`, `Content-Security-Policy`, HSTS in production) and
  `ProxyFix` so Render's reverse proxy headers (client IP, scheme) are
  trusted correctly for rate limiting and secure cookies.
- **Explicit error pages** for 400/413/429/500 instead of Flask's default
  HTML, plus a `gunicorn --timeout 120 --workers 2 --threads 4` startCommand
  in `render.yaml` so a real (non-dry-run) generation — which makes one
  SuperDocs turn per RFE item — isn't killed by the 30s default worker
  timeout.
- `webapp/requirements.txt` adds `flask-wtf` and `flask-limiter`; both
  degrade to a loud startup warning (not a crash) if somehow missing, so
  a misconfigured environment fails safe rather than hard-crashing the app.

None of this touches `rfe_response_builder/` except adding request
timeouts to `superdocs_client.py` — the domain logic and its test
coverage are unchanged.

## Quickstart

```bash
git clone <this-repo-or-folder>
cd rfe-response-builder
make install
export SUPERDOCS_API_KEY=sk_your_key   # from use.superdocs.app > Settings > API Keys
make run
```

Sanity-check before spending any SuperDocs operations:

```bash
make dry-run   # parses, matches, and prints instructions + exhibit list; zero API calls
```

No key yet?

```bash
PYTHONPATH=. python -m rfe_response_builder.generate \
  --notice data/sample_rfe_notice.txt \
  --petition data/sample_petition_arguments.json \
  --new-evidence data/sample_new_evidence.json \
  --case-id CASE-2002 --client-name "Marco Alvarez" \
  --out out/ --agent-signup
```

Output: one assembled `.docx` response packet in `out/`, with an
Exhibit List and a Coverage Checklist section as its final parts, plus
a `<case-id>-exhibit-manifest.json` alongside it.

## CLI flags

| Flag | Required | Purpose |
|---|---|---|
| `--notice` | yes | Path to a plaintext RFE notice |
| `--petition` | yes | Path to prior petition arguments JSON |
| `--supporting-doc` | no | Path to a free-text supporting document (repeatable); parsed into candidate arguments and merged with `--petition` |
| `--new-evidence` | no | Path to a new-evidence catalog JSON; skipped (no exhibits) if omitted |
| `--case-id` | yes | Used in the document title and sanitized for output filenames |
| `--client-name` | yes | Used in the document title |
| `--out` | no | Output directory (default `out/`) |
| `--dry-run` | no | Parse + match + print instructions/exhibits; zero SuperDocs calls |
| `--review` | no | Draft via the human-review gate, prompting `y/N` for each section in the terminal before it's exported; mutually exclusive with `--dry-run` |
| `--agent-signup` | no | Sign up a free SuperDocs agent account if no API key is set |
| `-v` / `--verbose` | no | Debug-level logging |

## Testing

```bash
make test-offline   # 74 tests, zero network, zero SuperDocs operations spent
make lint           # ruff
```

- `tests/test_rfe.py` — pure domain logic: notice parsing (numbered
  list splitting, no-marker fallback, empty-input handling), top-N
  keyword matching against the prior petition, new-evidence-catalog
  matching, exhibit numbering/deduplication, instruction construction,
  checklist correctness and response-section mapping, case-id filename
  sanitization, the `is_substantive_reply` answer-quality gate, evidence
  status classification, multi-document paragraph extraction, and
  stemmed fuzzy-match suggestions.
- `tests/test_generate_integration.py` — the full non-interactive
  pipeline (notice → match → evidence identification → exhibit assembly
  → per-item drafting turns → checklist → export) against a mocked
  SuperDocs API via `requests_mock`, including tests that a persistent
  per-item failure and a non-substantive reply are both honestly
  reported as `NOT ANSWERED`, a one-off transient failure is absorbed by
  the client's retry logic, and an end-to-end run of the `--review` CLI
  flag with mocked terminal input.
- `tests/test_review.py` — the human-review-gated flow: pending items
  are only counted as answered when explicitly approved, an omitted
  decision is treated as rejected, and a synchronously-completed turn
  (no pending change to approve) still has to pass the substantive-reply
  check.
- `tests/test_review_store.py` — the SQLite-backed review session store:
  round-trip, cross-instance visibility (standing in for separate
  gunicorn workers sharing one file), deletion, and TTL pruning.
- `tests/test_webapp.py` — the Flask layer: upload validation
  (extension, encoding, multi-document `supporting_docs`), CSRF, rate
  limiting, error handling, the dry-run path, and the real-run →
  review page → approve → export flow against a mocked SuperDocs API.

## Architecture

```
data/sample_rfe_notice.txt        ---parse_rfe_notice--->  list[RFERequest]
data/sample_petition_arguments.json -> PriorPetition              |
data/sample_new_evidence.json    -> NewEvidenceCatalog             |
(optional free-text docs)  --arguments_from_free_text-->    -> merged into PriorPetition
                                          |                         v
                                          `---best_matches (top-N, both)
                                                               |
                                                               v
                                build_exhibit_list -> numbered, deduped exhibits
                                                               |
                                                               v
                                   build_response_instruction (per request)
                                                               |
                                                               v
                                generate.py: one SuperDocs chat turn per
                                request (with retry/backoff on 429/5xx),
                                on one running document/session
                                                               |
                                                               v
                          build_coverage_checklist -> appended as final
                          section (with Exhibit List section) -> export
                          .docx + exhibit-manifest.json
```

`rfe.py` never imports `requests` or knows about SuperDocs; `generate.py`
is the only place that touches the SuperDocs client, so parsing/matching/
exhibit logic is testable with zero mocking and the API integration is
testable with mocking alone.

## Extending

- **Physical exhibit attachment**: the exhibit manifest JSON is designed
  to hand off to an exhibit-indexer build (also on the open list) that
  attaches the actual scanned evidence files as numbered exhibit PDFs.
- **Evidence catalog per practice area**: `data/sample_new_evidence.json`
  is a stand-in for a real firm's evidence-category library; swap it
  for a per-case-type catalog (family-based, employment-based, etc.)
  via `--new-evidence`.
- **Semantic/vector retrieval**: `PriorPetition.fuzzy_matches` now
  covers morphological variants (stemming) as an unverified suggestion
  when exact keyword matching finds nothing — see "Fuzzy match
  suggestions" below. A real vector index over uploaded documents would
  go further (catching true synonyms, not just word-form variants); the
  human review gate (`review.py`) is what makes shipping a fuzzier
  matcher safe, since any match — exact or fuzzy — can be rejected
  there before it ever reaches the exported document.

## Fuzzy match suggestions (stemmed, not semantic)

When `PriorPetition.best_matches` finds nothing for an RFE item (exact
keyword overlap = 0), `fuzzy_matches` runs a second pass over stemmed
keywords — a pure-stdlib suffix-stripping stemmer (`_stem` in `rfe.py`),
no embeddings, no external calls. This catches morphological variants
exact matching misses (`"specialized"` vs. `"specializing"`) but NOT
true synonyms (`"expertise"` vs. `"experience"` still won't connect).

Critically, fuzzy matches are **never** used as a citation or fed into
the drafting instruction — they're surfaced in the dry-run output, the
review page, and the CLI's `--review` prompt as an explicit "possible
related argument, UNVERIFIED, not cited" note with a confidence score,
so a human can confirm it before it's used, never so the tool can quietly
upgrade a guess into a citation.

## Known limitations (told honestly)

- Matching (both prior-petition and new-evidence) is keyword-overlap
  scoring, ranked to top-N — an improvement over single-best-match, but
  still not semantic; a request phrased very differently from the
  matching argument/evidence description can still score 0 on the
  strict matcher (the fuzzy-suggestion fallback above catches some but
  not all of this gap — see its own section for exactly what it does
  and doesn't cover). This applies to `arguments_from_free_text`'s
  multi-document ingestion too: it's paragraph-level keyword search,
  not embeddings.
- Retries only cover 429/5xx from the SuperDocs API itself; a
  persistent outage still surfaces as `NOT ANSWERED` after
  `max_retries` is exhausted (default 2), by design — the checklist
  should never claim success it can't back up.
- The review gate's pending-change JSON shape (`review._interpret_job`)
  is inferred from the documented `chat_async`/`approve_change`
  contract, not confirmed against a live SuperDocs response — this
  sandbox's network egress allowlist blocks `api.superdocs.app`. The
  function is deliberately defensive (tries several plausible field
  names, falls back to showing raw job JSON) so an unrecognized shape
  degrades to "reviewer sees raw data" rather than a crash or a
  silent false-approve.
- The web app's review-session store (`webapp/review_store.py`) is
  SQLite at a local file path (`/tmp` by default), shared by every
  gunicorn worker on one Render instance — verified live: a session
  written via one `ReviewSessionStore` instance is readable and
  deletable from a second instance pointed at the same file
  (`tests/test_review_store.py`). This solves the multi-*worker* case
  but not multi-*instance* horizontal scaling, since each Render
  instance has its own local disk — that would need a real shared
  store (Postgres/Redis) instead, which only touches
  `webapp/review_store.py`.
- The CLI now has a review-gated path too (`--review`, prompts in the
  terminal via `_run_interactive_review` in `generate.py`, tested end
  to end in `test_cli_review_flag_prompts_and_only_exports_approved_items`).
  The plain `build_response_packet` path (no `--review` flag; used for
  batch/CI) still has the substantive-reply honesty gate but skips
  human review entirely by design — there's no human to prompt in an
  unattended batch job.

---
Built for the SuperDocs task by [your name here].
