# Domain Model — Telecom Contract-Analysis Core

This document describes the shared, UI-independent core in `src/` that analyzes
the synthetic telecom fixture corpus in `fixtures/`. It is a pure Python
package: no network calls, no live model key required, fully testable offline.

## Package Layout

```
src/
  domain/        typed dataclasses shared by every pipeline stage
  extraction/     steps 1-6: classification, text/table reading, metadata,
                  rate tables, amendment-clause location
  rules/          steps 7-12: deterministic decision rules (notice period,
                  pricing lock, mutual consent, effective date, conflicts,
                  eligibility)
  reporting/      steps 13-14: amendment-letter data prep, control report
  pipeline.py     wires steps 1-13 together for a single contract
tests/
  unit/           fixture-driven tests, no live model key needed
  fixtures/       (reserved for test-local fixtures; corpus lives in /fixtures)
docs/
  DOMAIN_MODEL.md this document
```

## Design Invariants

These rules are enforced by construction, not by convention:

1. **Uniform provenance.** Every extracted fact carries a `SourceCitation`:
   `document_id`, `section`/`page` (where available), `source_span` (quoted
   or normalized), `confidence` (validated to `[0, 1]` in
   `SourceCitation.__post_init__`), and `extraction_method`
   (`deterministic_rule` / `model_reasoning` / `fixture_recorded`).
2. **Unsupported facts stay `None`.** Nothing is guessed to fill a gap. See
   `NoticeRequirement.notice_period_days` for case 5, where the contract
   states only "a commercially reasonable period" — the field stays `None`
   and the qualitative text is preserved in `notice_period_type` instead.
3. **Low-confidence and conflicted inputs become `requires_review`.**
   `rules/eligibility.py` treats any unresolved `Conflict`, dependency on an
   unattached document, or a notice-extraction confidence below 0.5 as an
   automatic escalation — never a best-guess approval or denial.
4. **Pricing-lock and mutual-consent cases never generate contract edits.**
   `reporting/amendment_letter.py` returns `AmendmentLetterData(blocked=True,
   ...)` with every proposal field `None` whenever
   `EligibilityDecision.status != EligibilityStatus.ELIGIBLE`. There is no
   code path from a locked or consent-required contract to a populated
   amendment letter.
5. **Document text is never treated as instructions.** Contract text is only
   ever read as a plain Python string passed into regex-based extractors —
   it is never interpolated into a prompt or used as control flow. The one
   embedded instruction-like string in the corpus
   (`fixtures/contracts/contract_05_pelagic.md`) is detected by
   `rules/conflicts.py::has_prompt_injection` and surfaced only as a
   `Conflict` / reviewer note (`EligibilityDecision.prompt_injection_note`).
   It cannot and does not change the eligibility branch taken —
   `rules/eligibility.py` never inspects the injection match itself, only
   the independent, legitimate ambiguities (unattached documents, reserved
   clauses, unresolved conflict-of-interpretation).
6. **Deterministic rules run separately from model reasoning.** Everything
   under `src/rules/` and `src/extraction/` is regex/parsing logic with zero
   dependency on any model client. `tests/unit/test_domain_model_invariants.py`
   asserts this by AST-scanning `src/rules/*.py` for banned imports. A
   `ExtractionMethod.MODEL_REASONING` value exists in the enum for future
   stages that do call a model, but no current stage sets it — every fact
   produced by this package today is `deterministic_rule` (or
   `fixture_recorded` for facts read directly off a recorded fixture).

## Domain Models (`src/domain/models.py`)

| Model | Purpose |
|---|---|
| `DocumentReference` | Identifies a corpus document (id, path, type). |
| `SourceCitation` | Uniform provenance envelope attached to every fact. |
| `PartnerContract` | Partner/our-entity names, contract date/identifier, governing law. |
| `RateEntry` | One destination row from a rate card (old or new). |
| `PricingClause` | The clause(s) governing rate amendments, with supporting clause list. |
| `NoticeRequirement` | Notice-period days/type, delivery method, objection window. |
| `Conflict` | An unresolved internal conflict, unattached-document dependency, or logged injection note. |
| `EligibilityDecision` | Final eligible / not_eligible / not_eligible_unilaterally / requires_review determination. |
| `ProposedRateChange` | Old-vs-new rate delta for a destination (rate-card comparison). |
| `AmendmentLetterData` | Fields to populate the amendment-letter template, or a `blocked` reason. |
| `ControlReportRow` | One row of the aggregate corpus-wide control report. |

## Pipeline Stages

| # | Stage | Module | Function |
|---|---|---|---|
| 1 | Document classification | `extraction/classification.py` | `classify_document` |
| 2 | Text/table extraction | `extraction/text_extraction.py` | `extract_document_text`, `extract_csv_table` |
| 3 | Partner/contract metadata | `extraction/metadata.py` | `extract_partner_contract` |
| 4 | Rate-table identification | `extraction/rate_tables.py` | `identify_rate_table` |
| 5 | Old-rate extraction | `extraction/rate_tables.py` | `extract_old_rates` |
| 6 | Amendment-clause identification | `extraction/clauses.py` | `find_amendment_clause_block`, `extract_pricing_clause` |
| 7 | Notice-period extraction | `rules/notice_period.py` | `extract_notice_requirement` |
| 8 | Pricing-lock detection | `rules/pricing_lock.py` | `detect_pricing_lock` |
| 9 | Mutual-consent detection | `rules/mutual_consent.py` | `detect_mutual_consent` |
| 10 | Effective-date validation | `rules/effective_date.py` | `validate_effective_date` |
| 11 | Conflict detection | `rules/conflicts.py` | `detect_conflicts`, `has_prompt_injection` |
| 12 | Eligibility decision | `rules/eligibility.py` | `decide_eligibility` |
| 13 | Amendment-letter data prep | `reporting/amendment_letter.py` | `prepare_amendment_letter_data` |
| 14 | Control-report generation | `reporting/control_report.py` | `generate_control_report` |

`pipeline.py::analyze_contract(file_path, reference_date)` runs stages 1-13
over a single contract and returns a `ContractAnalysis`. Stage 14 operates
over a list of already-analyzed contracts (see
`tests/unit/test_clause_and_control_report.py` for an example driver).

## Why clause-location is per-document

The fixture corpus was deliberately built with five structurally distinct
numbering conventions (`Article N.N`, `SECTION N(a)`, plain `N.N` under a
Recitals header, `Clause I.N`/`Clause II.N`, and `§N.N`) specifically so a
pipeline cannot pattern-match on one fixed layout
(see `docs/FIXTURE_DESIGN.md`). `extraction/clauses.py` therefore matches
each of the five heading conventions independently and picks whichever
heading's text matches amendment/pricing keywords, rather than assuming one
canonical structure.

## Testing Without a Live Model Key

Every extractor and rule in this package is a pure function over a string of
already-read document text — there is no model call anywhere in
`src/extraction/` or `src/rules/`, so `tests/unit/*.py` runs fully offline
against the fixture corpus and `fixtures/expected_results.json` as ground
truth. `tests/conftest.py` pins the evaluation reference date to
`2025-08-06` (matching `expected_results.json`'s
`evaluation_assumptions.reference_evaluation_date`) rather than reading
`date.today()`, so the pricing-lock-expiry test for case 3 is deterministic
and reproducible regardless of when the suite is actually run.
