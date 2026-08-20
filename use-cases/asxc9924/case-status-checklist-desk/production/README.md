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

## Two ways to run this

**1. CLI (local/dev, flat JSON file)** — the original sample script:

```bash
git clone <this-repo-or-folder>
cd case-status-checklist-desk
make install
export SUPERDOCS_API_KEY=sk_your_key   # from use.superdocs.app > Settings > API Keys
PYTHONPATH=. python -m case_status_desk.generate \
  --cases data/sample_cases.json --case-id CASE-1001 --out out/
```

Output: one `.docx` letter per case in `out/`. Good for trying the logic
out, not for running against real client data at volume.

**2. HTTP API (production, DB-backed, deployable)** — see below.

Note: the old `--agent-signup` flag (auto-registering for a fresh
SuperDocs API key over the network, unattended) has been removed.
Credential creation should be a deliberate human action.

## Running the production API

```bash
cp .env.example .env      # fill in SUPERDOCS_API_KEY and STAFF_API_KEYS
pip install -r requirements.txt
python scripts/seed_db.py                 # one-time: loads sample cases into the DB
uvicorn case_status_desk.app:app --reload
```

Endpoints (all require `Authorization: Bearer <staff key>` from
`STAFF_API_KEYS`):

- `GET /v1/cases` — list cases; `?needs_update=true` filters to cases with
  outstanding items (i.e. "any update required"). Any staff role.
- `GET /v1/cases/{case_id}` — one case's live status + checklist. Any staff role.
- `POST /v1/cases/{case_id}/letters` — draft a letter from current case
  state. **Does not export.** Status starts as `awaiting_approval`. Any staff role.
- `POST /v1/letters/{letter_id}/approve` — **requires `approver` or `admin`
  role**, and rejects with 409 if the approver is the same person who
  drafted the letter — separation of duties is enforced, not just role
  membership, so nobody can rubber-stamp their own draft.
- `POST /v1/letters/{letter_id}/export` — exports to `.docx`. **Requires
  `approver`/`admin` role AND refuses with 409 if the letter isn't yet
  `approved`.** This is the human-in-the-loop gate: nothing goes out to a
  client without a *different* person confirming it first.

### Roles

`STAFF_API_KEYS` entries are `key:name:role` triples:

```
STAFF_API_KEYS=sk_abc:Priya:preparer,sk_def:Marco:approver,sk_ghi:Admin User:admin
```

- `preparer` — can view cases and draft letters.
- `approver` — can also approve and export.
- `admin` — everything. (A bare `key:name` pair with no role, for
  backward compatibility, is treated as `admin`.)

