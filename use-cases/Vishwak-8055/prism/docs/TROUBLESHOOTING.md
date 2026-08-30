# Troubleshooting

Real error messages this codebase actually produces, and what they mean.

**`writeDocx refuses to write back a document containing tables: ...`**
The source document has a `<w:tbl>`. Not a bug — see KNOWN_LIMITATIONS #2.
PRISM GRID needs to land before this works.

**`Gate: cannot apply — N change(s) still pending: delta-000X, ...`**
`applyApprovedChanges` was called before every change in the approval set
had a decision. Call `decide()` on each listed ID first.

**`Gate: unknown changeId "..."`**
The changeId doesn't exist in this ApprovalSet — likely a stale ID from a
different `compareFiles()` run (change IDs are only stable within one
report, not across different document pairs or re-runs).

**`Vault: nothing to undo.` / `Vault: nothing to redo.`**
Called at the boundary of the version timeline. Check `canUndo()` /
`canRedo()` before calling if the boundary is expected in normal use.

**`Vault: fingerprint mismatch on restore for version ...`**
The stored paragraph content for a version no longer matches its recorded
fingerprint — this should only happen if something mutated a version's
paragraphs after commit, which the public API doesn't allow but a caller
reaching into internals could. Treat as data corruption, not a normal
error to catch-and-continue past.

**`Workflow(...): illegal transition X -> Y. Allowed: ...`**
The workflow state machine was asked to jump somewhere the transition
graph doesn't permit. The error lists what IS allowed from the current
state — use one of those instead of the attempted one.

**`ENOENT: no such file or directory, open '...'`**
Standard Node error — the path passed to `readDocx`/`compareFiles` doesn't
exist. Check the path, not this codebase.

**Tests fail with a `pandoc: command not found`-shaped error**
`pandoc` isn't installed. Required only for `@prism/core`'s write-docx
round-trip tests' independent verification step — install it
(`apt install pandoc` on Debian/Ubuntu) or skip that specific test file.
