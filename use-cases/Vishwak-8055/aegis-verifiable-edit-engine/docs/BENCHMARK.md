# Adversarial benchmark

`benchmark/dataset.ts` defines 21 hand-written cases; `benchmark/run-benchmark.ts` runs every one through the real `AegisEngine` pipeline (mock adapter) and prints/writes metrics computed from what actually happened — nothing here is a fixed or pre-written number. Run it yourself:

```bash
npm run benchmark
```

## Categories

- **`safe` (7 cases)** — grammar, punctuation, a whole-document readability rewrite, a formatting-only change, a scoped local fix, and two explicitly-requested value changes (a fee increase, a deadline extension). A correct system ends these in `VERIFIED` or `VERIFIED_WITH_WARNINGS`.
- **`unsafe` (10 cases)** — one case per concrete failure mode the brief lists in section 17: obligation mutation, date mutation, currency mutation, unit mutation, scope escape, a deleted paragraph, an altered table, an altered URL, a changed exception, a changed condition. A correct system ends these in `REQUIRES_REVIEW` or `BLOCKED`.
- **`adversarial` (4 cases)** — the result *reads* like a perfectly reasonable edit; the mutation is disguised inside legitimate-looking simplification (a dropped obligation phrased as a natural rewrite, a changed number buried in reworded prose, an obligation quietly reassigned to the other party, an out-of-scope addition that sounds like a helpful clarification).

## Reading the output

The runner reports two numbers that matter more than the headline accuracy figure:

- **Unsafe recall** — of the cases that should have been caught, how many were. A miss here (a false negative) is the dangerous failure mode: an unsafe edit silently passing. The runner exits non-zero if this is ever less than 100%, because that specific regression should fail CI, not just get logged.
- **Safe specificity** — of the cases that should have passed cleanly, how many did. A miss here (a false positive) is annoying — a good edit gets held for review it didn't need — but not dangerous.

It also reports, per case, whether the *specific* finding kind predicted in the dataset actually showed up (`expectedFindingKind`) — this is informational only, not part of the pass/fail score, because more than one finding kind can legitimately fire for the same underlying problem and asserting on exactly one is brittle by construction (this is also why the property test in `test/property/protectedInvariant.property.test.ts` only asserts the *decision*, never a specific finding kind).

## Latest real run

```
generated_at: 2026-08-25T10:54:06.366Z
total_cases:  21
correct:      21   (100.0%)
unsafe recall:      14/14
safe specificity:    7/7
```

Full per-case output, including every finding kind that fired, is written to `benchmark/results/latest.json` on every run (git-ignored — it's regenerated output, not a fixture).

## What 100% does and doesn't mean

This is 21 hand-written cases against a mock adapter with hand-scripted resolvers — it demonstrates that the verification logic correctly classifies the specific failure modes it was built to catch, not that it would perform identically against real, unscripted LLM output at scale. The benchmark already did its intended job once during development: it caught `SEMANTIC_ACTOR_CHANGED` being classified too low to actually block anything (`MEDIUM` instead of `HIGH`), which was fixed in `policy.default.json` rather than adjusted in the test — see [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#risk-model-rationale). A production deployment should keep growing this dataset from real near-misses, not treat 21 cases as a ceiling.
