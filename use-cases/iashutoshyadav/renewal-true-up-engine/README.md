# Renewal & True-Up Documentation Engine

Built by **Ashutosh Yadav** for the SuperDocs engineering hiring round.

## What it does

Ninety days before a SaaS contract renews, this assembles the renewal pack for a whole customer cohort in
one batch: the usage/entitlement picture, the true-up calculation for any overage (with the exact governing
clause quoted from the customer's own signed contract, never assumed from a template), and a real amendment
document generated and edited through SuperDocs.

A clean renewal (no overage) applies automatically - nothing for a human to look at. A genuine exception
(real money owed, or a contract whose governing clause couldn't even be located) is held for a human to
review and decide, one at a time, with the exact arithmetic shown so it's reproducible by hand:

```
entitlement = 100
usage       = 125
overage     = 25
rate        = $20/unit
true-up     = 25 × $20 = $500
```

## How to run it

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env             # leave SUPERDOCS_API_KEY empty to run against the offline fake client
uvicorn app.web:app --port 8010
```

Open `http://localhost:8010`, click **Run cohort batch**, review any exceptions, approve or reject each one.

Runs against a bundled synthetic cohort of four invented customers (`data/sample_cohort/cohort.py`) -
two clean, one real overage, one with a deliberately missing clause - so the exception path is exercised
without needing real customer data.

## Tests (no live key needed)

```bash
pytest
```

25 tests, all offline against a fake SuperDocs client - true-up arithmetic (including the exact worked
example above), clause extraction with real quote verification, the human-approval flow (approve applies
the edit, reject leaves the contract untouched), batch isolation (one customer's failure never aborts the
rest), and the operation-limit stopping rule.

**Also verified against the real API** (`verify_real_api.py`, run manually with a real key, not part of
the pytest suite) - both the clean auto-apply path and the full human-in-the-loop approval path were run
against the live product, end to end, and confirmed working correctly. Five real bugs were found this way
and are now fixed:

1. **Export of text formats crashed.** `POST /v1/documents/export` returns markdown/html/txt content
   directly as the response body (`Content-Type: text/markdown`), not wrapped in a JSON envelope - the
   first version of `export_document` called `resp.json()` unconditionally and crashed on every export.
2. **A just-approved change wasn't reflected in an immediate export.** `approve_change` returning success
   doesn't mean the edit has landed yet - there's real propagation delay before the document actually
   updates. `apply_human_decision` now polls the job to `status='completed'` before exporting.
3. **Every quoted clause was silently missing its own section number.** "3.1 If Customer usage exceeds..."
   came back as "1 If Customer usage exceeds..." - the extraction regex treated the period inside "3.1"
   itself as a sentence boundary. Existing tests never caught it because they only checked quote *content*,
   never where the quote *started*. Fixed, with a regression test that checks the exact start of all three
   quotes.
4. **A real `SUPERDOCS_API_KEY` in `.env` was silently ignored.** `python-dotenv` was a listed dependency
   but `load_dotenv()` was never actually called anywhere - so `os.environ.get("SUPERDOCS_API_KEY")` always
   read an empty environment regardless of what `.env` said, and the app kept running against the fake
   client with no error, only an easy-to-miss "offline fake client" banner as any signal. Fixed by calling
   `load_dotenv()` at module load, before anything reads the environment. Found live on 2026-08-19 while
   deliberately trying to switch this exact build over to the real API - the banner never went away after
   setting the key, which is what surfaced it.
5. **Re-running the same batch against the real API eventually failed with a real 409.** `session_id` was
   a bare `f"renewal-{customer.customer_id}"` - stable across every run. Because the "Run cohort batch"
   button invites re-running the exact same cohort, a prior run's async approval job was still active in
   that session by the time a later run tried again, and the real API rejected the new request:
   `error_code: 'session_busy'` - *"The AI is still working on a previous request in this
   conversation... use a different session_id"* (the fix suggestion is straight from SuperDocs's own error
   body). Fixed in `app/renewal_engine.py` by suffixing `session_id` with a fresh `uuid.uuid4()` per call -
   safe because it only needs to stay consistent *within* one call (it flows through to the later approve
   step via `PendingHumanDecision.package.session_id`), not stable across separate runs. Diagnosing this
   took writing a throwaway script to inspect `SuperDocsError.detail` directly, because the UI only ever
   showed the bare status code (`"SuperDocs API 409"`) - fixed that too: `app/batch.py` now includes the
   real API's own error detail in what a failed customer reports, so this doesn't require a script next
   time.

None of these were found by inspection - all five surfaced only once this build was actually run against
the real product, which is exactly why that step happened before this code was committed, not after.

## Two follow-up improvements, made after live-testing this exact build

1. **The operation-limit stopping rule (`max_customers`) was tracked but never shown.** `BatchResult`
   already computed `skipped_over_limit`, but `dashboard.html` never rendered it - against a real cohort
   larger than the limit, an operator would have no visible indication that some customers were silently
   skipped, which directly contradicts this project's own "operations are bounded, not silently capped"
   design commitment (see `app/batch.py`'s module docstring). Fixed: the dashboard now shows a warning
   banner listing exactly which customers were skipped, whenever the list is non-empty.
2. **No feedback while a real batch runs.** Against the live API, a 4-customer batch measured 20-90+
   seconds this round, with the button just sitting there the whole time. `run_cohort_batch` already
   accepted an `on_progress` callback that was never wired to anything. Wired it up: `/batch/run` now
   updates in-memory progress state as each customer finishes, a new `/batch/progress` endpoint exposes it,
   and the dashboard polls it while the batch is in flight, showing "Processing 2 of 4: brightleaf" live.
   Verified for real: triggered a batch and polled `/batch/progress` concurrently, confirming genuine
   per-customer updates flow through as the real API calls complete, not just a static spinner.
3. **The renewal quote and talk track were dead code.** The task card names these explicitly as pack
   components - "the renewal quote... and a talk track for the customer-success manager" - not optional
   extras. `_renewal_quote_text()` and `_talk_track()` existed in `renewal_engine.py` but were never
   called from anywhere; the previously-computed `exported_summary_markdown` (the actual applied amendment
   text) was equally never rendered. Fixed: both helpers are now called for every package in
   `start_renewal()` and stored on `RenewalPackage`; a new `/pack/{customer_id}` page (linked from every
   clean-renewal row) shows the full pack - usage summary, renewal quote, talk track, and the applied
   amendment document - and the exception review page now shows the renewal quote and talk track
   alongside the true-up math and governing clause it already had. Verified against the real API: the
   talk track for a real overage case correctly quotes the exact governing clause verbatim, not a
   paraphrase, and the clean-renewal pack page shows the real applied amendment text with the entitlement
   genuinely updated (10,000 -> 12,000). Regression test:
   `test_renewal_quote_and_talk_track_are_populated_for_every_package_with_terms`.
4. **The `search` and `templates` surfaces named on this card were never touched.** Audited against the
   card's own text ("SURFACES IT TOUCHES: API, Multi-document, search, templates, images, export") - only
   API and export were actually exercised. Fixed by adding two real integrations, and each one surfaced
   its own real finding:
   - **Templates** (`POST /v1/templates/upload-base64` - the docs' own field names, `name`/`template_base64`,
     turned out to be wrong; the real API returns `422` and wants `filename`/`file_base64`, caught by
     actually calling it before trusting the docs). A real amendment template
     (`data/renewal_amendment_template.txt`) is uploaded once per process and referenced by name when
     drafting an amendment. **Real finding, live on 2026-08-20**: referencing the template on the
     auto-applying clean-renewal path caused SuperDocs to generate duplicated amendment sections (two
     separate "Renewal Amendment" blocks, two signature tables) and an unwanted `Please fill: Client Legal
     Name` placeholder even though the real customer name was already in the document - a clean renewal
     applies with no human catching that before it lands, so this was a real correctness risk, not a
     cosmetic one. Fixed by scoping the template reference to the exception path only, where a human
     reviews the proposed amendment before it applies - the clean path uses the plain instruction that was
     already verified correct. Re-verified against the real API after the fix: the clean path is back to
     the exact surgical single-clause edit, no duplication, no placeholders.
   - **Search** via `cross_session_search: true` on the amendment chat calls, letting SuperDocs draw on
     the account's own prior sessions when drafting. **Real finding**: enabling it measurably slowed
     individual chat calls (more history to search after a day of live testing accumulated real session
     count), and one customer failed outright with `The read operation timed out` against the client's
     60s timeout - which is exactly what the task brief's own warning describes ("operations... can take
     from thirty seconds to several minutes... the correct read is still processing, not a crash"). Fixed
     by raising `RealSuperDocsClient`'s default timeout to 240s, matching the documented range instead of
     contradicting it. Re-verified: the same batch that timed out at 60s completed cleanly at 240s.

5. **`images` was never touched at all - not even logged as a cut - and the human reviewer was approving
   amendments blind.** Re-audited against the card's own surface list a second time and found `images` sitting
   unaddressed in the exact sentence finding #4 above already quotes. Separately, `old_html`/`new_html`/
   `ai_explanation` were captured from every proposed change and then never rendered anywhere - a human
   clicked Approve or Reject on an amendment without ever seeing what it actually said, directly undercutting
   this project's own quoted line above ("a person reviews what the system intends to do... before it
   commits"). Fixed both:
   - **Images**: a real usage-vs-entitlement bar chart (`app/chart.py`, hand-built SVG, no charting
     dependency added), uploaded via `POST /v1/documents/images/upload-base64` and shown in the renewal pack.
     Same `url`-is-actually-403/`view_url`-is-the-real-link finding as the sibling build applies here too
     (same endpoint, same account) - confirmed live before trusting `view_url` (`200`, real PNG - SuperDocs
     rasterizes an uploaded SVG server-side, a small bonus finding).
   - **Diff visibility**: `PendingHumanDecision` and `PendingReviewItem` now carry the real
     `old_html`/`new_html`/`ai_explanation`, rendered in `review.html`'s "Proposed amendment" section instead
     of a static placeholder. Confirmed live that these fields are plain HTML strings needing no second JSON
     parse - the task brief's own warning about that gotcha doesn't apply to this particular field, verified
     rather than assumed either way.
   - **Multi-document, and two real bugs found live getting it working (2026-09-14)**: a second real
     document (a usage report built from the same `UsagePeriod` data, `app/renewal_engine.py::_usage_report_text`)
     is uploaded into the same session as the contract - the `Multi-document` surface this card names.
     First attempt: a chat instruction saying "this session also has a usage report attached - do not edit
     it" was not enough disambiguation - SuperDocs edited the *usage report* instead of the contract (caught
     by inspecting the real returned `old_html`: it was the usage report's own wording, not the contract's
     clause). Second attempt: naming both files explicitly by filename in the instruction *still* didn't fix
     it - `export_document(session_id)` kept returning the usage report. That call has no document/file
     parameter at all, which turned out to be the actual mechanism: the **active document for both editing
     and export is set by upload order** (whichever document was uploaded most recently), not by anything a
     later chat message says. Fixed by uploading the usage report first and the contract last. Re-verified
     live end to end: the contract is edited correctly, exported correctly, and the usage report is left
     completely untouched, on both the clean and exception paths.

## SuperDocs features used

- **REST API**, direct (`app/superdocs_client.py`) - not MCP. Every endpoint/schema here was verified
  against a real running session before this code was written (upload, chat, async chat with
  human-in-the-loop approval, and export were all exercised live during design).
- `POST /v1/documents/upload` - loads each customer's contract into its own session.
- `POST /v1/chat` (`approval_mode=approve_all`) - applies the entitlement amendment automatically for
  clean renewals.
- `POST /v1/chat/async` (`approval_mode=ask_every_time`) + `GET /v1/jobs/{job_id}` +
  `POST /v1/chat/{session_id}/approve` - the human-in-the-loop path for genuine exceptions: the amendment
  is proposed but never applied until a person decides.
- `POST /v1/documents/export` - the final renewal summary, exported as markdown.
- `POST /v1/templates/upload-base64` - uploads a real renewal-amendment template once per process; the
  exception path references it by name so a human-reviewed amendment can follow consistent formatting and
  signature-block conventions.
- `cross_session_search: true` on `/v1/chat` and `/v1/chat/async` - lets SuperDocs draw on the account's
  own prior renewal sessions when drafting an amendment.
- `POST /v1/documents/images/upload-base64` - a real usage-vs-entitlement chart, embedded in every renewal
  pack.
- Two documents per session (contract + a real usage report) - the `Multi-document` surface named on this
  card.

## Design notes

- Clause extraction is deterministic regex over a declared contract phrasing style, not an LLM - keeps
  every test in this project runnable with zero network calls and zero cost, per the round's own "real
  tests, no live key" standard. A production version would likely swap this one module for an LLM-backed
  extractor without touching anything downstream.
- "Genuine exception" (a decision this project's task card leaves undefined) is: any true-up amount greater
  than zero, or a governing clause that can't be located at all. A clean renewal never reaches a human -
  that's the entire point of a batch that surfaces real exceptions instead of dumping everything into review.
- No database - this is a single-operator, single-cohort-run review tool, not a persistent multi-user
  system. In-memory state is a deliberate scope match, not a shortcut.
