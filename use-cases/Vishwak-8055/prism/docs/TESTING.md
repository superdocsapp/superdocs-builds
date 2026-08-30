# Testing

## Current suite: 40/40 passing

Run `npm test` from the repo root (`npm test --workspaces`). Per-package
breakdown:

| Package | Tests | What they cover |
|---|---|---|
| `@prism/core` | 13 | OOXML reading, paragraph alignment (incl. an uneven-length edge case), and 4 write-docx round-trip tests independently checked via `pandoc` |
| `@prism/delta` | 10 | Reader details, classifier correctness per category (numeric/date/semantic/formatting/structural), end-to-end fixture comparison |
| `@prism/vault` | 5 | Undo/redo, redo-truncation-on-new-commit, revert including revert-of-a-revert, and a deliberate-tamper test proving restore verification isn't a no-op |
| `@prism/gate` | 5 | Full-approve, full-reject, partial approval (verified by re-diffing), edited decisions, pending-decision refusal |
| `@prism/registry` | 7 | Registry data integrity, illegal state transitions, the UNVERIFIED dead-end, and the full composed workflow (happy path, incomplete-decisions path, mixed-decisions path) |
| `@prism/ui` | 16 | Real HTTP integration tests against a live server instance (full compare→decide→apply→download→vault flow, table-containing document flow, structured-error paths, path-traversal guard) + real axe-core accessibility checks against the static shell and every dynamic render function with representative real data |
| `@prism/grid` | 9 | Structural table comparison against real fixtures, including merged-cell cases (gridSpan, vMerge restart/continue) |

## Coverage against the directive's required test types

| Required type | Covered? |
|---|---|
| Unit | Yes — most of the 40 |
| Integration | Yes — `gate.test.js` and `compose.test.js` cross package boundaries |
| Contract | Partial — `opIndex` is a real contract between delta and gate, exercised but not pinned by a dedicated schema test (see RISK_REGISTER #8) |
| API | N/A — no HTTP/RPC API exists yet |
| E2E | Partial — `compose.test.js` is end-to-end for the CLI/library surface; `@prism/ui/test/server.test.js` is end-to-end for the HTTP API (real server, real requests, full compare→apply→download→vault flow); no real-browser E2E (no Playwright/Selenium — see docs/KNOWN_LIMITATIONS.md #1) |
| Document fidelity | Yes — see docs/FIDELITY.md |
| Regression | Yes, informally — the full suite reruns on every change; no dedicated regression fixture set beyond the shared fixtures |
| Security | No — no security-specific test suite; see docs/SECURITY.md |
| Accessibility | Partial — real axe-core DOM-structure checks (13 assertions across static shell + 5 dynamic render functions) plus manually-computed WCAG contrast ratios for the full palette (caught and fixed one real failure). Not real browser/screen-reader testing — see docs/KNOWN_LIMITATIONS.md #1 and #7 |
| Performance | No — not benchmarked; see docs/BENCHMARKS.md |
| Concurrency | No — PRISM MESH not built |
| Failure recovery | Partial — illegal transitions, unknown IDs, pending-decision refusal, and the table-write refusal are all tested failure paths; broader adversarial recovery (network/storage failure, timeouts) is N/A since no network/storage layer exists yet |
| AI evaluation | N/A — no model is called anywhere in this codebase |

## Philosophy actually followed, not just stated

Every new risky piece of code this session (`write-docx.js`, `gate/apply.js`,
`compose.js`) was tested **immediately after being written, before the
next piece was built on top of it** — e.g., write-docx's round-trip tests
ran and were fixed before `@prism/gate` was started. Two real bugs were
found and fixed this way in the prior session; this session's write-docx
and gate code passed on first test run, which is worth stating plainly
rather than either hiding a suspiciously clean result or manufacturing
false modesty about it.
