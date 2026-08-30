# Evaluation

Generated from real command output on 2026-08-22, after a fresh
`rm -rf node_modules dist *.vsix package-lock.json && npm install` (lockfile
regenerated, not reused) — not reconstructed from memory. Reproduce with
the commands below.

## Quality gates actually run

```
$ npm run typecheck
> tsc --noEmit -p .
(no output — clean, strict mode, exactOptionalPropertyTypes on)

$ npx eslint src test --ext .ts
(no output — clean, zero warnings)

$ npx vitest run
 ✓ test/sessionWatcher.test.ts   (20 tests) 24ms
 ✓ test/reviewStore.test.ts      (15 tests) 13ms
 ✓ test/chunkDiff.test.ts        (20 tests) 13ms
 ✓ test/webviewRender.test.ts    (22 tests) 17ms
 ✓ test/revertEngine.test.ts      (5 tests)  5ms
 ✓ test/claimReconciler.test.ts   (9 tests)  7ms
 ✓ test/changeModel.test.ts      (10 tests)  5ms
 ✓ test/superdocsClient.test.ts   (5 tests) 10ms
 ✓ test/liveSideEffects.test.ts   (3 tests)  9ms
 ✓ test/persistence.test.ts       (7 tests)  8ms

 Test Files  10 passed (10)
      Tests  116 passed (116)

$ npm run build
dist/extension.js       482.7kb
dist/extension.js.map   894.7kb

$ npx vsce package --allow-missing-repository --no-dependencies
DONE  Packaged: superdocs-agent-review-0.1.0.vsix (27 files, 400.57 KB)

$ node -e "require('./dist/extension.js')"
Cannot find module 'vscode'   <- expected/correct outside the Extension Host
```

An environment issue was found and fixed while producing this run: a stale
`node_modules` state had caused `tsc` to resolve to an unrelated, unpinned
TypeScript version, which surfaced a deprecation error that had nothing to
do with this project's code. A clean reinstall (lockfile regenerated)
resolved it. Noted here because catching this — rather than assuming a
"typecheck failed" result meant a real code regression — is exactly the
kind of verification this document exists to be honest about.

## Audit matrix (condensed — full narrative in GAP_ANALYSIS.md)

| Area | State | Evidence |
|---|---|---|
| API integration | Real client, typed, tested against mocked `fetch`; never live-tested | `superdocsClient.test.ts`, `liveSideEffects.test.ts` |
| Session/turn identity | `turnId` keyed on server `job_id`, not a local counter | `sessionWatcher.test.ts` "turn identity" suite |
| Document baseline | Bootstrap fix in this pass — pre-existing content no longer misreported as new | `sessionWatcher.test.ts` "bootstrap baseline" suite |
| Diffing | Top-level-only chunking (nested-duplication bug fixed); refuses on duplicate ids | `chunkDiff.test.ts` |
| Claim reconciliation | Grounded in objective diff + billing signal, never a model call | `claimReconciler.test.ts` |
| HITL workflow | Adopted directly from SuperDocs's own structured proposal, no re-diffing needed | `reviewStore.test.ts` HITL suite |
| Approve/reject | Source-aware (auto_apply vs hitl) correct semantics; double-submit safe | `reviewStore.test.ts`, `changeModel.test.ts` |
| Revert | Chunk-scoped, conflict-detecting, gated by the round-trip safety check | `revertEngine.test.ts`, `liveSideEffects.test.ts` |
| Persistence | Atomic JSON writes, restart-durable, cursors persisted | `persistence.test.ts`, `sessionWatcher.test.ts` restart test |
| Audit | Append-only; fields renamed to stop implying a false version guarantee | `reviewStore.test.ts` audit assertions |
| Security | Real CSP, maintained sanitizer, validated messages, secrets in SecretStorage only | `webviewRender.test.ts`, `docs/SECURITY.md` |
| Concurrency | Overlap guard on polling; per-job/per-session failure isolation | `sessionWatcher.test.ts` |
| Failure recovery | 429 backoff, per-session isolation, duplicate-chunk-id isolation | `sessionWatcher.test.ts` |
| Webview | Real, functional; not visually inspected in a running host | This document, "Not run" section |
| Accessibility | Not audited — no running host available | Stated limitation, not claimed done |
| Performance | Not load-tested at scale — no running host available | Stated limitation, not claimed done |
| Tests | 116 passing, real run each time | This document |
| Documentation | README/GAP_ANALYSIS/SECURITY/EVALUATION kept in sync with actual code each pass | This document |
| Build/release | typecheck/lint/test/build/package all genuinely pass; 2 package.json fields are stated placeholders | Command output above |

## Packaging — what was actually broken, and what's still a placeholder

