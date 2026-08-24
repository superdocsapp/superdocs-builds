# Development Log

Built in one session against the Back-Translation Drift Check spec
(SuperDocs Open Task, Band S3). Order of work, and the two real bugs caught
along the way — kept because "what broke and how it was caught" is more
useful to a future maintainer than a changelog of what went right.

1. **Environment check first.** No existing repository, no
   `ANTHROPIC_API_KEY`. Decided offline-first: `FixtureProvider` as the
   verified path, `AnthropicProvider` fully implemented but disclosed as
   live-unverified (LIMITATIONS.md #5) rather than faked.

2. **Data model, integrity, parsing, alignment** — the parts with zero AI
   involvement — built first, since everything else depends on them.

3. **Deterministic signal detectors, sanity-checked against the spec's own
   worked examples before anything else was built on top of them.** This
   caught a real bug immediately: `"30 days" → "60 days"` was classified as
   `unit_change` instead of `numeric_change`, because the unit-quantity
   token path defaulted to `UNIT_CHANGE` regardless of whether the unit
   actually changed. Fixed before the provider layer, drift engine, or any
   test existed — cheaper to catch here than after the pipeline was wired
   up. A second bug (`"thirty days"` vs `"30 days"` not comparing equal,
   because only digit-form numbers were binding to a following unit word)
   was caught the same way, same session.

4. **Provider abstraction.** First draft had `deterministic_signals` as an
   *input* to the provider call, intended to give the LLM context. Caught
   before writing `pipeline.py`: this is circular (signals are computed
   from the back-translation the provider call produces) and, worse, would
   have meant the semantic layer was primed by the deterministic layer
   before "corroborating" it, which defeats the point of having two
   independent checks. Removed the parameter; the two passes now run fully
   independently and are combined afterward in `drift_engine.py`. See
   DECISIONS.md #8.

5. **Severity/review-status policy.** First instinct was to cap AI-only
   findings at MEDIUM severity, to operationalize "the LLM must not be the
   sole authority." Reconsidered before implementing: that would mean a
   genuinely critical AI-only finding (the flagship demo's capillary/venous
   case) could get triaged away by a reviewer skimming for CRITICAL rows.
   Implemented instead as a stricter starting review state
   (`REVIEW_REQUIRED` vs `PENDING_REVIEW`) with severity left on its
   merits. See DECISIONS.md #4.

6. **Pipeline, correction generation, review workflow, audit trail, report
   generation (Markdown/JSON/HTML), CLI.**

7. **Flagship demo fixture authored** (English source / Spanish target, 12
   sections: all 10 spec-required seeded cases + 2 bonus sections
   demonstrating dual-signal corroboration and semantic-only detection) and
   run end to end for the first time. All 10 required cases and both PASS
   cases landed exactly where seeded on the first full run.

8. **Second, unrelated document authored** (English/French, HR domain) and
   run to confirm the pipeline generalizes.

9. **Test suite written against the now-working implementation**, covering
   every canonical example the spec gives directly, the mandatory
   deliberate mutation test, resumability after a simulated failure,
   idempotency, prompt-injection resistance, and report correctness. First
   run: 55/57 passing. Two failures, both real:
   - `review.edit()` tried to mutate `ProposedCorrection.suggested_text`,
     which is a frozen dataclass — `FrozenInstanceError`. Fixed by not
     mutating it at all: the system's original proposal stays on the
     finding, the reviewer's final text lives on the `ReviewDecision`
     returned by `edit()`. Better audit trail than the original design,
     not just a workaround.
   - The prompt-injection test asserted the wrong thing (expected a
     genuinely-passing section to be `PENDING_REVIEW` when a PASS with no
     proposed correction is correctly `APPROVED` by design). Rewrote the
     test to check what actually matters: a section with *real* drift is
     unaffected by another section's injected content, and the "approved"
     PASS carries no correction for that approval to apply to.

10. **Typecheck and lint.** mypy clean after fixing a module-resolution
    config issue (`--explicit-package-bases`) and removing 5 stale `type:
    ignore` comments the earlier fixes had made unnecessary. Ruff clean
    after two real fixes (unused import, `zip()` without `strict=`) and one
    config change (line-length 100→120, since the majority of remaining
    flags were CSS-in-Python-string and docstring lines where mechanical
    wrapping would hurt readability, not real issues).

11. **Documentation, final full-suite re-run, packaging.**

## Pre-submission audit pass

A second pass, framed as a production pre-submission audit, surfaced three
real gaps and one real security check worth verifying directly rather than
assuming:

12. **Finding aggregation.** Two numbers in one temperature range both
    having their unit swapped, or a protected-term miss and a
    capitalized-phrase-heuristic miss both pointing at one altered entity,
    were being reported as separate findings — technically accurate, but
    inflating the count for what's actually one underlying problem.
    `drift_engine` now groups same-category deterministic signals into one
    finding with multiple evidence items before construction; different
    categories are never merged. Flagship demo finding count dropped from
    15 to 13, both drops accounted for by name (Sections 9 and 10). See
    DECISIONS.md #10.

13. **Unit-conversion policy — a real false-positive/false-negative gap.**
    The unit-change detector compared unit tokens as raw strings with no
    concept of whether the underlying value represented the same physical
    quantity. That meant a translator correctly localizing "2°C" to
    "35.6°F" would have been flagged identically to the dangerous bug of
    leaving "2°C" as "2°F" — a real false positive on legitimate
    localization, sitting right next to a real false negative risk if the
    policy had instead been "unit changed = always fine." Implemented an
    explicit conversion table with a rounding tolerance: legitimate
    conversions pass, incorrect conversions are flagged CRITICAL with the
    expected value shown, and unit pairs outside the table are flagged for
    review rather than guessed at either direction. See DECISIONS.md #11.

14. **SuperDocs integration seam.** The first pass documented the absence
    of SuperDocs credentials/API spec and stopped there — no adapter code
    existed at all. Added `superdocs.py`: the operations a real integration
    needs (upload, propose-edit, record-review-decision, export) as a
    Protocol, with a `LocalSuperDocsAdapter` implementing them against the
    filesystem, and `credential_status()` reporting `PENDING_NOT_CONFIGURED`
    unconditionally — never inferring "configured" from environment
    variables that were never exercised against a real endpoint. See
    DECISIONS.md #12.

15. **HTML escaping — verified directly, not assumed.** Every
    finding-derived string in `report.py` already passed through `_esc()`,
    but "the code looks like it escapes everything" isn't the same claim as
    "it does." Ran an actual XSS-payload round trip through `report.to_html()`
    — script tags and an `onerror` handler embedded in source text, target
    text, back-translation text, and even the CLI `run_id` — and confirmed
    the payloads appear only as escaped, inert text, never as a live tag.
    Kept as a permanent regression test
    (`test_html_escaping_and_size_limits.py`) rather than a one-off check.

16. **README rewritten and restructured** per the audit's requested flow
    (problem → architecture → detection model → safety guarantees → human
    review → SuperDocs → testing → demo → running instructions), and the
    development-tooling disclosure removed from it — a normal scoping
    choice for a README, distinct from the technical-limitation disclosures
    (what's live-verified vs. not) in LIMITATIONS.md, which were left
    exactly as accurate as they were.

Net result: 57 tests → 83 tests → 84 tests → 87 tests, all passing; mypy and ruff clean; flagship
and second-document demos re-verified end to end after every change above.

## Third pass — correctness/documentation audit only

Scoped explicitly to verifying every claim in the documentation against
actual behavior, not redesigning anything. Found two more real issues, both
caught by actually running things rather than reading the code and
assuming it matched the docs:

17. **HTML report section-numbering bug.** The report's "§N" card label was
    the finding's position in the flattened, severity-sorted list
    (`enumerate`), not its actual document `section_index`. Invisible as
    long as every section produced at most one finding — but Section 11
    legitimately produces two (a modal change and a qualifier change,
    different categories, correctly never merged), which pushed every
    subsequent card's label out of sync by one. The semantic-only Section
    12 finding was displayed as "§13" in a document that only has 12
    sections. Fixed by labeling each card with `f.section_index` directly.
    Caught by regenerating the actual HTML and grepping for the label, not
    by reading the template and assuming it matched; kept as a permanent
    regression test asserting the full displayed label set equals `{1..12}`.

18. **The documented CLI command didn't reproduce the documented demo.**
    README's "Running it" section instructs `drift-check run --provider
    fixture --fixture-file fixtures/flagship/back_translations.json`.
    Running that exact command showed 4 critical / 3 pass findings, not the
    5 critical / 2 pass every other doc describes — because
    `FixtureProvider.from_json_file` only ever loaded back-translation text;
    the two hand-authored semantic overrides that make Section 11's
    corroboration and Section 12's semantic-only detection work lived only
    in `scripts/demo_providers.py`, which the CLI never touches. The
    documented command silently produced a materially weaker result than
    what the rest of the repository describes. Fixed by extending the
    fixture JSON format to optionally carry `semantic_overrides` alongside
    `back_translations`, moving the two overrides into
    `fixtures/flagship/back_translations.json` itself, and simplifying
    `demo_providers.py` to a thin wrapper around the same file — the CLI and
    the Python helper are now provably the same code path (see
    `test_cli_only_path_reproduces_the_same_flagship_result_as_the_python_helper`),
    not two paths that happened to agree by coincidence. The second
    document's fixture file was deliberately left in the old flat format,
    to keep proving that simpler format still works.

19. **"Self-contained" was an overclaim.** The HTML report's CSS loads
    decorative webfonts from Google Fonts over the network; it degrades
    correctly to system fonts if offline (every `font-family` declaration
    has a generic fallback), but it is not free of any external dependency
    in the strict sense the README asserted. Reworded to state exactly
    what's true.

Also re-verified during this pass and found already correct: finding
aggregation, the unit-conversion policy, source immutability, translation-
only correction targeting, severity counts summing to the finding total,
second-document independence from any flagship-specific code path, and that
no SuperDocs claim anywhere implies a live connection.

Net result: 87 tests, all passing; mypy and ruff clean; the documented CLI
command now produces the documented result, verified by actually running it.

## Fourth pass — a reported Python 3.14 discrepancy, and Ruff cleanup

A report came in of the parity test
(`test_cli_only_path_reproduces_the_same_flagship_result_as_the_python_helper`)
failing on a fresh Python 3.14.3 venv with 4 critical findings instead of 5,
everything else (86/87 other tests, mypy, ruff's 23 line-length findings)
matching exactly.

Investigated rather than dismissed or patched around:

- 20 isolated repetitions plus the full 87-test suite run under 4 different
  `PYTHONHASHSEED` values (5 full-suite runs total) — zero failures, zero
  variance, in this environment (Python 3.12.3).
- Hand-traced `FixtureProvider.from_json_file` → `_parse_semantic_override`
  → `analyze_section_pair`'s corroboration branch → `_finding_from_semantic`
  line by line; the logic that would need to be wrong to drop exactly one
  critical finding (Section 12's semantic-only override failing to apply)
  did not reveal a bug.
- Inspected the fixture JSON's raw bytes directly (no BOM, correct UTF-8,
  `json.loads` reproduces the exact intended structure).
- Searched for documented Python 3.11–3.14 behavior changes to `enum`,
  `dataclasses`, and `json` that could plausibly explain a 3.12-vs-3.14
  divergence specifically. Found one real, documented `str`+`Enum` mixin
  change — but it landed in 3.11, so it's already in effect in this
  environment's 3.12 too and can't explain a 3.12-vs-3.14 gap. Found a
  documented 3.13 dataclass `__eq__` optimization change, but it only
  affects fields whose `__eq__` doesn't return a plain bool (e.g. numpy
  arrays) — none of this codebase's dataclass fields do.
- Attempted to obtain an actual Python 3.14 interpreter to test directly
  (apt has no package for it on this base image; the GitHub API for
  standalone-build releases was rate-limited; guessing release tags for a
  direct download 404'd). Could not get one in this sandbox.

Did not find a reproducible root cause, and did not change the expected
value on that basis — the evidence for `5` (both the design intent and
every local run) is stronger than the evidence for `4` (which currently
consists of one report I could not independently reproduce). What *did*
come out of the investigation, kept regardless of root cause:

20. **The parity test itself was hiding information.** It asserted inside
    a loop over both providers, so a failure on the first provider meant
    never learning whether the second one also failed — precisely the
    ambiguity that made this report hard to localize. Rewrote it to run
    both providers to completion first, build a full per-section
    `(severity, category)` breakdown for each, and assert on that
    structured breakdown with both providers labeled in any failure
    message — including an explicit "helper vs. cli_path" diff. If this
    recurs, the new version's output will show exactly which section and
    category diverges, which the old version's plain count never could.

21. **All 24 Ruff `E501` findings fixed by wrapping, none suppressed.** No
    `noqa`, no config-level rule disabling, no line-length increase this
    pass (120 was already set intentionally in an earlier pass). Every
    fix is either: Python line-wrapping with zero behavior change, or —
    for the one CSS `@import` line pulling three Google Fonts families
    through one query string — splitting it into three separate `@import`
    statements, which is standard, equivalent CSS. Verified the regenerated
    HTML report still contains all three font imports and all 12 section
    labels after the change.

If this recurs on an actual 3.14 environment, running the rewritten test
there and sharing its output (specifically which of `by_section_helper` /
`by_section_cli_path` differs, and at which section) would supply the one
piece of information this investigation could not obtain locally.
