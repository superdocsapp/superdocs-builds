# SuperDocs Living Note for Obsidian

> Built by Ayam for the SuperDocs task.

An Obsidian plugin that keeps marked sections of one designated note current from the rest of the vault, through the SuperDocs API. The design decision the whole thing turns on is visible ownership: the agent can write only between `superdocs:owned` markers, and it is never even handed the text outside them.

## What it does

1. Point it at a note: **Set active note as designated living note**.
2. Mark what the agent may maintain. Anything between a start and end marker is its; everything else is yours.

   ```md
   ## Where the project stands

   <!-- superdocs:owned:start id="status" brief="where the project stands right now" -->
   - Waiting for the first reviewed run.
   <!-- superdocs:owned:end id="status" -->
   ```

   The markers are part of the file, not a hidden setting, so anyone reading the note can see the boundary. `brief` is optional and tells the agent what the block is for; without it the nearest heading above the block is used. A missing, duplicated, nested, unclosed or overlapping marker stops the run before any network call.
3. Run **Preview living-note update (no spend)**. It ranks the vault locally and shows you the exact text a real run would upload. No network call, no operation.
4. Run **Sync designated living note now**. The plugin uploads *only* the owned-region content as the editable SuperDocs document, attaches the note and the top-ranked vault sources as read-only reference material, and starts one asynchronous `ask_every_time` edit.
5. Review each proposed change in Obsidian: approve, reject, or reject with feedback, one by one. At most three rounds.
6. Approved changes are applied to the note, inside the markers, after three checks pass.

## Why the agent never gets your prose

The editable document is built from the owned regions alone:

```md
## superdocs-region: status

- Waiting for the first reviewed run.

## superdocs-region: questions

- Waiting for the first reviewed run.
```

That is the whole document SuperDocs sees as editable. A proposed change to one of your paragraphs is not something the agent can express, because your paragraphs are not in the document it is editing. They go up separately as a read-only attachment, which the API cannot apply an edit to.

The region headings exist because SuperDocs strips Markdown comments during parsing and export — verified against the live API, and reported as a rough edge. Headings survive the round trip; comments do not. The comment markers stay in the vault, where they belong.

## The three checks before a byte is written

1. **Chunk alignment.** Each `data-chunk-id` in the parsed document is matched back to the exact Markdown block it came from, and the two must carry the same text. An approved change is placed by chunk id, so it lands in the paragraph it was proposed against and nowhere else.
2. **Ownership.** The candidate note is diffed against the original outside the markers. Any difference at all, and the run writes nothing.
3. **Agreement with SuperDocs.** The Markdown export of the approved document is fetched and compared, region by region, against the local result. If SuperDocs and the plugin disagree about what was approved, the plugin writes nothing rather than pick a winner.

Then the note is re-read and written in one `Vault.process` operation, so an edit you made during the review aborts the write instead of being overwritten.

## Setup

### 1. Get a key

