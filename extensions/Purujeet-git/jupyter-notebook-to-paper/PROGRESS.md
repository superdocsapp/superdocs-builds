# Progress

## Completed

- Established the notebook-to-paper evidence, claim, paper-block, and paper-document contracts.
- Added executed Jupyter notebook parsing.
- Added metric and statistic extraction with notebook cell, output, line, and character traceability.
- Added figure fingerprinting, captions, embedded image rendering, and LaTeX equation extraction.
- Added title derivation and preservation of relevant Markdown headings and prose.
- Added contradictory metric detection and conflict blocks.
- Added evidence snapshots, diffs, and incremental paper merging.
- Added an end-to-end two-version notebook test proving that only affected result prose changes.
- Added Markdown and HTML rendering.
- Added SuperDocs sync chat, async chat, job polling, itemized approval, and binary export.
- Verified the live async SuperDocs approval flow and export flow.
- Confirmed the current SuperDocs contract uses `document_html`; there is no separate upload endpoint in the active API.
- Added a browser review UI with per-block approve/reject decisions and review-before-commit enforcement.
- Added visible parse, evidence, claims, paper, review, and commit stages.
- Added retry, skip, and escalation decision handling.
- Added atomic state writes, checkpoints, resume support, run IDs, concurrent output locking, and stale-lock recovery.
- Added MCP server support and an MCP protocol test.
- Added prompt-injection safety scanning and tests.
- Added persistent SuperDocs usage telemetry and a telemetry CLI command.
- Added automated build and full test verification through `npm run verify`.
- Added setup, manual testing, Jupyter screenshot, SuperDocs, review, MCP, and download instructions to `README.md`.

## Verification status

The current local verification passes:

```text
npm run build  -> passed
npm test       -> 10 test files, 24 tests passed
```

Run both commands together with:

```powershell
npm run verify
```

## Current scope

This repository is the Jupyter notebook-to-paper Task 2.2 implementation. It is not the complete SuperDocs selection package. The general mixed-format Task 1 platform, Google Sheets roster-to-documents Task 2.1 build, Task 3 use-case research, Task 4 video/write-up/architecture submission, and public pull request remain outside this repository’s implementation scope.

## Release prerequisites

Before publishing:

1. Confirm the correct public `extensions` repository URL.
2. Confirm the required destination folder and branch.
3. Ensure `.env`, generated state, and usage ledgers are not staged.
4. Run `npm install` followed by `npm run verify` from a clean clone.
5. Copy the final README and test evidence into the submission materials.
