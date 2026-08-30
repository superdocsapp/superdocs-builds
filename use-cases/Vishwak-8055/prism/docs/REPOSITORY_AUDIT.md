# Repository Audit

Phase 0 deliverable. Unusual honesty note up front: the "existing PRISM
DELTA implementation" this directive says to audit is code I wrote in the
prior session of this same conversation — there is no independent
codebase to discover. What follows is a genuine audit in the sense that
every claim below is checked against the actual code and test runs, not
assumed from memory of having written it.

## 1. Existing architecture (as of session start)

A single npm package (`prism-delta`) with four modules: `docx/read-docx.js`
(OOXML reader), `docx/snapshot.js` (fingerprinting), `diff/text-diff.js`
(paragraph alignment + word diff), `classify/classify-change.js`
(deterministic categorization), `report/build-report.js` (assembly),
`index.js` (public API), `cli.js`. 19 tests, all passing. No table support,
no write-back, no versioning, no approval workflow, no task registry.

## 2. Existing functionality

Confirmed working by re-running the inherited test suite before touching
anything: read a real `.docx`, align two paragraph sequences, classify
changes into numeric/date/formatting/structural/semantic categories with
materiality tiers, and produce a JSON report. Deliberately conservative:
every ambiguous change routes to `review-required` rather than being
scored.

## 3. Reusable components

All of it. Per the directive's "no giant rewrite" rule, the reader,
fingerprinting, alignment, and classification logic were moved into
`@prism/core` and `@prism/delta` verbatim or near-verbatim (see git log —
the port is a `cp` plus import-path fixes, not a rewrite). Two real bugs
surfaced during the port itself, both path/assertion issues introduced by
moving files, not logic defects — see docs/DECISIONS.md.

## 4. Broken components

None found broken. The inherited suite passed 19/19 both before and after
the port (the port temporarily broke fixture paths in the copied test
file; fixed immediately, see commit history).

## 5. Technical risks

- **No write-back existed.** The inherited code was read-only. This
  session's biggest new risk surface is `@prism/core#write-docx.js`, a
  from-scratch OOXML writer — see docs/RISK_REGISTER.md #1.
- **Paragraph-only document model.** No table, header/footer, footnote, or
  tracked-changes support, inherited and still true. `write-docx.js` makes
  this an explicit refusal (throws on tables) rather than a silent gap,
  which is a strictly safer posture than the inherited read-only version
  had (which simply never encountered the question).
- **Adjacency-based modification pairing** (documented in the inherited
  code's own LIMITATIONS.md) is unchanged and still a real limitation for
  non-adjacent paragraph reordering.

## 6. Security risks

Unchanged from the inherited assessment: no hardening against zip bombs,
XML entity expansion, or oversized inputs. Still assumes trusted local
files. Now slightly more relevant since `write-docx.js` also parses
untrusted-shaped OOXML on the way in before rewriting it — same exposure,
now on both read and write paths.

## 7. Fidelity risks

The new write path is the material change here. Mitigated by: (a)
preserving the entire original zip and only replacing
`word/document.xml`, so styles/fonts/theme/settings survive untouched by
construction, not by re-implementing them; (b) preserving `<w:sectPr>` and
all `<w:document>`-level namespace attributes from the source rather than
reconstructing them; (c) three real round-trip tests independently checked
via `pandoc`, not only the writer's own reader. Residual risk: fidelity for
documents with tables is not attempted — refused outright (see #3 above).

## 8. Performance risks

Not benchmarked. Fixtures are trivially small (2 short contracts). No
claim of performance at scale is made anywhere in this repository — see
docs/KNOWN_LIMITATIONS.md.

## 9. Integration constraints

Same as the prior session's finding: the real `@superdoc/mcp`,
`@superdoc/cli`, and `@superdoc/sdk` packages are not present in the
public `superdoc/docx-editor` mirror's source tree (published to npm, but
their source lives outside what's clonable). This session's code does not
depend on them at all — it reads/writes raw OOXML directly, which sidesteps
the alpha/unbuilt-package risk entirely, at the cost of not being able to
claim actual SuperDoc-engine compatibility, only contract-shape
similarity.

## 10. Recommended evolution path

1. PRISM GRID (table model) next — it directly unblocks `write-docx.js`'s
   table refusal, which is the single biggest fidelity gap.
2. PRISM MESH (concurrency) — the version-graph prerequisite
   (`@prism/vault`) already exists; only the concurrent-writer simulation
   and conflict resolution are missing.
3. PRISM CONTINUUM (durable agent) — likewise now has its state-storage
   prerequisite in `@prism/vault`; missing piece is the agent loop and
   stopping rules, which need a model in the loop (see
   docs/KNOWN_LIMITATIONS.md).
4. A real UI is deliberately last: every capability above it is useful
   headlessly and is where the actual document-fidelity risk lives; a UI
   without table support or concurrency handling underneath it would be
   decoration over an incomplete floor.
