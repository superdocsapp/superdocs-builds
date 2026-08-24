# Limitations

Numbered scope boundaries, stated explicitly rather than discovered by
surprise.

**1. Single-level sectioning.** Only `##` headings create section
boundaries; a `###` heading inside a section is body text, not a
sub-section. Documents that rely on deep hierarchical structure would need
the parser extended before this pipeline is meaningful for them.

**2. Deterministic detectors cover English source text only.**
`signals.run_all_detectors` takes a `language` argument and no-ops for
anything other than `"en"` rather than guessing with English marker tables
against non-English text. Both demo documents have English as the source
language, so this isn't exercised as a gap in this build, but a document
whose *source* language isn't English would currently get semantic-layer
coverage only, with no deterministic corroboration. Adding a language means
adding a new marker table, not restructuring detection logic.

**3. Numeric/date alignment within a section is positional, not semantic.**
Tokens of the same kind (all dates, all percentages, ...) are compared in
order of appearance. This is accurate for the short, single-topic sections
this system targets, but a section with the same *value* appearing twice in
different roles (e.g. two independent "30 days" deadlines in one paragraph
that get transposed) would not be caught if the transposition preserves
order.

**4. Named-entity detection is exact-match + heuristic, not true NER.**
`protected_terms` gives high-precision, zero-recall-guarantee coverage (it
only ever fires on a term the caller explicitly listed). The capitalized-
phrase heuristic is a cheap proxy for "looks like a proper noun" and both
under- and over-fires by construction (documented as MEDIUM severity, lower
than a protected-term miss, specifically because it's a heuristic). General
open-domain entity recognition is exactly the kind of task pushed to the
semantic/AI layer rather than solved deterministically.

**5. `AnthropicProvider` is fully implemented but not live-verified.** No
`ANTHROPIC_API_KEY` was available in the environment this was built in. Its
HTTP request construction, retry/backoff, and response parsing (including
the malformed-response and unrecognized-category paths) are unit-tested
against a mocked HTTP layer in `tests/test_review_and_security.py`, and the
prompt/schema contract is exercised structurally, but an actual network
round-trip to `api.anthropic.com` has not been run. Every result presented
in this project (flagship demo, second document, all 87 tests) runs on
`FixtureProvider`, which requires no credentials — this is what "offline
tests must not require API credentials" means in practice here. Running
live is `--provider anthropic` with the key set; nothing else changes.

**6. Deterministic literal corrections exist only for numeric/date/
percentage/unit categories.** For modal, negation, qualifier, and
named-entity findings, the proposed correction is a precise natural-language
instruction, not auto-generated target-language prose — generating replacement
translation text automatically is the exact capability this tool is meant to
audit, not perform. See DECISIONS.md #9.

**7. Tier-3 "standout" features (spec section 25) are not built.**
Confidence-score UI polish beyond what's already surfaced, a dedicated
diff-visualization mode, reviewer filters, and a translation-memory-style
context store are all out of scope for this build. What's built covers the
spec's own Tier 1 and Tier 2 priority lists completely.

**8. No *live* SuperDocs platform integration.** `superdocs.py` implements
the adapter seam (`SuperDocsAdapter` protocol + `LocalSuperDocsAdapter`)
that every demo and test in this project actually uses, but no SuperDocs
API specification or credentials were provided or discoverable, and
"SuperDocs" does not correspond to any real, documented external platform
this environment has access to. Building a *live* client against an
undocumented/nonexistent API would mean fabricating a contract and,
implicitly, fabricating a verification result — which the spec itself
prohibits. `credential_status()` reports `PENDING_NOT_CONFIGURED`
unconditionally rather than inferring "configured" from environment
variables that were never actually exercised against a real endpoint.

**9. The unit-conversion table (°C↔°F, g↔kg↔mg, mL↔L, km↔miles) is
intentionally narrow.** These are the exact units the originating spec
names; adding another unit family (e.g. volume in cups/tsp, or pressure)
means adding one more formula to `_CONVERSION_TABLE`, not restructuring the
policy. A unit pair outside the table is never guessed at — it's flagged
for human review, which is the deliberately safe default for an unknown
conversion, not a gap that produces wrong answers silently.

**10. Word-number parsing (`thirty`, `twenty-one`) covers common English
constructions up to compound tens+ones; it does not handle every English
numeral phrase (e.g. "a dozen", "half a million").** Sufficient for the
"mixed numeral formats" robustness case in the spec's own test list
(`tests/test_signals_regression.py::test_mixed_numeral_formats_equal_value`),
not a general English-numeral parser.

**11. Date parsing covers `Month DD, YYYY`, `DD Month YYYY`, and ISO
`YYYY-MM-DD`.** Numeric-only date formats (`01/31/2027`) are deliberately
excluded rather than guessed at, since day/month/year ordering is
locale-ambiguous and a wrong guess would be worse than no detection.
