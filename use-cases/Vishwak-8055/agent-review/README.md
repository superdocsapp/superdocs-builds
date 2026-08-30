# SuperDocs Agent Review

A VS Code panel for reviewing document changes made through SuperDocs by an
external client (a coding agent, a script, or a person) before they're
treated as final. Changes are grouped by turn, shown before/after, and
approved, rejected, or reverted individually. An audit trail distinguishes
what a turn claimed from what was actually observed in the document.

**Status: functional core, not yet live-verified.** The review engine
(diffing, claim reconciliation, state machine, independent revert,
persistence, audit log, session polling, webview) is implemented and
covered by passing tests — see [`docs/EVALUATION.md`](docs/EVALUATION.md)
for the exact current count and command output. It has not been run
against a real SuperDocs account or a real running VS Code — see "Known
limitations" below for exactly what has and hasn't been verified, and by
which command.

## What it does

- Diffs two document HTML snapshots at the `data-chunk-id` level (edit /
  create / delete), whether or not SuperDocs's human-in-the-loop mode was
  used for that turn.
- Compares a turn's claim (its reply text) against the observed diff,
  grounded in the diff itself and SuperDocs's billing signal — never by
  asking a model to grade its own output — and specifically flags a turn
  that claims an edit with no corresponding document change, without
  creating a placeholder change for it.
- Tracks each change through an explicit state machine (`proposed` →
  `approved` / `rejected` / `reverted`, with `conflicted` for anything that
  can't be resolved automatically and `superseded` for a stale proposal a
  later turn has overtaken); a decision submitted twice is a no-op, not a
  duplicate.
- Reverts (or, for an already-applied change, undoes on reject) exactly one
  change's own chunk, never a sibling change's, and refuses rather than
  guesses when the live document has moved on since approval, or when its
  own document model can't prove a write-back would be lossless (see
  `docs/SECURITY.md`).
- Persists changes and audit records to disk so pending review state
  survives a restart, and persists per-session polling cursors so a
  restart doesn't reprocess already-seen turns.
- Polls SuperDocs sessions for new turns: sorted by creation time (not API
  return order), one slow poll never overlapping the next, one session's
  failure never blocking another's, and backing off on a rate limit.
- Renders a webview panel: turns grouped by session, each with its
  instruction, the agent's reply, before/after per change, a claim/actual
  badge, and approve/reject/revert actions — under a strict per-render CSP
  and with document content sanitized before rendering.

## Architecture

```
SuperDocs (hosted API) -> SessionWatcher (polls sessions/jobs)
                              -> ReviewStore (state machine, persistence, audit)
                                  -> ReviewPanel (webview) / TurnsTreeProvider (tree view)
```

The extension host owns all state and all SuperDocs calls; the webview only
sends action messages (`approve` / `reject` / `revert` / ...) and renders
whatever `ReviewStore` currently holds — it has no business logic of its
own. Full design, data model, and the reasoning behind the auto-apply vs.
human-in-the-loop handling: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

## Requirements

- Node.js 18+
- VS Code 1.85+, to run the extension itself
- A SuperDocs account and API key for actual use (not required to build or
  test) — free tier at [use.superdocs.app](https://use.superdocs.app) ->
  Settings -> API Keys

## Setup

```bash
npm install
```

## Configuration

No environment variables are required to build or test. To connect a real
account, run the "SuperDocs Review: Connect Account" command inside the
Extension Development Host; the key is stored in VS Code's encrypted
`SecretStorage` and is never written to a settings file or committed.

## Run

Open this folder in VS Code and press `F5` to launch the Extension
Development Host. `dist/extension.js` will not load outside that host —
`vscode` is intentionally external to the bundle (see "Build").

## Test

```bash
npm run typecheck                 # strict TypeScript, exactOptionalPropertyTypes on
npx eslint src test --ext .ts     # lint
npm test                          # vitest — see docs/EVALUATION.md for the current count and pass/fail
```

All tests run against in-memory fixtures; none require network access.

## Build

```bash
npm run build   # esbuild bundle to dist/extension.js, vscode external
```

## Package

```bash
npx vsce package --allow-missing-repository --no-dependencies
```

Two fields in `package.json` — `publisher` and `repository.directory` —
are placeholders (`replace-with-your-publisher-id`) and must be set to a
real value before this is published or submitted; `vsce` will otherwise
reject a human-readable placeholder outright. Everything else about
packaging (icon, license, included files) has been verified by actually
running this command; see `docs/EVALUATION.md`.

## Demo

Not recorded — a real account and a real running VS Code are both needed
to exercise it, and neither was available in the environment this was
built in. The planned script is in `docs/IMPLEMENTATION_PLAN.md` §14.

## Security

Credential handling, webview CSP, document-content sanitization, and known
gaps: [`docs/SECURITY.md`](docs/SECURITY.md).

## Known limitations

- **Not verified against a live SuperDocs account.** Every SuperDocs
  interaction is tested against fixtures built from the documented API
  shapes, not a real account — this build environment's network access
  does not reach `api.superdocs.app`.
- **Not visually inspected.** No GUI VS Code host was available; the
  webview's HTML/CSS/message-handling logic is unit-tested, its rendered
  appearance is not confirmed.
- **The live write-back path is AI-mediated, not confirmed deterministic.**
  No plain "overwrite this document verbatim" endpoint was found in the
  documented API. A runtime check (`canSafelyRoundTrip`) refuses to write
  back when the local document model can't prove it captures the document's
  full structure, rather than risk corrupting content it doesn't model —
  see `docs/SECURITY.md`.
- **Multi-document-per-turn is not modeled** in the session watcher (it
  currently treats one session as one document); the data model supports
  it.
- Full gap analysis, including correctness fixes made while wiring this
  together: [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md).

## Further reading

- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — architecture, data model, integration boundary
- [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) — what changed, what's still open
- [`docs/SECURITY.md`](docs/SECURITY.md) — credential handling, CSP, sanitization, document-integrity gate
- [`docs/EVALUATION.md`](docs/EVALUATION.md) — real command output, acceptance-scenario-to-test mapping

## Credits

Built and engineered by **Vishwak**.