Create an API key at [use.superdocs.app](https://use.superdocs.app). Never put it in a repository. The plugin stores it in this vault's local plugin data, shows it as a password field, and never logs it.

### 2. Build and install

Requirements: Node.js 18+, Obsidian 1.5.7+.

```bash
npm install
npm test         # 31 tests, no API key needed
npm run typecheck
npm run build
```

Copy `manifest.json`, `main.js` and `styles.css` into `<vault>/.obsidian/plugins/superdocs-living-note/`, then enable the plugin. `npm run dev` rebuilds on change.

`examples/demo-vault/` is a four-note vault you can open straight away; see [examples/README.md](examples/README.md).

## Commands

| Command | What it does |
|---|---|
| Set active note as designated living note | Points the plugin at the open note |
| Initialize an owned region in the designated note | Adds a starter boundary, only if the note has none |
| Preview living-note update (no spend) | Local retrieval and plan; no network call |
| Sync designated living note now | One bounded reconciliation with human review |

## SuperDocs surfaces used

- **API**: `documents/upload-base64` (the owned regions, with `return_html` for chunk ids), `attachments/upload-base64` and `attachments/status` (the note and vault sources as read-only context), `chat/async` with `approval_mode: "ask_every_time"`, `jobs/{id}` polling, `chat/{session}/approve` with per-change decisions, and `documents/export` as the final cross-check.
- **Search**: a local deterministic lexical ranker picks which vault notes to attach; SuperDocs' own `cross_session_search` is an opt-in setting.
- **Memory**: opt-in `cross_session_memory`, with an optional key for separating vaults.
- **Review**: every proposed change is decided by a person, item by item, with optional feedback on a rejection.

The session id is derived from the note path and the source fingerprint, so a given source state gets one session and stale attachments are never reused across source states.

## Stopping rules

- Automatic sync is opt-in and driven by source-note changes, debounced by five seconds. The designated note is excluded from the trigger, so the plugin cannot re-trigger on its own output.
- A source state is reconciled once. The fingerprint is recorded **before** the first paid call, so a run that fails afterwards is not retried automatically — a deterministic failure cannot bill in a loop. A manual sync always runs.
- The first scheduled tick after automatic sync is switched on records where the vault stands instead of spending.
- At most three review rounds, and a job that has not finished in fifteen minutes is abandoned rather than polled forever.
- A large-edit continue prompt is surfaced and stopped, never continued automatically.
- Preview mode makes no network call and spends nothing.

## Tests

`npm test` runs 31 tests with no API key and no network:

- 20 on the ownership guarantee: marker parsing and every malformed shape, duplicate ids, region briefs, chunk alignment against tables, task lists, images and fenced code, targeted edits, inserts, deletes, ordering, CRLF notes, and the export cross-check.
- 11 end to end, driving the real plugin against a real vault folder on disk and a stand-in SuperDocs service that applies only what was approved: preview spends nothing, a reviewed run writes only the approved change, a source note that gives orders is treated as material, a change aimed at human text cannot be applied, an edit during review aborts the write, a disagreeing export stops the write, rejecting everything writes nothing, a malformed boundary never reaches the network, a continue prompt stops, a failed run is not retried, and the same source state is not reconciled twice.

`tests/live-vault.ts` is a manual script that runs the same code against a real vault and the live API. It is not part of `npm test`, because it needs a key and spends an operation.

## Honest limitations

- The guarantee is about the bytes outside the markers. Inside a region, formatting is only as good as the HTML-to-Markdown conversion of an approved change: bold, italics, links, code, headings, ordered and unordered lists and block quotes are handled; anything more exotic is flattened.
- If a proposed change cannot be aligned to exactly one Markdown block, the run stops instead of guessing. That is deliberate, but it means an unusual block can block a note until it is simplified.
- If SuperDocs revises a change you already approved in an earlier round, the plugin stops and asks for a fresh run rather than reasoning about it.
- Repeat manual syncs at the same source state re-upload the same attachments into the same session. Harmless, but wasteful.
- Retrieval is a local lexical ranker over Markdown notes. It is not semantic search, and it does not index every Obsidian data type.
- Whatever is in the configured source folders is uploaded to your SuperDocs account. Scope that setting deliberately.
- The plugin does not sign, publish or send anything. A person approves every change.

## Screenshots

To be added from the demo recording: the review modal deciding two proposed changes, and the note before and after a run with the human paragraphs unchanged. Save them as `docs/review-modal.png` and `docs/note-after-run.png`.

## Bugs found in SuperDocs while building this

Reported to the team, and repeated here because they shaped the design:

1. Markdown comments are dropped on upload and export. This broke the first write-back design and is why ownership is fenced with headings on the wire.
2. The Markdown export flattens list markers: `- item` comes back without the bullet, although the parsed HTML is a correct `<ul><li>`. This is why the export is used as a cross-check rather than as the write-back source.
3. `ai_explanation` on a proposed change sometimes echoes the instruction back, truncated with an ellipsis, instead of explaining the change. It is the text a reviewer reads in the approval card.
