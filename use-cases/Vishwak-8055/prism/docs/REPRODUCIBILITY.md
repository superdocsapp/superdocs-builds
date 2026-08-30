# Reproducibility

## Setup

```bash
npm install          # installs and links all workspace packages
```

Requires Node.js with built-in `node --test` support (Node 18.17+ / 20+)
and ES module support. `pandoc` is required only to re-run
`@prism/core`'s write-docx tests' independent verification step (not
required for the library itself to run).

## Test

```bash
npm test             # runs all 7 packages' suites, 71 tests total
npm run typecheck    # tsc --noEmit against the @ts-check JSDoc annotations
npm run lint         # eslint .
npm run check        # typecheck + lint + test, the full pre-commit gate
```

Or per-package: `cd packages/<name> && node --test`.

## Regenerate fixtures

```bash
cd packages/delta && npm run fixtures
```

Rebuilds `contract-v1.docx` / `contract-v2.docx` from
`fixtures/generate-fixtures.js` using the `docx` package — deterministic
given the same `docx` version (pinned in `package-lock.json`).

## Demo

```bash
npm run demo          # from repo root — runs cli.js
```

## Benchmark / Evaluation

Not applicable — see docs/BENCHMARKS.md for why none exist yet.

## Build

No build step. Everything is plain ES modules run directly by Node — a
deliberate choice to minimize what "clean install, clean run" depends on;
see docs/DECISIONS.md.

## Pinned versions

`package-lock.json` (root and per-package) pins exact dependency
versions: `jszip@3.10.1`, `fast-xml-parser@5.11.0`, `diff@9.0.0`,
`docx@9.7.1`. No floating major-version ranges beyond what npm workspaces
itself requires for the `@prism/*` internal links.
