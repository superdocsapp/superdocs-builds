# Progress log

## 2026-08-05

- Read the engineer task, the growth task, the open task list, and the SuperDocs API and MCP documentation.
- Chose the assigned Obsidian build rather than an optional extra, so the core acceptance bar is unambiguous.
- Decided ownership must be a visible note-level contract, not a setting hidden in the plugin.
- Implemented explicit start and end markers, strict validation, local source ranking, persisted fingerprinting, a no-spend preview, and opt-in source-change scheduling.
- Implemented the REST calls: base64 document upload, reference attachments, async chat, approval, job polling and Markdown export.
- Implemented a review modal with per-change decisions and a three-round stopping condition.
- Live smoke test against the API with synthetic data: upload, attachment processing, async edit, approval and export all succeeded.
- Found that SuperDocs strips HTML comments during parsing and export, which broke the first write-back design.

## 2026-08-25

Re-verified every assumption against the live API before changing anything, then rebuilt the parts that did not hold.

**What the live API actually does** (session `smoke-region-1`, synthetic content, one operation):

- HTML comments do not survive upload or Markdown export. Confirmed.
- `## heading` markers do survive the round trip byte for byte. This is now how region boundaries are expressed on the wire.
- Markdown export flattens `<ul><li>` back to plain lines without bullets, even though the parsed HTML is a correct list. So the export cannot be the write-back source.
- On the polling surface, `metadata.pending_changes` arrives as objects. The documented JSON double-parse trap applies to the SSE surface, not to this one. A string entry is still parsed defensively.
- Per-change decisions are honoured: one approved and one rejected in the same batch produced exactly the approved change in the export.

**Redesign that followed from it.**

- The editable document is now the owned regions only, fenced by `## superdocs-region: <id>` headings. Human prose goes up as a read-only attachment. The ownership guarantee stopped being a text check and became structural: the agent is not given the text it must not touch.
- Approved changes are placed by chunk id, using a map from each parsed chunk back to the Markdown block it came from, verified by text on both sides. Ambiguity fails closed.
- The export is now used as an independent cross-check of the local result rather than being fetched and discarded, which is what the previous README claimed it was for.
- Owned regions gained an optional `brief` attribute. Without it the agent had no idea what a block was for and proposed nothing at all on the first live vault run; with it, runs produce useful updates. The nearest heading above the block is the fallback.

**Verification.**

- 31 tests, no API key: 20 on the ownership guarantee and 11 end to end, driving the real plugin against a real vault folder and a stand-in service that applies only what was approved.
- Three live runs against a real Obsidian vault and the live API. Bytes outside the markers identical every time; one operation per run.
- An independent adversarial audit of the code found eight real defects, all fixed: settings were captured unbound so nothing persisted from the settings tab; duplicate region ids validated clean and then failed with a message that falsely blamed the ownership guarantee; chunk alignment refused tables, task lists, images and fenced code blocks containing a blank line; an insert and an edit sharing an anchor could apply in the wrong order; a failure after the spend left the fingerprint stale so the automatic path re-bought the same reconciliation every interval; the scheduled tick could spend on a first run nobody asked for; the polling loop had no deadline; `waitForCompletion` was dead code.

## Open verification work

- Record the demo: preview, a source edit, one approval and one rejection, the note showing human paragraphs untouched, and a repeat run that does not spend again.
- Add the two README screenshots from that recording.
- Send the three SuperDocs findings above through the bug channel with a reproducing file.
