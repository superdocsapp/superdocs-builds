# Risk Register

## Carried forward from the prior session (still true)

| # | Risk | Severity | Status |
|---|---|---|---|
| 1 | Real SuperDocs starter repo and private Open Task List still never provided — two directives now, neither included them despite claiming they were "supplied." | High | Open. Everything here targets the public `superdoc/docx-editor` mirror and the directive's own text. |
| 2 | SuperDoc is AGPLv3 (commercial license available). This repo does not import real SuperDoc packages (it reads/writes raw OOXML directly), so this risk is currently dormant, not resolved — it activates the moment real SuperDoc code is imported. | Medium | Dormant. Legal review needed before that import happens, not before now. |
| 3 | Paragraph-modification pairing is an adjacency heuristic, not similarity-scored alignment. | Medium | Unchanged. Documented, tested for the cases it handles. |
| 4 | Obligation-language signal list is small and curated. | Medium | Unchanged. |
| 5 | No security hardening on `.docx` input parsing (zip bomb, XML entity expansion, size limits) — now true on both the read AND write paths. | Medium | Unchanged in kind, slightly larger surface (write path added). |
| 6 | No model/LLM wired in anywhere. | Low–Medium | Unchanged, and now also true for GATE's decision-making (a human or future agent must supply decisions; nothing here judges materiality beyond DELTA's deterministic tiers). |

## New this session

| # | Risk | Severity | Status / mitigation |
|---|---|---|---|
| 7 | **`write-docx.js` is new, from-scratch OOXML serialization** — the highest-risk new code in this build. A subtle round-trip bug here silently corrupts documents. | High | Mitigated, not eliminated: 3 round-trip tests, each independently checked via `pandoc` (not just the writer's own reader reading its own output), plus an explicit refusal (not silent data loss) for table-containing documents. Not fuzz-tested; only the fixture pair and one small table-containing document have been exercised. |
| 8 | **GATE's `applyApprovedChanges` re-derives change→paragraph mapping via `opIndex`**, a positional contract between `@prism/delta`'s report shape and `@prism/gate`'s consumption of it. If `build-report.js`'s op-iteration order ever changes without updating `opIndex` semantics, GATE would silently misapply changes. | Medium | Mitigated by tests that verify exactness through independent re-diffing (see `gate.test.js` "partial approval"), which would catch a misapplication, but there is no schema/contract test pinning the `opIndex` relationship itself — a determined refactor could still break it undetected until the exactness test happens to run. |
| 9 | **The demo's approval policy (`cli.js`) is a scripted heuristic** ("approve material+cosmetic, reject review-required"), not a human decision. If read as "the system decides what's material," that would misrepresent GATE's actual design (GATE applies decisions, it does not make them). | Low | Mitigated by an explicit in-line comment and console output labeling every auto-decision as "(auto-policy, not a human decision)." |
| 10 | **`@prism/vault` is in-memory only.** A process restart loses all version history. | Medium | Documented. Persistence was out of scope this session — see KNOWN_LIMITATIONS.md. |
| 11 | Single-capability... now triple-capability... scope. 27 of 30 PRISM capabilities and 21 of 28 shared-core services remain unbuilt. | High (for the full directive) / Expected (for two sessions of work) | Explicit in TASK_TRACEABILITY.md, not hidden. |

## New this session (UI)

| # | Risk | Severity | Status / mitigation |
|---|---|---|---|
| 12 | `@prism/ui`'s accessibility tests run against jsdom, not a real browser — a green test suite here does not mean a real screen reader will announce this UI well. | Medium | Mitigated by scope honesty (stated in the test file, KNOWN_LIMITATIONS #1/#7, and DECISIONS.md) but not by broader coverage — the underlying gap (no real browser/AT available) is unresolved. |
| 13 | Single shared server-side workspace with no auth — anyone reaching the port can read/mutate it. | Medium | Acceptable for the documented local single-operator use case; would need real work (sessions, auth) before any network exposure. See KNOWN_LIMITATIONS #7. |
| 14 | No request size limits on the JSON API — `readJsonBody` buffers the full request into memory. | Low | Fine for a human explicitly picking local files through the UI; a concern only if this server were ever exposed beyond that. |

## New this session (GRID)

| # | Risk | Severity | Status / mitigation |
|---|---|---|---|
| 15 | **GRID's write-back uses a raw paragraph-ordinal anchor for tables**, not a stable identity. Any future change to how paragraphs are counted/reindexed could silently break table positioning. | Medium | Mitigated by tests (multi-table interleaving, single/multi row) but not by a stronger anchor mechanism yet — see KNOWN_LIMITATIONS #2a. |
| 16 | **`xml-order.js` runs a SECOND full parse of document.xml** (preserveOrder:true) purely to recover sibling order lost by the main parser's grouped mode. Real, caught-by-testing risk: an earlier version of this file used `ignoreAttributes:true`, silently stripping table structure attributes (like gridSpan's required width) even though text content survived — found via independent pandoc verification, not by the unit tests alone (they were initially checking the wrong thing). Fixed by reusing the main parser's full-fidelity options. | Medium (was High until found) | Fixed and tested (`write-docx.test.js`'s multi-table interleaving test), but stands as a reminder that dual-parser designs need the SAME fidelity config on both passes, not just the same shape. |
