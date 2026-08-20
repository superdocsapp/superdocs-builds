# Docs PR Reviewer — one page

Built for docs-as-code teams who already live in GitHub. Every pull request that
touches documentation gets a small number of high-signal comments, a rendered
preview of the changed docs, a command that applies a suggested fix as a commit,
and a branded release document when a tag is published. SuperDocs is the document
engine; this app is the orchestration layer.

## What it does, measured

The offline demo is the source of these numbers. It reviews a synthetic PR with
three changed files, two of them documentation:

- 2 documentation files reviewed, 1 code file ignored
- 7 findings generated, 5 posted, 2 suppressed by the ranker
- review event is `REQUEST_CHANGES` because a blocker is present
- one apply command produces one commit, changing one line
- the same command afterwards produces no second commit
- applying a `TBD` placeholder is refused; the app will not invent the missing content
- a reader without write access is refused
- a document that contains instructions aimed at the app is reviewed as content; nothing is applied until a human comments the command

The test suite covers the same claims without a live key. Typecheck, tests, and
build all pass.

## Trade-offs

Comments are capped at five. Maintainers mute noisy bots; a quiet, useful review
is the product.

Only mechanical fixes are applied: heading-level skips and the `utilize` style
term. Missing alt text, placeholders, and TODO markers stay advisory. Generating
prose would mean inventing document content.

The preview and the release document share one HTML conversion. Without a
SuperDocs key that HTML is stored locally; with a key it is exported. Either way
the source is the same, so the preview cannot silently diverge from the export.

The live GitHub path is behind credentials. A fresh clone runs `npm run demo`
instead. Missing credentials are a named degraded mode, not a crash.

## What it does not do

It has not been installed as a real GitHub App in this workspace. The adapters
and the pipeline are real; the remaining step is creating the app and pointing a
webhook at the server.

Release documents list changed documentation files, not the merged pull requests
behind them. Associating commits with PRs needs extra calls this build does not
make.

`review` and `preview` commands parse and route; only `apply` is executed.

Built for the SuperDocs round 2 assigned build.
