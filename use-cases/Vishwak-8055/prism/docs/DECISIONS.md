# Decisions

Key judgment calls this session, and why, so a future engineer doesn't
have to reverse-engineer the reasoning from the code alone.

## Delta → Gate → Vault, not Nexus/Proof/Target

See docs/PRISM_ARCHITECTURE.md "Why this composition, specifically." Short
version: it's the one chain in the locked 30 that's fully deterministic,
so it was the one place "real, measured, verified" was achievable without
a model in the loop.

## Refuse table-containing documents in `writeDocx` rather than attempt partial support

A half-working table write-back (e.g., preserving tables that aren't
touched by the edit, but silently mishandling ones adjacent to edited
paragraphs) would be worse than an explicit refusal: it would look like it
worked until it didn't, on a document nobody thought to check closely.
Explicit refusal matches the directive's own "implement the correct
abstraction boundary... document the limitation" instruction more
directly than partial support would.

## Revert creates a new commit; it does not rewrite history

Modeled on `git revert` rather than `git reset`. This makes "revert a
revert" well-defined without a special case (it's just `revertTo()` called
on a version whose `kind` happens to be `'revert'`) and keeps the full
audit trail intact — a reverted-away version is still inspectable in
`vault.graph()`, never deleted.

## `applyApprovedChanges` refuses to run with any decision still `pending`

Considered: defaulting pending items to `rejected` (safest content-wise).
Rejected that option because it would silently apply a decision nobody
actually made — indistinguishable, from the caller's side, from a real
human rejection. An explicit throw naming the pending IDs was judged more
honest, even though it's less convenient.

## No build step — plain ES modules throughout

Considered TypeScript with a `tsc` build step (the shared-core services'
"strong typing" goal argues for it). Chose plain JS with `// @ts-check` +
JSDoc types instead: get real type-checking (`tsc --noEmit` works against
JSDoc-annotated JS) without adding a build step that could fail
independently of the logic itself — one fewer thing to go wrong in a
"clean install, clean run" check.

## Plain `node:http`, no framework, for `@prism/ui`

Considered Express (the obvious default). The actual route count is small
(9 endpoints) and the logic per route is a thin JSON-in/JSON-out wrapper
around already-tested library calls — a framework's routing/middleware
machinery would add a dependency and a learning-curve cost without solving
a problem this size actually has. Consistent with the dependency-
discipline principle already applied to the rest of this repo (no build
step, minimal deps).

## jsdom + axe-core for accessibility, not a real browser

A real browser (Playwright/Puppeteer with actual binaries) would give a
strictly better signal but needs binaries this sandbox's network allowlist
can't fetch. jsdom + axe-core gives a real, if narrower, signal — DOM
structure, ARIA validity, heading order, label presence — for zero added
infrastructure risk. The narrowing is stated in the test file itself
(a comment block in `accessibility.test.js`), not just in this document,
specifically so a future reader hits the caveat at the moment they'd be
tempted to over-trust a green checkmark. Color contrast was carved out of
the automated check entirely (jsdom doesn't render layout) and verified
instead by directly computing WCAG ratios for the palette — which is how
the `--text-faint` failure got caught: not by axe, by actually running the
numbers.

## The Verification Center shows NOT_APPLICABLE, not PASS, for unbuilt checks

Easiest wrong answer: make every row green so the panel looks complete.
`computeVerificationCenter` in `server.js` only ever returns `PASS` for
the two checks that actually run (CONTENT/STRUCTURE via re-diff, APPROVAL
via the decided set) and `NOT_APPLICABLE` for the six that would need
capabilities not built (citations, references, visuals, revisions) or a
document feature not present (tables). This is the same principle as the
task registry's honest `not_implemented` entries, applied to a UI
component instead of a data table — the two are deliberately consistent
with each other rather than the UI "looking" more complete than the
registry claims.

## Tables are read/compared/preserved, never edited, this session

`@prism/grid` gives PRISM DELTA-adjacent value (knowing whether a table
changed) without extending the diff/classify pipeline to reason about
table content, which would be substantially more work (table-aware
alignment, cell-level diffing) for a directive that never asked DELTA
itself to edit tables. Preserving verbatim is the correct, honest scope
for what's actually needed right now: prove nothing was silently lost,
not "propose a table edit."

## Table anchoring uses a raw paragraph-ordinal count, with a stated failure mode

Considered: a more robust anchor (e.g. tied to a stable paragraph
identity from `@prism/delta`'s op indices). Chose the simpler ordinal
count for this session, with an explicit, tested refusal
(`write-docx.test.js` "refuses only the genuinely ambiguous case") when
paragraph count changes rather than silently mis-anchoring. The honest
trade: less general, but never wrong — see KNOWN_LIMITATIONS #2a for the
upgrade path.

## A second, real bug: the order-recovery parser silently dropped table attributes

While building the table-aware write path, `xml-order.js`'s parser was
initially configured with `ignoreAttributes: true` — reasonable-looking,
since its ONLY declared job was recovering sibling tag order, not
content. But its node objects ended up reused directly for verbatim table
pass-through, and `ignoreAttributes: true` silently stripped every
attribute in that subtree — including `<w:gridCol>`'s required width. The
written file's raw XML still contained the cell text ("T1", "T2"), so a
naive text-search check would have looked fine; `pandoc` rendering the
tables as completely absent was the actual signal, caught by running
independent verification rather than trusting the unit test's first
(and, it turned out, insufficient) assertions. Fixed by having
`xml-order.js` reuse the main parser's full-fidelity `XML_OPTIONS`
instead of declaring its own narrower config. The general lesson, stated
because it will recur: **when one parse pass's output gets reused for a
different purpose than it was originally written for, its config
assumptions need re-justifying for the new purpose, not just carrying
forward.**

## The demo's approval policy is a labeled heuristic, not a hidden decision-maker

`cli.js` needs *some* decisions to reach `EXPORTED` and produce an
interesting demo. Rather than hand-picking specific changeIds (which
would silently encode "I know this fixture" into the demo script),
`cli.js` applies a stated, visible policy (approve material+cosmetic,
reject review-required) and prints it next to every decision — so
re-running the demo against a different document pair would still produce
sensible, inspectable output rather than crashing on unknown IDs.
