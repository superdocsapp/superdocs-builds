# Testing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . && pip install pytest mypy ruff
python -m pytest tests/ -q                                  # 87 tests
MYPYPATH=src mypy -p drift_check --explicit-package-bases    # typecheck, clean
ruff check src/ tests/ scripts/                              # lint
```

All 87 tests run against `FixtureProvider` — zero API credentials required,
zero network calls made, by construction (`FixtureProvider` has no HTTP
client in it at all).

## Coverage map

| File | Covers |
|---|---|
| `test_signals_regression.py` | Every canonical example the spec itself gives: both PASS cases (must/is-required-to, may/is-permitted-to synonyms, harmless reorder, punctuation variation, mixed numeral formats), both CRITICAL cases (must→may, must-not→may), the full modal transition matrix (must→should, must-not→may, may→must, shall-not→shall, required→recommended), numeric/percentage/date/unit change detection, qualifier weight tiers, negation reversal, protected-term matching |
| `test_integrity.py` | Hash determinism, verification on unchanged source, **the mandatory deliberate-mutation test** (spec section 9), section-level mutation detection independent of whole-document hash, confirmation the pipeline never opens the source file for writing |
| `test_pipeline.py` | Full flagship-demo run (all 10 seeded cases + 2 bonus sections asserted individually), full second-document run (proves generalization to a different domain and language pair), idempotency (identical finding IDs on a fresh rerun), **resumability after a simulated mid-run provider failure** (spec section 19), alignment edge cases (empty translation, section-count mismatch, duplicate headings, unicode, zero-section document) |
| `test_review_and_security.py` | Approve/reject/edit state transitions, re-review rejection, empty-edit rejection, semantic-only findings starting in the stricter review state, **prompt-injection resistance** (document content that reads as an instruction never changes another section's finding or gets anything auto-approved), malformed/empty LLM response handling, unrecognized-category degradation, code-fence-wrapped JSON parsing, extremely long section input, **bounded retry with no infinite loop**, retry-then-succeed, missing-API-key error path |
| `test_report.py` | JSON/Markdown/HTML structural completeness, **every proposed correction's `correction_target` is `"translation"`**, severity counts sum to the finding total |
| `test_aggregation_and_units.py` | **Finding aggregation** — two unit signals and two entity signals each collapse into one finding with multiple evidence items; different categories never merge; single-signal findings are unaffected. **Unit-conversion policy** — same unit/same value, same unit/changed value, legitimate conversion (incl. rounding tolerance), invalid conversion, unsupported conversion pair, missing unit, multiple values in one section, unit values are never auto-rewritten |
| `test_html_escaping_and_size_limits.py` | XSS-payload round-trip through the actual HTML report generator (source text, back-translation text, and `run_id` all attempted), confirms escaped-but-inert vs. a live tag, oversized-document handling (200 sections), binary/garbled input, empty-string input |
| `test_superdocs.py` | Adapter never claims a live connection, upload/export round-trip, proposed edits are recorded but don't mutate exported content until a decision is applied, review decisions are recorded |

## What "verified" means for the live LLM path

`AnthropicProvider`'s HTTP request construction and response parsing are
tested against mocked responses (`_parse_response_json` called directly with
constructed payloads — malformed JSON, missing fields, unrecognized
category, code-fence-wrapped output). No test in this suite makes a real
network call to `api.anthropic.com`; see LIMITATIONS.md #5.

## Manual verification performed before calling this done

- Ran the flagship demo end to end via `run_pipeline` directly (not just
  through pytest) and read the resulting JSON/Markdown/HTML reports.
- Ran the second, unrelated document the same way.
- Confirmed `source_integrity_status: VERIFIED` and a non-zero,
  matches-expected `integrity_checks_run` count in both summaries.
- Grepped both reports to confirm all 10 seeded cases and both PASS cases
  landed at the section index they were seeded at.
- Confirmed `git diff`/`git status` contain no `.env`, key material, or
  `__pycache__` before the final commit.
- (Pre-submission audit pass) Ran an XSS-payload round trip through the real
  `report.to_html()` — not a synthetic unit test in isolation — confirming
  escaped-but-inert output and no live tag.
- (Pre-submission audit pass) Verified the aggregated flagship finding count
  by direct inspection (`15 → 13`, matching the two sections where two
  same-category signals now correctly collapse into one finding).
