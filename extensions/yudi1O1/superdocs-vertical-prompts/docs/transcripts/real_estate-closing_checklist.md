# `/real_estate:closing_checklist`

Real output from `session.get_prompt("closing_checklist", ...)` against the actual running server
(`python -m vertical_prompts.server --pack packs/real_estate/pack.yaml`) — captured, not hand-written.
Regenerate with `python scripts/capture_transcripts.py`.

**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):

```
/real_estate:closing_checklist
  transaction_description: 'the purchase agreement, inspection addendum, and financing contingency for the 123 Maple St. purchase, all open in this session'
  closing_date: '2026-10-15'
```

**Rendered prompt message the assistant receives:**

```
Read the purchase agreement, inspection addendum, and financing contingency for the 123 Maple St. purchase, all open in this session and produce a closing checklist as a new
document, organized as a table: Item | Responsible Party | Due Date |
Source Document. The closing date is 2026-10-15 — express every
deadline both as an absolute date and as "N days before closing" so the
coordinator can sort by urgency.

Include financing, inspection, title, insurance, and disclosure items —
not just the ones with the earliest deadlines. If a document you'd
expect at this stage (e.g. a title commitment) isn't among the open
documents, list it as an open item with no source document rather than
omitting it.


--- SuperDocs call settings for this workflow (do not deviate) ---
- Tool: call `chat` (synchronous) or `chat_async` with `approval_mode="approve_all"` — this command produces new/summary content rather than editing existing binding text, so it applies immediately without a per-change review gate.
- Still show the user the AI's response before exporting, so they can ask for a follow-up edit if something looks off.
- When the work is approved and complete, call `export_document` with format="markdown", options={'filename': 'closing-checklist'}.
- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first (docs.superdocs.app/mcp/mcp-setup) before attempting any of the above.
```
