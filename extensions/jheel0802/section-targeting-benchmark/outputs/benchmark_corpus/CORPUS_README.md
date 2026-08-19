# SuperDocs Section-Targeting Benchmark Corpus

## Purpose

This frozen corpus supports manual evaluation of whether SuperDocs identifies the intended section when a document contains repeated headings, nested context, semantic references, historical material, appendices, or genuine ambiguity. It evaluates SuperDocs behavior; it is not a replacement targeting algorithm and contains no automatic judge.

## Composition

Version 1.0.1 contains 14 realistic professional Word documents and 40 cases. Each document is a genuine DOCX with machine-readable Heading 1 and Heading 2 structure, paragraphs, real Word lists, and tables where the artifact naturally calls for them. The same 14 fixed documents are reused across all cases; no per-case document variants exist.

The set includes account and status reports, a release plan, vendor evaluation, incident post-mortem, PRD, SOP manual, regional sales report, implementation plan, employment-policy manual, architecture specification, audit report, meeting summary, and multi-product release notes.

## Cases and difficulty

Cases are search/question or edit instructions. Difficulty is assigned from the targeting evidence available before execution:

- **Easy:** explicit parent and child heading; useful as a control.
- **Medium:** repeated templates or nearby related content with an explicit resolving clue.
- **Hard:** semantic, ordinal, relative-position, historical/current, appendix, or multi-clue resolution.
- **Adversarial:** genuine ambiguity or a plausible but absent target where confident action would be unsafe.

Difficulty describes targeting conditions, not an expected pass rate.

## Expected behaviors

- `unique_target`: one section path is correct.
- `acceptable_set`: more than one path may be defensible. Version 1.0.1 defines the representation but contains no pure acceptable-set case; ambiguous cases require clarification instead.
- `should_clarify`: SuperDocs should seek missing scope rather than choosing silently. Each rationale states what counts as Pass, Fail, and Ambiguous.
- `no_target`: the requested specific section or commitment does not exist. Pass means the system says so and does not silently modify unrelated content; a clearly qualified related suggestion is acceptable.

## Ground truth

`benchmark_manifest.json` is authoritative. The CSV is a flat interchange copy. Each case records its instruction, expected behavior, target path or acceptable paths, expected search answer or edit scope, sections that must not be targeted, capability, likely failure category, rationale, fixture version, and source-document SHA-256.

No case IDs, expected answers, target labels, distractor labels, or benchmark annotations appear inside the DOCX files.

## Freezing and versioning

All fixtures are frozen at `fixture_version: 1.0.1`. This patch removes shared template prose without changing headings, benchmark facts, targets, distractors, or case mappings. SHA-256 values in the manifest and validation report identify the exact bytes. Do not silently modify a fixture after collecting results. A content or structural change requires a version bump, a new hash, and an explicit list of affected cases.

## Validation

Run with the bundled/runtime Python environment containing `python-docx`:

```bash
python validate_corpus.py
```

The script checks document count and readability, real heading structure, manifest references, unique and acceptable paths, repeated-heading conditions, required negative paths, search-answer evidence, no-target absences, metadata leakage, required case fields, ID uniqueness, case count, per-document case count, fixture hashes, and distributions. Results are written to `validation_report.json`.

The DOCX files were also rendered to page images and visually inspected for legibility, hierarchy, spacing, table behavior, and benchmark invisibility.

## Using the existing harness

Upload one file from `documents/` once, then create the three manifest cases with the same document selection. Persist ground truth before running. Map `instruction`, `expected_section_path`, `expected_answer`, and `expected_edit_scope` into the corresponding case fields; keep the remaining manifest metadata alongside the run for adjudication. Do not approve proposed edits merely because a benchmark verdict is saved.

The current harness does not bulk-import this richer manifest. Import can be done manually without changing the platform, or via a future dedicated ingestion step after review.

## Known limitations

- The corpus is synthetic and English-language; it does not measure OCR, multilingual headings, or corrupted files.
- Heading depth is primarily two levels, even though the PRD and architecture documents use numbered hierarchy.
- Search answers are deterministic fixture facts, not an exhaustive factuality benchmark.
- Likely failure category is a design hypothesis; actual observed failures may use another taxonomy category.
- Some taxonomy categories have only one direct case, and `acceptable_set`, `under_targeting`, `over_targeting`, `unnecessary_clarification`, and `correct_section_wrong_edit_range` are weak or absent as primary labels. They remain valid adjudication categories but were not forced into artificial cases.
- No live SuperDocs request was made while generating or validating the corpus.
