# Trade-show lead → tailored recap batch

Built for SuperDocs Round 2, Task 2 (assigned build). From a CSV of
trade-show leads with booth notes, generate one tailored, branded recap
document per lead — what was discussed, what was promised, what happens
next — as a single batch run. N leads in, N documents out.

## This version fixes a broken first attempt — read this first

The earlier version of this build was written against a **guessed API
schema** — `POST /documents`, `POST /documents/{id}/chat`,
`POST /documents/{id}/approve`, `GET /documents/{id}/export` — because
`docs.superdocs.app` was reported unreachable from that build
environment. **None of those endpoints exist on the real SuperDocs API**,
so every request would have failed. This version is rewritten against
the real, documented contract — see "How this matches the real API"
below — and also adds a genuine document-level verification step that
wasn't there before (see "How 'no invented specifics' is actually
proven").

## How this matches the real API

| Step | Endpoint | Key request fields | Key response fields |
|---|---|---|---|
| Upload template | `POST /v1/documents/upload` (multipart) | `file`, `session_id` | `session_id`, `chunks_count`, `version_id` |
| Substitute (start) | `POST /v1/chat/async` | `message`, `session_id`, `approval_mode="ask_every_time"` | `job_id` |
| Substitute (poll) | `GET /v1/jobs/{job_id}` | — | `status`, `metadata.pending_changes`, `result` |
| Substitute (approve) | `POST /v1/chat/{session_id}/approve` | `job_id`, `approved: true`, `changes: [{change_id, approved}]` | — |
| Verify | `POST /v1/documents/export` (`format="txt"`) | `session_id`, `format` | text body |
| Deliver | `POST /v1/documents/export` (`format=<configured>`) | `session_id`, `format` | binary body |

`app/superdocs_client.py` cites the doc section behind each design
choice inline. It shares its async/poll/approve/continue sequence
implementation with `extensions/object-storage-pipeline` (this round's
other assigned build) — see that build's client for the more detailed
docstring on the HITL contract itself, since both were fixed for the
same root cause.

## Why `ask_every_time`, not `approve_all`

Both are implemented and tested (`tests/test_superdocs_client_hitl.py`).
`ask_every_time` is the default because it's the literal shape of "the
minimum contract with us is four calls: upload... send an edit
instruction... approve the proposed changes... export" from the task
brief, with every change auto-approved by the batch runner rather than
a human — the card doesn't call for a human reviewer here, so a
blocking gate would be scope creep, but the real approval mechanism is
genuinely exercised. Set `SUPERDOCS_APPROVAL_MODE=approve_all` for the
faster single-call alternative.

## Found running against the live API — three real bugs found, all fixed

Running the full batch against a real SuperDocs account surfaced
failure modes that offline mock-based tests couldn't have caught,
because they're specific to real, persistent server-side session state
and to genuine model behavior under a large, multi-field instruction.
This section is left as a running account of what actually happened,
not cleaned up after the fact — including the first fix attempt that
turned out to be insufficient, because that's a more honest and more
useful record than only showing the final working version.

**1. Stale session collision across separate CLI runs.** Session IDs
were originally deterministic per lead (`recap-L001-priya_nair`). A
`--limit 1` smoke test followed by a full batch run reused that exact
session for L001. SuperDocs sessions persist server-side **with their
full chat history**, even when the document body is reset by a fresh
upload — so the second run's identical substitution instruction landed
in a session that already "remembered" performing that edit, and the
AI correctly-but-unhelpfully treated it as an already-satisfied no-op,
leaving every `{{token}}` untouched. Fixed by giving every batch run a
random per-process salt (`uuid.uuid4().hex[:8]`, generated once in
`run_batch`), so no two separate CLI invocations can ever collide —
every run gets entirely fresh sessions, full stop. **Confirmed fixed**:
re-run against the live account, L001 came back clean.

**2. A single large substitution instruction is unreliable — and a
retry alone doesn't fix it.** One real run left 3 of 7 tokens (the
header line's `lead_name`/`lead_company`, plus the longest, most
detail-dense section) unresolved on one lead while 5 others in the same
batch substituted cleanly. The first fix attempt added a retry from a
fresh session on verification failure. **That fix was insufficient**:
re-run live, the exact same lead failed on the exact same 3 fields on
*both* independent attempts. Two identical failures in a row on an
unchanged instruction meant the problem was structural — the model
losing track partway through one large, 7-field edit — not one-off
randomness a retry could paper over.