Every draft/approval/export is a row in `generated_letters` — a full
audit trail of who requested what, when, and who approved it, with the
checklist snapshot captured at draft time (so you can always answer "what
did we tell this client and when").

### Importing real case data

Three ways to get real case data in, from least to most integration work:

**1. Upload a CSV/Excel export from the firm's existing CMS (works today, no CMS-specific code needed).**
Every practice-management system — Clio, Docketwise, INSZoom, MyCase, a custom
CRM, whatever — can export its case list to CSV or Excel. Instead of building
and maintaining a bespoke API adapter per vendor, the firm exports periodically
and uploads the file:

```bash
curl -X POST http://localhost:8000/v1/cases/import-upload \
  -H "Authorization: Bearer $STAFF_KEY" \
  -F "file=@case-export.csv"
```

Required columns: `case_id, client_name, case_type, stage` (plus optional
`language`, and one row per required document via
`document_name, document_form_type, document_received, document_due_date` —
see `CsvFileCaseSource` in `case_status_desk/case_import.py` for the full
documented shape). `.xlsx` works the same way. Upserts by `case_id`, so
re-uploading a fresh export is exactly what keeps the checklist reflecting
the true current state of the file — not just after the first upload, every
time. Missing/malformed rows are skipped rather than failing the whole
import; a missing required column fails the whole file with a clear 422.

This is the practical answer to "which CMS does the mapping need to
target" for a firm you don't have a live integration with yet — it targets
a small documented column shape instead of a vendor's proprietary schema.

**2. `scripts/seed_db.py`** (loads `data/sample_cases.json`) — sample/demo data only.

**3. A live API integration**, for firms that want automatic sync instead of
periodic upload. `case_status_desk/case_import.py` defines a `CaseSource`
interface — implement `fetch_cases()` against your CMS's real API and pass
it to `sync_cases()`. A generic `HttpCaseSource` is included as a starting
point for any CMS with a REST case-list endpoint, but **its field mapping
(`HttpCaseSource._map()`) is deliberately unimplemented** — no two CMS's
share a schema, so this step has to be written against your specific
system rather than guessed at:

```bash
python scripts/import_cases.py --source http --base-url https://your-cms/api --api-key "$CMS_KEY"
```

Wire whichever path you use into a scheduled job (Render cron job, or any
scheduler) so case data — and therefore every checklist — stays current
automatically rather than only updating when someone remembers to re-upload.

### Deploying to Render

`render.yaml` in the repo root defines a web service plus a managed
Postgres database. From the Render dashboard: New → Blueprint → point at
this repo. After the first deploy, set `SUPERDOCS_API_KEY` and
`STAFF_API_KEYS` in the service's Environment tab (they're marked
`sync: false` in the blueprint on purpose — real secrets should never be
committed to `render.yaml` or the repo). Then run either
`scripts/seed_db.py` (sample data, for a demo) or `scripts/import_cases.py`
against your real CMS (production) via Render's shell, or as a scheduled job.

### Production readiness notes

- **Auth**: role-aware bearer-key allowlist by default (`STAFF_API_KEYS`),
  with separation of duties enforced (preparer drafts, a *different*
  approver signs off). **Real SSO is also implemented** (`sso.py`) —
  set `OIDC_ISSUER` + `OIDC_AUDIENCE` and `require_staff_user()` switches
  to verifying real OIDC tokens (Okta, Azure AD/Entra ID, Google
  Workspace, Auth0 — any standard OIDC provider) instead of shared keys.
  **What only you can supply**: your provider's actual issuer URL and
  audience, and `OIDC_ROLE_CLAIM`/`OIDC_ROLE_MAP` to translate your IdP's
  real group/role names into this app's `preparer`/`approver`/`admin`
  vocabulary — that mapping is inherently specific to your identity
  provider and can't be guessed. Unmapped roles fail closed to
  `preparer` (least privilege), not open.
- **Rate limiting** (`rate_limit.py`): per-API-key sliding window,
  `RATE_LIMIT_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS` (default 60/60s),
  429 + `Retry-After` on breach. **Caveat, stated plainly**: this is
  in-process memory, correct for one instance but *not* a true global
  limit across multiple instances/workers — scaling out means the
  effective limit multiplies per instance. Swapping to a shared Redis
  counter is the fix, and is a real infra decision left to you rather
  than added silently.
- **Structured logging** (`logging_setup.py`): JSON log lines to stdout
  (Render/most log aggregators parse this natively), each request tagged
  with a `request_id` that's also returned as an `X-Request-ID` response
  header, so a client-reported issue can be traced to its exact log line.
- **Retries**: `superdocs_client.py` retries 5xx/network errors with
  exponential backoff (`tenacity`); 401/403 fail fast and surface as a 502
  with a clear "credential rejected" message rather than retrying a dead
  key.
