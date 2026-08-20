# Terminal HITL Review TUI

Renders a batch of proposed changes as a coloured diff in the terminal with
keyboard **accept / reject / edit**, then commits the approved batch.

Built with Rust + [ratatui](https://ratatui.rs). Input is either a SuperDocs
`pending_changes.json` batch or a plain unified `git diff` file.

## What it does

- Left pane: change list (status, index, target file, AI explanation).
- Right pane: coloured line diff with word-level highlighting (red/green +
  strikethrough/underline); HTML chunks are shown as readable extracted-text
  diffs (`t` toggles the raw markup).
- Keys: `j/k` move, `a` accept, `r` reject, `u` undo, `e` edit in `$EDITOR`
  (re-diffed against the original), `n` next unreviewed, `f` filter by status,
  `[`/`]`/`0` scroll the diff, `c` commit, `q` quit.
- Commit applies **only the accepted/edited changes** (partial approval),
  stages the touched files and makes one commit with a summary message.
- Scales to hundreds of changes: the list is virtualized and the diff for a
  change is computed lazily only when it is selected.
- Headless mode for CI/automation: `--decide accept-all|reject-all` and/or a
  JSON decisions file, plus `--dry-run` to plan without touching anything.

## Usage

```bash
cargo build --release

# interactive review of a SuperDocs pending_changes batch
./target/release/hitl-review-tui data/sample_batch.json --workspace .

# interactive review of a unified diff (one change per file)
./target/release/hitl-review-tui data/sample.diff --workspace .

# headless: accept everything and commit
./target/release/hitl-review-tui data/sample_batch.json \
  --workspace . --decide accept-all

# headless: per-change decisions from a file, nothing written or committed
./target/release/hitl-review-tui data/sample_batch.json \
  --workspace . --decisions data/decisions.example.json --dry-run
```

`--map doc_id=path` overrides where a document's changes are applied, and a
`"path"` field inside each JSON change entry is honored first.

## Input formats

- **JSON batch** (SuperDocs `pending_changes.json` shape): entries with
  `old_html`/`new_html` or `old_text`/`new_text`, optional `change_id`,
  `document_id`, `ai_explanation`, `path`. A change applies by replacing its
  `old_*` content inside the target file (or creating the file if it is
  missing).
- **Unified diff** (`.diff`/`.patch`, git-style or plain): parsed into one
  change per file; hunks are applied with context verification.

## Decisions file (headless)

```json
{
  "chg-001": "accept",
  "chg-002": "reject"
}
```

Every change must be decided (`--decide` covers the rest); otherwise headless
mode fails with a non-zero exit code.

## Project layout

```
src/
  cli.rs        CLI parsing and usage text
  load.rs       input parsing (JSON batch / unified diff) -> Vec<Change>
  model.rs      Change, Decision, Payload, Hunk types
  diffengine.rs unified diff parse + apply, line/word diff rendering
  htmlext.rs    HTML -> plain-text extraction for readable diffs
  actions.rs    apply accepted changes, git stage + single batch commit
  headless.rs   headless review runner
  tui/          ratatui app (key handling) and ui (rendering)
data/           sample batch, sample diff, and a demo workspace
tests/          end-to-end tests: temp git repos, partial approval, 200-change run
```

## Tests

```bash
cargo test
```

Covers diff parsing/application, HTML extraction, key handling, partial
approval in a real temp git repo (rejected files untouched, commit contains
only accepted files), dry-run, and a 200-change batch staying fast and
correct.

Built for the SuperDocs engineering task (round 2) by Akshat Rai.
