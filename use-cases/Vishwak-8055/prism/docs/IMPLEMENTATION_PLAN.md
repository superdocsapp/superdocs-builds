# Implementation Plan

## This session's actual plan (executed, not aspirational)

1. Audit inherited PRISM DELTA code → confirmed reusable, no rewrite
   (docs/REPOSITORY_AUDIT.md).
2. Port into an npm-workspaces monorepo: `@prism/core` (shared) +
   `@prism/delta` (thin capability layer). Fix the two path bugs the port
   introduced. Re-run inherited 19 tests → 23 (paths fixed, same coverage).
3. Build `@prism/core#writeDocx` — the one genuinely new, high-risk shared
   primitive everything else this session depends on. Test immediately
   (round-trip, mutation, formatting, table-refusal) before building
   anything on top.
4. Build `@prism/vault` on top of `@prism/core#fingerprintParagraphs`.
   Test immediately, including a deliberate-tamper test.
5. Build `@prism/gate` on top of `@prism/core#writeDocx` and
   `@prism/delta`'s report shape (extended with `opIndex`/`ops` for this
   purpose). Test immediately, including cross-verification via re-running
   PRISM DELTA on GATE's own output.
6. Build `@prism/registry`: task data for all 30 capabilities (3 real, 27
   honestly bounded) + an explicit workflow state machine + the actual
   composed Delta→Gate→Vault run. Test immediately, including the
   UNVERIFIED-is-a-dead-end property and the full happy/incomplete/mixed
   paths.
7. Root demo (`cli.js`) exercising the real composed workflow against the
   real fixtures.
8. Documentation (this directory) written against what steps 1–7 actually
   produced, not drafted in advance of building it.
9. Full workspace test run (40/40), fresh-extract smoke test, git commit,
   zip.

## Next, if continued (see docs/REPOSITORY_AUDIT.md §10 for reasoning)

1. PRISM GRID (table model) — unblocks `writeDocx`'s current refusal.
2. PRISM MESH (concurrency) — `@prism/vault`'s version graph is already a
   real prerequisite; needs the concurrent-writer simulation and conflict
   resolution on top.
3. PRISM CONTINUUM (durable agent) — same prerequisite situation as MESH;
   additionally needs a model-backed agent loop with stopping rules.
4. A real UI — deliberately last; see docs/PRISM_ARCHITECTURE.md "Why
   this composition, specifically."

## Budget/scope discipline actually followed

No capability was started speculatively and left half-working. Each of
the 3 implemented capabilities has full test coverage for its own logic
before the next one was started, matching the directive's own "INSPECT →
PLAN → IMPLEMENT → TEST → REVIEW → FIX → TEST AGAIN → INTEGRATE →
REGRESSION TEST" loop rather than "implement everything, test at the
end."