- **PII**: case data includes names and document details. Treat the
  Postgres instance and `SUPERDOCS_API_KEY`/`STAFF_API_KEYS` accordingly
  (Render's built-in secret storage, not `.env` files, in production).
- **Automated letter-content validation** (`letter_validation.py`): every
  draft is checked programmatically before a human ever reviews it —
  every currently-outstanding document and its exact `form_type` must
  appear in the letter text (hard error if missing), the approved stage
  summary and next-step language must appear verbatim (hard error if
  altered/paraphrased), and language matching legal-advice or
  outcome-prediction patterns is flagged (warning). Results are stored
  on the letter (`validation_passed`, `validation_issues`) and returned
  in the API response. `POST /v1/cases/{id}/letters?block_on_validation_error=true`
  refuses to even create the draft on a hard failure; by default the
  draft is still created (visible to the approver with its issues) but
  `POST /v1/letters/{id}/approve` refuses to approve a failed draft
  unless the approver explicitly passes `override_validation=true` —
  which is itself recorded (`validation_overridden_by`) in the audit
  trail, so an override is a visible, attributable decision, not silent.
  This doesn't replace human review (the approval gate is unchanged) —
  it's a cheap, deterministic check that runs first, so the approver is
  reviewing a letter that's already been mechanically verified against
  the checklist rather than a raw, unverified draft.
- **SuperDocs Files integration**: on export, the letter's drafting
  session is linked to its SuperDocs durable File (`list_documents` /
  `rename_document` / `archive_document` from the Files API), so the
  letter has real version history in SuperDocs and isn't just a local
  `.docx` snapshot. `POST /v1/letters/{id}/archive-superdocs-document`
  retires it (soft-delete, ~30-day recoverable) once a case closes.
  **Honest limitation**: the current SuperDocs chat/export response
  doesn't directly return the durable File's id, so the link is made by
  matching the most-recently-updated File right after the session's
  chat call (`_link_superdocs_document` in `service.py`) — a reasonable
  heuristic for one letter at a time, not a guaranteed-correct id lookup
  under concurrent account activity. This is best-effort by design: if
  the lookup fails, the `.docx` export still succeeds (tested).
- **What's left, honestly**: real case data now has a working path that
  doesn't require CMS-specific code — `POST /v1/cases/import-upload`
  accepts a CSV/Excel export from whatever CMS the firm actually uses
  (see "Importing real case data" above). What's still deliberately
  unfinished is the *live API* path: `HttpCaseSource._map()` raises
  `NotImplementedError` because no two CMS's share a field schema, so
  automatic sync against a specific vendor's API has to be written
  against that vendor, not invented here. Same reasoning for
  `OIDC_ISSUER`/`OIDC_ROLE_MAP` above — these are the two places this
  build cannot be finished without information only you have (your CMS's
  live API and field names, if you want sync instead of periodic upload;
  your IdP's real issuer and group names). Everything else — rate
  limiting, logging, auth plumbing, the approval gate, retries, the
  upload-based CMS path — is implemented and tested.

## Testing

```bash
python -m pytest tests/ -q    # 63 tests, zero network, zero SuperDocs operations spent
```

`test_cases.py` tests the domain logic (stage language, checklist
derivation, prompt construction) with no dependencies at all.
`test_generate.py` uses `requests_mock` to intercept every SuperDocs API
call for the CLI path. `test_service_and_app.py` covers the DB-backed
production path: checklist correctness against live DB state, the
draft→approve→export gate (export refuses until approved), the audit
snapshot, auth rejection, and — found by this test suite — a regression
where the DB seeder originally read the wrong JSON key and silently
seeded every case with an empty checklist. All of it runs against a
temp SQLite file and a fake SuperDocs client, no network or real key
required.

## Architecture

```
                       cases.py
             (pure domain logic: stage language,
              checklist derivation, prompt text --
              never imports requests or SQLAlchemy)
                     /              \
                    /                \
      generate.py (CLI)        db.py (case store)
      loads data/*.json               |
              \                  service.py (draft -> approve -> export,
               \                       audit trail)
                \                     |
                 \               app.py (FastAPI, auth-gated HTTP API)
                  \                   |
                   \                  v
                    superdocs_client.py (thin REST wrapper,
                    retries on 5xx, fails fast on bad auth)
                              |
                              v
                     SuperDocs API -> .docx letter
```

`cases.py` is deliberately dependency-free and shared by both paths, so
the "what does this case actually need to say" logic is tested once and
used everywhere. `service.py` is where the human-approval gate and audit
logging live; `app.py` is a thin HTTP layer over it.

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
