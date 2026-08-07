# Background-Check Consent Generator

**Built with:** SuperDocs API + a thin Python CLI
**Difficulty:** S2 — real employer compliance pain (FCRA disclosure/authorization
separation), genuine document generation, a real correctness bar to hit.

## What this is

Employers running background checks must, under the FCRA, give candidates a
disclosure document that contains **nothing else** (15 U.S.C. § 1681b(b)(2)(A)),
a **separately** signed authorization, and a summary-of-rights notice. Getting
this wrong — mixing a liability waiver or release clause into the disclosure —
is a common, real compliance mistake. This generator takes a company's
templates plus one candidate's details and produces the three documents as
genuinely separate files, then **verifies** (doesn't just assert) that the
disclosure stayed clean.

## How it works

1. `merge_fields()` — deterministic Python string-replace fills in
   `{{company_name}}`, `{{candidate_name}}`, etc. from `data/company.json` +
   `data/candidate.json` into the three HTML templates in `data/`.
2. Each merged document is sent to SuperDocs (`POST /v1/chat`) with a single,
   narrow instruction: format into a clean professional layout, add nothing.
   (Same design principle as the family-communication-engine build: keep
   deterministic work in Python, use the LLM for exactly one job at a time.)
3. `cmd_verify()` scans the generated `disclosure.html` for waiver/liability/
   release/authorization language, sentence-by-sentence, negation-aware — see
   `output/RECONCILIATION_REPORT.md` for the real bug this caught in the
   verifier itself during testing, and how it was fixed.
4. `cmd_export()` renders all three to PDF via `soffice --headless`.

## Run it

```bash
export SUPERDOCS_API_KEY=sk_...
python bgcheck_generator.py generate   # calls SuperDocs, writes output/*.html
python bgcheck_generator.py verify     # PASS/FAIL on disclosure standalone-ness
python bgcheck_generator.py export     # output/*.pdf
python -m unittest tests/test_verify_stdlib.py -v   # 6 tests, all passing
```

## What strong looks like, mapped to what's actually here

- **Disclosure contains no unrelated clauses** — verified programmatically,
  not eyeballed. See `output/RECONCILIATION_REPORT.md` §3 for the real
  false-positive/fix cycle this went through.
- **Authorization and rights notice are separate documents** — three files,
  three PDFs, checked to exist independently.
- **Fictional test data throughout** — Northfield Logistics Inc., Clearwater
  Screening Services, candidate Jordan T. Ellis. No real personal data.

## What's not built (deliberate v1 cuts)

- Real CFPB-mandated Summary of Rights text — `rights_notice.html` is a
  clearly labeled placeholder; real use requires the actual published text
  and counsel sign-off.
- E-signature integration — outputs are hand-off-ready PDFs, not signed.
- State-specific disclosure variations (some states require additional
  disclosure language) — out of scope for this demo.
- Multi-candidate batch generation — this build handles one candidate; the
  family-communication-engine build (the companion Task 2 submission)
  demonstrates the batch/multi-record pattern instead, so it wasn't
  duplicated here.

## Files

```
bgcheck_generator.py           CLI: generate / verify / export
data/company.json              fictional employer + CRA
data/candidate.json            fictional candidate
data/disclosure_template.html  standalone disclosure
data/authorization_template.html   separate signed authorization
data/rights_notice_template.html   separate rights notice (placeholder text)
output/disclosure.{html,pdf}   live SuperDocs output, verified clean
output/authorization.{html,pdf}
output/rights_notice.{html,pdf}
output/RECONCILIATION_REPORT.md  field-merge + verification evidence
tests/test_verify_stdlib.py    6 stdlib tests, all passing
```
