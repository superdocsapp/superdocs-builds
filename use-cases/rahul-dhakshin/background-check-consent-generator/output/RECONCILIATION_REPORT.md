# Reconciliation Report — Background-Check Consent Generator

All three documents below were generated live against the real SuperDocs API
(`POST https://api.superdocs.app/v1/chat`), not simulated. Field values come
from `data/company.json` and `data/candidate.json` (fictional test data:
Northfield Logistics Inc., Clearwater Screening Services, candidate Jordan T.
Ellis).

## 1. Field-merge verification

Every `{{field}}` placeholder in the three templates was deterministically
replaced by `merge_fields()` (plain Python string replace, no LLM involved)
before the SuperDocs call. Confirmed by inspecting each output for leftover
`{{` markers — none found.

| Field | Value | Appears in |
|---|---|---|
| company_name | Northfield Logistics Inc. | disclosure, authorization |
| cra_name | Clearwater Screening Services | disclosure, authorization |
| position_title | Warehouse Operations Supervisor | disclosure, authorization, rights_notice |
| candidate_name | Jordan T. Ellis | authorization, rights_notice |
| application_date | August 6, 2026 | authorization |

## 2. What SuperDocs was asked to do, and what it actually did

Each merged document was sent with one instruction: *"Format this document
into a clean, professional layout... Do not add any additional clauses,
waivers, releases, liability language, or any sentence not already present
below... formatting only."*

SuperDocs returned each document restructured into headed sections with
inline styling (`data-chunk-id` grounding on every paragraph, its per-chunk
tracking mechanism) — and, checked sentence-by-sentence against the source
templates, added no new sentences or clauses to any of the three documents.
It reorganized the *disclosure* into four subsections (Consumer Report
Disclosure / Background Information / Your Rights / Disclosure Statement)
and gave *rights_notice* card-style visual grouping, but the wording of every
existing sentence was preserved verbatim.

## 3. Finding: the disclosure stayed genuinely standalone — but proving that
   required fixing my own verification script, not just SuperDocs' output

`cmd_verify()` scans `disclosure.html` for waiver/liability/release/
authorization language — the exact failure mode the assignment brief calls
out (a disclosure that's no longer standalone because unrelated clauses got
mixed in). Running it against the live output initially **failed**:

```
FAIL: disclosure.html is no longer standalone. Found:
  - pattern '\bwaiv(e|er|ers|ing)\b' matched 'waiver'
  - pattern '\breleas(e|es|ed|ing)\b' matched 'release'
```

The match was this sentence, which is in the *original template*, not
something SuperDocs added:

> "This document is a disclosure only. **No release, waiver**, authorization,
> or other acknowledgment is contained in or attached to this document."

That's the disclosure correctly *asserting* it contains no such clauses — a
false positive from naive keyword matching that doesn't understand negation.
Fixed `cmd_verify()` to scan sentence-by-sentence and skip any match preceded
by a negation cue (`no`, `not`, `without`, `never`, `none`) earlier in the
same sentence. Re-ran:

```
PASS: disclosure.html contains no waiver/liability/release/authorization language.
Authorization and rights-notice content confirmed to live in separate files:
  - output/authorization.html: exists
  - output/rights_notice.html: exists
```

Added `tests/test_verify_stdlib.py` (6 tests, all passing) to pin this in
both directions: the negated template sentence must pass, and synthetic
sentences with a *real* (non-negated) waiver, release, liability, or
"I authorize" clause must still fail. This is a heuristic, not real NLP —
a real clause buried behind an unrelated negated word earlier in the same
sentence could still slip past it. Documented as a known limitation rather
than papered over.

## 4. Separation confirmed

- `disclosure.html` — contains only disclosure content, verified clean.
- `authorization.html` — separate file, contains the signature/authorization
  language (including "I authorize...", which is correctly *absent* from
  the disclosure).
- `rights_notice.html` — separate file, clearly labeled as a template
  placeholder pending the real CFPB-published text (see file header).

Three distinct files, three distinct PDFs, no cross-contamination.

## 5. Exports

`cmd_export()` converts each HTML file to PDF via `soffice --headless`
(same tool used in the family-communication-engine build, for the same
reason: pandoc's LaTeX path doesn't handle this cleanly, and PDF is the
expected hand-off format ahead of an external e-signature step).

- `disclosure.pdf`
- `authorization.pdf`
- `rights_notice.pdf`
