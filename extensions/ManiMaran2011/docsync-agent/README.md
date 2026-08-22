# DocSync — Code-to-Docs Sync Agent

**Category:** "Own invention," aimed at a proven real-world use case — integrations with coding tools
(Cursor/VS Code), which the task card explicitly names as one of the categories SuperDocs wishes existed.

## The problem

Documentation drifts from code constantly, not because engineers don't care, but because updating docs is
a full manual re-read-and-rewrite chore that competes with shipping. The realistic failure mode isn't "nobody
ever updates the README" — it's "someone changes a function signature, the PR merges, and the README's
example still shows the old signature for three months because updating it wasn't part of the diff."

## What DocSync does

Watches a codebase (via git). When code changes, it:

1. **Diffs at the function level**, not the line level — using Python's `ast` module to compare old and new
   versions of every changed file, producing a structured list of what actually changed semantically (a
   function's signature, a function added, a function removed) rather than a noisy line-diff.
2. **Finds where that function is documented** — searches the target doc (a README, an API guide) for
   sections that reference the changed function by name, using SuperDocs' chunk-id structure the same way
   Build A does.
3. **Proposes a targeted edit, scoped to exactly that section**, with an explicit citation back to the
   file:line of the code change that motivated it — nothing else in the document is touched, and nothing is
   proposed without a concrete code change behind it.
4. **A human approves each proposed doc update individually** before it's applied — mirrors Task 1's human
   gate and Build A's "never trust, always verify" posture. Rejecting one proposed update doesn't affect the
   others.
5. **Flags undocumented new public functions** as a separate category ("this is new and has no doc section
   at all") rather than either silently ignoring it or inventing a new section without asking.
6. **Says nothing when nothing needs saying** — an internal refactor that doesn't change any documented
   function's public signature produces zero proposed changes, honestly, rather than forcing an edit to
   justify having run.

Packaged as a thin VS Code extension (`vscode-extension/`) that runs the sync check on save or on commit and
shows proposed doc updates in a side panel with per-item approve/reject — the same UI shape as the CLI, just
inside the editor.

## Architecture

```
git diff (old file, new file)
        │
        ▼
  code_diff.py  ── AST-level diff → FunctionChange[] (added/removed/signature_changed)
        │
        ▼
  doc_index.py  ── finds which doc chunk(s) mention each changed function, by name
        │
        ▼
 sync_engine.py ── for each FunctionChange with a doc hit: propose a scoped SuperDocs edit,
                    citing file:line. For a hit with no doc reference: flag as "undocumented".
                    For a change that doesn't affect any documented function: propose nothing.
        │
        ▼
   human review  ── approve/reject each proposed update individually
        │
        ▼
 SuperDocs chat  ── applies ONLY approved updates, scoped to their target chunk
```

## What's tested without a live key

`tests/` covers `code_diff.py` and `doc_index.py` and `sync_engine.py`'s decision logic entirely offline —
these are pure functions over Python source text and don't need SuperDocs at all to prove correct:
- A function's signature change is detected and the old/new signatures are captured accurately.
- A function that's genuinely unchanged (docstring reformatted, body refactored, signature identical)
  produces NO proposed change — internal refactors don't spuriously trigger doc updates.
- A function documented in the README gets a scoped proposal citing the right file:line.
- A function NOT mentioned anywhere in the README is flagged as "undocumented," not silently skipped.
- Removing a function proposes removing its doc section, not leaving stale documentation behind.

The SuperDocs-calling layer (`sync_engine.apply_approved_updates`) is tested against a fake client, same
pattern as every other build in this submission — real-API verification is what the demo video shows.

## What's honestly a gap

- The AST-based diff only handles Python. A real product would need per-language diff strategies (or a
  tree-sitter-based language-agnostic approach) to cover the polyglot repos this would actually need to help
  with.
- Doc-reference matching is name-based (does the function name appear in the doc text), not semantic —
  it will miss a doc section that describes a function's *behavior* without naming it directly, and could
  false-positive on a common function name that appears in unrelated prose. Logged rather than hidden.
- The VS Code extension is a thin shell around the CLI (spawns the Python process, renders its JSON output)
  rather than a native TypeScript reimplementation — a reasonable trade for a weekend build, not what a
  shipped product would want long-term.