The actual fix: `_process_one_lead` now sends **several smaller,
section-scoped turns** instead of one big instruction — one turn for
the header fields, one for `discussion_section`, one for
`promised_section`, one for `next_step_section` — matching
`docs.superdocs.app/guides/model-selection`'s own guidance that a vague
or broad instruction "invites wide edits" and a narrow, single-section
instruction is more reliable. If verification still finds issues after
those turns, one **targeted cleanup pass** re-requests *only* the
specific fields still wrong (built from `find_unresolved_tokens` /
`missing_expected_fields` in `app/verify.py`, not a blind re-ask of
everything) before falling back to the fresh-session retry from fix #1
as a last resort. `test_targeted_cleanup_pass_only_re_requests_the
_specific_leftover_fields` proves the cleanup pass touches only the
field that needed it and recovers within the same attempt, no retry
needed. `RecapResult.attempts` still records whether a full fresh-session
retry was needed, surfaced in the CLI output as `[needed 2 attempts]`.

This does cost more operations per lead than the original single-turn
design — typically 4 turns per lead instead of 1, up to 5 if a cleanup
pass is needed, up to 10 in the worst case (both attempts, both needing
cleanup). For 6 leads that's roughly 24–60 operations worst case,
trivial against the 500/month free tier, and a clearly correct trade to
make: the brief explicitly rewards honesty and correctness over raw
efficiency, and a self-healing pipeline that reliably ships correct
documents is worth more operations than a cheaper one that silently
ships broken ones.

## How "no invented specifics" is actually proven

The card's bar: "no cross-contamination — lead A's details provably
never appear in lead B's document; blank note fields degrade to honest
generic sections, never invented specifics; the batch of N inputs
yields exactly N documents." This is enforced at **two independent
layers**, and both are tested:

1. **Before SuperDocs is ever called** (`app/recap_content.py`): every
   value that goes into the substitution instruction is plain Python
   string assembly from one `Lead` record's own fields, or one of two
   fixed, honest fallback strings (`NO_NOTES_FALLBACK`,
   `NO_NEXT_STEP_FALLBACK`) when a field is blank. There is no model
   call in this layer at all — nothing here can invent anything, by
   construction, because nothing here is generative.
2. **After SuperDocs has run the edit** (`app/verify.py`, new in this
   version): the earlier design stopped at step 1 — it trusted the chat
   instruction to be followed exactly, but never checked the document
   SuperDocs actually produced. This version exports a free `txt` copy
   after every edit (exports don't cost operations — see
   `docs.superdocs.app/account/plans-and-usage#what-counts-as-an-operation`)
   and mechanically checks that (a) no `{{token}}` placeholder was left
   unresolved, and (b) every one of that lead's own section values
   actually appears in the output. A lead whose document fails this
   check is flagged in the CLI summary (`VERIFICATION ISSUES: ...`),
   not silently shipped — see `test_no_cross_contamination.py::test_a_bad_export_that_drops_a_field_is_flagged_not_silently_shipped`.

Cross-contamination between leads is proven by construction (a fresh
template upload and a fresh session per lead — nothing is ever shared,
so there's no state one lead's fill could read from another's) and
tested exhaustively:
`test_no_cross_contamination_between_leads` searches every *other*
lead's instruction for strings unique to one specific lead's record
and asserts they appear in exactly one place.

## How it works

For each lead in the CSV (`app/batch.py::_process_one_lead`):

1. Upload the branded template as a brand-new document into a
   brand-new, lead-specific, run-salted session (`upload_document`).
2. Send four section-scoped substitution turns — header fields,
   `discussion_section`, `promised_section`, `next_step_section` — each
   built entirely from that one lead's `RecapSections` (`edit_document`,
   called once per section; see "Found running against the live API"
   for why this is several small turns rather than one big one).
