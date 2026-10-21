# Fidelity and Surgical-Change Verification — Method

This document describes `src/fidelity/`: the layer that proves, with
measurable evidence rather than assertion, that a SuperDocs export changed
only what an approved proposal authorized. It answers four questions with
evidence, not narrative:

1. Did only the intended rate-table sections change?
2. Did negotiated clauses (notice periods, pricing-lock language, mutual
   consent, governing law, etc.) stay untouched?
3. Did excluded contracts (pricing-lock, mutual-consent, requires-review)
   ever get amended?
4. Were approved and rejected proposals actually respected separately?

## Why this can't be a byte-diff

`export_document` (`src/integrations/superdocs_client.py`) only ever
returns markdown, html, or txt — this app never round-trips a real DOCX
package (no `word/document.xml`, no header/footer/footnote parts, no
`docProps` revision metadata). Even so, a raw string diff of "original file
on disk" vs. "exported text" is not a meaningful fidelity signal on its
own: trailing whitespace, re-serialized table formatting, or SuperDocs
re-rendering an untouched paragraph with different inline styling would all
show up as differences despite changing nothing a human reviewer cares
about. So every comparison in this package runs at two levels:

- **Byte level** — `original_text == exported_text`, tested directly and
  reported as `byte_identical: true/false`. Never inferred, never assumed.
- **Structural level** — both documents are parsed into a `DocumentModel`
  (`src/fidelity/document_model.py`): headings (with position, for section
  order), paragraphs (with nearest-heading context), tables (header row +
  per-cell values), and any inline style markers found. Structural diffing
  is what actually answers "did the rate table change and nothing else."

## The four identity tiers

Computed in `src/fidelity/compare.py::compare_documents`, in this strict
order — a tier is claimed only once its specific check has actually run
and passed, never inferred from a weaker signal:

| Tier | Meaning | Test performed |
|---|---|---|
| `byte_identical` | The exported text is byte-for-byte the same string as the original. | Direct string equality. |
| `structurally_identical` | Raw bytes differ, but every structural facet (headings, paragraphs, tables, styles) parses to the identical value. | Field-by-field `DocumentModel` equality. |
| `semantically_unchanged` | Structural facets differ, but every difference is attributable to an **approved** `IntendedEdit`'s old/new fragment. Non-target text, other tables, headings, and section order are unchanged. | Per-diff classification (see below); tier holds iff `unintended_diff_count == 0` and at least one facet actually differs. |
| `not_verified` | None of the above holds — at least one difference exists that cannot be attributed to an approved change. | Any diff with `classification: unintended`. |

`not_verified` is also the correct (and only honest) label whenever a
requested facet cannot be checked at all for the document's format — see
"Facets this format cannot check" below — rather than silently reporting
a pass for something that was never actually tested.

