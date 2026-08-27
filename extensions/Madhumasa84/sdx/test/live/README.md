# Live verification guardrails

Live checks are separate from default tests and never record raw responses.

`npm run test:live` currently runs the Stage 2 prerequisite review-mode smoke only. It skips when `SUPERDOCS_API_KEY` is absent, performs no approval/export, and caps potentially billable edits at one.

Stage 3 live verification requires that Stage 2 smoke pass first, then permits only:

1. one tiny synthetic `sdx edit`;
2. one tiny synthetic stdin `sdx new`.

The Stage 3 cap is two potentially billable operations. Because the Stage 2 prerequisite has not yet passed in this workspace, Stage 3 live operations must not run. Offline completion remains valid and `PROGRESS.md` records the pending status and zero operation count.

Never save raw live responses, signed URLs, identifiers, keys, or user documents.

Stage 4 follows the same prerequisite and permits at most two potentially billable operations total. The preferred proof is one explicitly approved target edit on the generated 120-page disposable fixture followed by verified export. This has not run in this workspace.

`npm run record:live` enforces the Stage 2 prerequisite first, then requires both `SDX_RECORD_FIXTURE=1` and an existing environment key. The recorder itself permits one edit, generates disposable synthetic input, approves each item explicitly, excludes signed-storage traffic and raw bytes, validates secrets/signed queries, and deletes local input/output. Including the prerequisite, that command can consume at most two potentially billable edits. No live cassette currently exists.

Every compiled CLI child receives an isolated temporary `HOME`; live tests never touch the developer's real `~/.sdxrc` or `~/.sdx`.