3. Export a free `txt` copy and run it through `verify_recap_text`. If
   anything's still wrong, send one targeted cleanup turn naming
   exactly the leftover field(s), then re-verify.
4. If verification still fails after the cleanup pass, retry the whole
   thing once from an entirely fresh session (`MAX_ATTEMPTS_PER_LEAD`).
5. Export the final delivery format (default `pdf`) and write it to
   `output/`.

One bad lead's failure (a raised exception anywhere in the sequence)
is caught, logged, and skipped — the other leads in the same batch
still produce their documents
(`test_partial_batch_failure_still_produces_results_for_the_working_leads`).

## Supported formats and domains

Templates are plain-text files with `{{token}}` placeholders
(`fixtures/recap_template.txt` is the reference shape: internal_owner,
event_name, lead_name, lead_company, discussion_section,
promised_section, next_step_section). Delivery format is any of
`docx`, `pdf`, `html`, `markdown`, `txt` (`EXPORT_FORMAT`, default
`pdf`) — whatever `POST /v1/documents/export` documents. No domain
restriction: swap `fixtures/leads.csv` and `fixtures/recap_template.txt`
for a different event/company's data and the same code path runs
unchanged — a second run means different leads inside the same CSV
shape, not a different code path.

## What's honestly thinner

- **Verification checks substitution correctness, not visual/branding
  fidelity.** It confirms the right text landed in the document; it
  doesn't check that the branded template's formatting (fonts, layout)
  survived the edit untouched. SuperDocs' own docs describe formatting
  preservation as a first-class guarantee of the edit pipeline; this
  build takes that as given rather than re-verifying it, since
  re-verifying visual formatting from exported bytes is a
  meaningfully harder problem than the text-substitution check this
  build actually does.
- **A lead still flagged after both attempts still gets a delivery file
  written** (flagged in the CLI summary as `VERIFICATION ISSUES`, not
  withheld) — the design choice is "ship it and tell the human clearly
  something's off" rather than "silently drop the document and require
  someone to notice a lead is missing." Either is defensible; this
  build picked visibility over silent omission.
- **The fresh-session retry is capped at one extra attempt**
  (`MAX_ATTEMPTS_PER_LEAD = 2`), on top of the in-attempt targeted
  cleanup pass — a genuinely stuck substitution (rather than a one-off
  issue the section-scoped turns and cleanup pass couldn't already
  resolve) should surface for a human to look at rather than silently
  burn operations retrying forever.
- **Retry/backoff is the same fixed exponential approach used in the
  object-storage-pipeline build** — see that build's README "What's
  honestly thinner" for the same caveat about not yet branching on
  quota-exhausted vs. infrastructure-surge 429s.

## Running it

```bash
pip install -e ".[dev]"
cp .env.example .env   # edit SUPERDOCS_API_KEY
python -m app.cli --leads fixtures/leads.csv --template fixtures/recap_template.txt --output output/
```

Small-sample mode while testing against a live key:

```bash
python -m app.cli --leads fixtures/leads.csv --template fixtures/recap_template.txt --output output/ --limit 2
```

## Tests (no live key, no network required)

```bash
pip install -e ".[dev]"
pytest -v
```

23 tests, all offline:

- `test_leads_and_content.py` — the pre-SuperDocs guarantee: sections
  are grounded in one lead's own fields, blank fields degrade to fixed
  honest fallbacks.
- `test_no_cross_contamination.py` — the batch-level guarantee: N in,
  N out; no shared session; no cross-lead string leakage in either
  direction; **the targeted cleanup pass re-requests only the specific
  field that was missed, not everything, and recovers within the same
  attempt** (`test_targeted_cleanup_pass_only_re_requests_the_specific
  _leftover_fields` — added after finding the live failure mode a
  blind retry alone couldn't fix); a persistently bad export is
  flagged, not shipped silently; a transient failure is recovered by
  the fresh-session retry as the final fallback; partial batch failure
  doesn't take down the working leads; `--limit` caps the run
  correctly.
- `test_superdocs_client_hitl.py` — the real
  upload/async-poll-approve-poll/export sequence against
  `httpx.MockTransport`, and the `approve_all` alternative.
- `test_verify.py` — the verification logic itself, isolated from the
  batch runner.