**This module never claims `byte_identical` unless the two full strings
were actually compared with `==`.** There is no shortcut path (e.g. "no
approved changes, so it must be identical") that produces this verdict
without running the check — see `case_fidelity.build_excluded_contract_report`,
which passes the same original text as both "original" and "exported" for
excluded contracts specifically so the byte check is real, not assumed.

## Facets compared

Per the required list, each is a distinct comparison in
`compare.py`, and each has a `FacetCheck` entry in the report so a reader
can see what was and wasn't actually verified:

| Facet | How it's compared | Status for markdown/html/txt |
|---|---|---|
| Body paragraphs | Set/positional diff of `DocumentModel.paragraphs`, each paragraph's text normalized (whitespace-collapsed) before comparison. | `checked` |
| Tables | Header row + full cell grid (`row, col -> text`) diffed per table index. | `checked` |
| Styles | Inline `style="..."` attribute values found in HTML exports (informational only — SuperDocs is documented to re-render approved-edit HTML with its own inline styling, so a style-only delta is never itself classified `unintended`). | `checked` |
| Headers (page headers) | N/A for this app's export path — see below. | `not_applicable` |
| Footers (page footers) | N/A for this app's export path — see below. | `not_applicable` |
| Footnotes | N/A for this app's export path — see below. | `not_applicable` |
| Section order | Sequence of heading texts, compared as an ordered tuple; a removed heading is always `unintended`, an added heading is `intended` only if its text is attributable to an approved edit's new fragment. | `checked` |
| Non-target text | Every paragraph/heading/table cell that is *not* covered by an approved edit's fragment — proven unchanged by simple absence from the diff list, not by a separate mechanism. | `checked` |
| Target rate cells | Table cells whose old or new value matches an `IntendedEdit`'s `old_fragment`/`new_fragment` — the literal SuperDocs proposal payload, not a re-derived guess. | `checked` |

### Facets this format cannot check

Headers, footers, and footnotes are OOXML/DOCX **package parts**
(`word/header1.xml`, `word/footer1.xml`, `word/footnotes.xml`) — concepts
that simply do not exist in a markdown, HTML, or plain-text export. Rather
than silently skip them (which would look identical in a report to "checked
and found no differences"), `DocumentModel.headers/footers/footnotes` are
always populated with a `SectionCheck(status="not_applicable", reason=...)`
— `SectionCheck.__post_init__` refuses to construct a `not_applicable`
value with no `reason`, so this can never degrade into a silent skip.

If this app is ever extended to compare true DOCX exports (via
`request_download_url`, referenced but out of scope in the README), a
DOCX-native parser (e.g. `python-docx`) can construct a `DocumentModel`
with those three fields populated for real — nothing else in
`src/fidelity/` assumes the markdown/html parser is the only producer of a
`DocumentModel`.

## Where "intended" comes from

`src/fidelity/intended_edits.py::derive_intended_edits` is the single
source of truth for "what was supposed to change." It reads directly off
an `AmendmentCase`:

- `case.pending_changes` — the literal `old_html`/`new_html` fragments
  SuperDocs proposed, keyed by `change_id` and `chunk_id`
  (`src/integrations/superdocs_client.py::ProposedChange`).
- `case.approvals` — the per-`change_id` human decision recorded by
  `src/amendment_case.py::record_decision`.

Every pending change becomes exactly one `IntendedEdit`, tagged
`approved` / `rejected` / `unresolved`. Only `approved` edits set
`should_appear_in_export = True`. This is deliberate: a fidelity check that
derived "intent" from the exported document itself (e.g. "assume any
change matching the AI's explanation was fine") would be circular — it
would validate the export against a description of itself rather than
against the actual human decision. The classifier in `compare.py` only
ever matches a diff against **approved** fragments
(`_classify(..., approved_only=True)`); a rejected or still-unresolved
change's fragment is never treated as license for a diff to appear.

## Classifying a diff as intended vs. unintended

For every structural difference between original and exported documents,
`compare.py::_classify` asks: does the exported (or original) value
correspond to the `old_fragment`/`new_fragment` of an **approved**
`IntendedEdit`? If yes → `intended`, with `matched_change_id` recorded. If
no → `unintended`. This means:

- A rejected change's rate appearing in the export anyway is `unintended`
  (nothing licenses it — `should_appear_in_export` is `False`, so the
  matcher never even considers it a candidate). See
  `tests/fidelity/test_compare.py::TestUnintendedChangesAreCaught::test_rejected_change_appearing_in_export_is_flagged_unintended`.
- An edit to a negotiated clause (notice period, pricing-lock text, etc.)
  that was never part of any proposal is `unintended` by construction — no
  `IntendedEdit` fragment can match it, approved or not.
- A heading/section **removed** from the export is always `unintended`,
  regardless of any approved edit elsewhere — approving a rate-table change
  never licenses deleting unrelated content.
- A **new** heading (e.g. SuperDocs adding a "Schedule A — Rate Card"
  section that didn't exist before) is `intended` only if its text is
  attributable to an approved edit's fragment; otherwise `unintended`.

## Excluded contracts

Pricing-lock, mutual-consent, and requires-review contracts never open a
SuperDocs session at all (`src/amendment_case.py::build_case`) — the
"export" for these is, by construction, the original file, byte for byte
(see `app/backend/routes/results.py`'s fallback path). This is exercised
directly rather than assumed:
`case_fidelity.build_excluded_contract_report` runs the *same*
`compare_documents` byte/structural checks with `original_text` passed as
both sides, so `byte_identical: true` is a real, tested result for these
cases too, and `excluded_contract`/`excluded_reason` are carried in the
report so a reviewer can see *why* no edit was expected — not just that
none occurred.

## Approved vs. rejected, kept separate

`record_decision` (`src/amendment_case.py`) stores one boolean per
`change_id`, independently. `derive_intended_edits` reads that map
directly — there is no aggregation step that could blur "3 of 4 approved"
into "mostly approved." A fidelity report for a partially-approved case
lists every pending change with its individual disposition
(`intended_edits_considered` in the JSON report), so a reviewer can confirm
the approved subset committed and the rejected subset did not, per change,
not in aggregate.

## Reports

`src/fidelity/report.py` renders a `FidelityReport` two ways:

- **Machine-readable** (`to_json`/`write_json_report`) — the full
  `FidelityReport.to_dict()`: verdict, byte/structural hashes, every
  facet check with its status and reason, every diff with its
  classification and matched change id, and the full intended-edit list
  with dispositions. Suitable for CI assertions
  (`report["is_surgical"] is True`) without re-running the comparison.
- **Human-readable** (`to_markdown`/`to_html`) — the same data as tables:
  verdict banner, facet-check table, intended-edits table, and two diff
  tables (unintended first, since that's what a reviewer needs to see
  immediately; intended second, for audit completeness).

`src/fidelity/case_fidelity.py::write_case_fidelity_artifacts` writes all
three formats (`.fidelity.json`, `.fidelity.md`, `.fidelity.html`) for one
case under a given directory — see `artifacts/fidelity-report/` for a
generated example (`sample_case_01_northstar.*`) built from a
partially-approved Northstar case (US rate approved, UK rate rejected).

## Tests

`tests/fidelity/` proves the method against both hand-built fixtures and
real `AmendmentCase` objects built the same way
`tests/unit/test_amendment_case.py` does:

- `test_document_model.py` — structural parser correctness (headings,
  paragraphs, tables, not-applicable facets) for markdown, html, and text.
- `test_compare.py` — diff classification and verdict-tier logic in
  isolation, using hand-built `IntendedEdit`s.
- `test_case_fidelity.py` — the four required end-to-end guarantees:
  - `TestRejectingEveryProposalLeavesContentUnchanged` — an all-rejected
    case's export is `byte_identical` to the original.
  - `TestApprovingOneRateTableDoesNotChangeAnotherSection` — approving one
    destination row's rate change leaves the other row and every
    negotiated clause (Article 1, Article 7's notice text) absent from the
    diff list entirely.
  - `TestPricingLockContractsProduceNoEditedExport` — cases 3 (pricing
    lock) and 4 (mutual consent) never open a SuperDocs session and their
    fidelity report is `byte_identical`.
  - `TestOnlySelectedProposalsAreCommitted` — a correct mixed-decision
    export is surgical; a *defective* one where the rejected change leaked
    through is caught as `unintended` and drops the verdict to
    `not_verified` — proving the classifier actually discriminates,
    not just that a happy-path export passes.
