# Build task

## Assigned build

Obsidian agent-maintained living note: an agent keeps a designated note current from the rest of the vault, editing only the sections it owns.

## Acceptance criteria

- [x] Human paragraphs outside the ownership markers are preserved byte for byte, and the tests prove it rather than assert it.
- [x] The ownership boundary is explicit in the file, and a malformed boundary stops the run before any network call.
- [x] Uses the SuperDocs API contract end to end: upload, async edit, human approval, Markdown export.
- [x] The agent is never handed the human prose as editable content, so a change to it cannot be proposed.
- [x] Local source retrieval, plus optional SuperDocs cross-session search and memory.
- [x] Preview mode makes no network call and spends zero operations.
- [x] Automatic sync is opt-in, source-change driven, debounced, fingerprinted, and never triggered by the target's own output.
- [x] One bounded reconciliation per source fingerprint, recorded before the spend so a failure cannot bill in a loop.
- [x] A large-edit continue prompt is surfaced and stopped, never auto-continued.
- [x] Tests run without a live key: 31 of them, including 11 end to end.

## Deliberate cuts

- Markdown vault notes and a local lexical ranker, rather than every Obsidian data type or a vector index. The ranker is deterministic, which keeps the preview honest about what a run would send.
- The review interface is an Obsidian modal rather than an inline editor diff. The decision, not the pixels, is what the task grades.
- A change that cannot be aligned to exactly one Markdown block stops the run instead of being placed by best guess. Failing closed is worth more here than covering an exotic block.
- A large edit that SuperDocs pauses to continue is not continued. Continuing spends again and crosses the plugin's stopping boundary.
- Repeat manual syncs at the same source state re-upload the same attachments rather than diffing the session's attachment list. Wasteful, bounded, and cheaper to explain than to fix.