`vsce package` was **not** clean the first time it was tried (an earlier
pass): it failed outright on the placeholder publisher name, then warned
about a missing `repository` field and missing `LICENSE`/`.vscodeignore`.
All fixed; the command above now succeeds cleanly. Two fields remain
intentionally-obvious placeholders — `publisher` and `repository.directory`
in `package.json`, both `replace-with-your-publisher-id` — because they
require a real identity this build environment doesn't have. That's not
the same as "packaging doesn't work."

- **No live network test.** This sandbox's outbound network allow-list
  does not include `api.superdocs.app`. Every SuperDocs interaction is
  tested against a fixture-backed fake, not a live account.
- **No visual QA / launched VS Code.** Headless container, no display
  server, no VS Code binary. The webview's HTML/CSS generation and message
  handling are unit-tested; its rendered appearance in a real Extension
  Host has not been visually confirmed.
- **No accessibility audit with a real screen reader**, no performance
  test at the 100-turn/500-change/1000-audit-event scale — both need a
  running host this environment doesn't have.

## Mandatory acceptance scenarios — mapped to real, passing tests

| # | Scenario | Test(s) | Result |
|---|---|---|---|
| 1 | Normal successful edit | `reviewStore.test.ts`, `claimReconciler.test.ts` "acceptance test 1" | passing |
| 2 | Claimed but not observed | `reviewStore.test.ts`, `claimReconciler.test.ts` "acceptance test 2" | passing — zero fake `Change` objects created |
| 3 | Independent revert | `reviewStore.test.ts` "acceptance test 3", `revertEngine.test.ts` "independent revert" | passing, pure-engine level and through the full store |
| 4 | Reject | `reviewStore.test.ts`, `changeModel.test.ts` "acceptance test 4" | passing |
| 5 | Multiple turns, separately inspectable | `reviewStore.test.ts` supersession test | passing |
| 6 | Multiple clients, no special-casing | Architectural — see note below | true by construction, partially demonstrated |
| 7 | Stale/concurrent edit | `revertEngine.test.ts`, `reviewStore.test.ts` conflict tests | passing |
| 8 | Extension restart | `persistence.test.ts`, `sessionWatcher.test.ts` "persists cursors" | passing (persistence layer only, not a real VS Code restart) |
| 9 | Duplicate event | `reviewStore.test.ts` "acceptance test 9", `sessionWatcher.test.ts` | passing |
| 10 | Failure recovery, no silent corruption | conflict tests across `revertEngine`/`reviewStore`, plus the new `canSafelyRoundTrip` gate | passing |

### Note on scenario 6 (multiple clients)

Unchanged from the prior pass's honest framing: there is exactly one real
integration point (the SuperDocs API), and nothing in `src/` branches on
which coding agent issued a request. That is a structural property, not
something observed working with two named real agents against a live
account — no live account was reachable from this environment.

## Is independent revert genuinely production-safe?

Answering this directly, as asked, rather than leaving it implied:

**The decision logic: yes, to the extent tests can show.** Given a correct
chunk map, `revertEngine.planRevert` correctly identifies whether a chunk
is untouched since approval, refuses when it isn't, and `ReviewStore`
correctly scopes a revert to exactly one change's chunk — demonstrated by
tests that construct two independent changes from one turn, approve both,
revert one, and assert the other's chunk is byte-for-byte untouched.

**The chunk model itself: not fully proven, and now honestly gated rather
than assumed.** The nested-chunk bug found this pass (item 1 in
`GAP_ANALYSIS.md`) shows the model *can* be wrong in ways that would have
corrupted a document if shipped as-is. The fix (top-level-only chunking)
resolves the specific bug found. Whether SuperDocs's real HTML has other
structure this model doesn't capture (a document wrapper, interstitial
text) is unverified — no live account was reachable. `canSafelyRoundTrip`
converts that unknown into a runtime-checked guarantee: a write-back either
proceeds only after empirically proving it round-trips the actual live
document, or it refuses and reports a conflict.

**Overall: safe to attempt, not yet safe to assume unattended.** This is
"provably refuses to corrupt what it can detect it doesn't understand,"
not "confirmed lossless against real SuperDocs documents." The honest
recommendation is to run the acceptance scenarios above against a real
account, on a real document containing a table, before treating this as
production-ready for revert.

## Honest overall assessment

Strong on: correctness of the core review engine, including a real bug
that a naive pass would have shipped. Every fix in this pass has a named
test, not just a claim.

Weak on: anything requiring a live SuperDocs account or a real display —
neither was available. `docs/GAP_ANALYSIS.md` and this document list every
such item explicitly.

**Is this PR-ready?** Not yet, by this project's own standard: nobody has
watched it work against a real account or a real running VS Code, and two
package.json fields are placeholders pending real information only the
submitter has. The engineering underneath — state machine, reconciliation,
revert safety, watcher hardening, packaging mechanics — is genuinely
verified, not asserted.
