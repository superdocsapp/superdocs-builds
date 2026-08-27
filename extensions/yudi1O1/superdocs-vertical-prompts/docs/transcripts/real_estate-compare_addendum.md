# `/real_estate:compare_addendum`

Real output from `session.get_prompt("compare_addendum", ...)` against the actual running server
(`python -m vertical_prompts.server --pack packs/real_estate/pack.yaml`) — captured, not hand-written.
Regenerate with `python scripts/capture_transcripts.py`.

**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):

```
/real_estate:compare_addendum
  addendum_description: "the financing contingency extension addendum the buyer's agent sent yesterday"
  base_agreement_description: 'the original purchase agreement open in this session'
```

**Rendered prompt message the assistant receives:**

```
Compare the financing contingency extension addendum the buyer's agent sent yesterday against the original purchase agreement open in this session and
produce a conflict report as a new document: one row per term the
addendum changes, with columns Term | Base Agreement Says | Addendum
Says | Conflict Type (extends / contradicts / adds new obligation).

If the addendum introduces a deadline, confirm whether it's consistent
with every other date already committed to in the base agreement (e.g.
a financing extension that would run past the closing date is a
conflict worth flagging even if the two documents don't literally
contradict each other in wording).


--- SuperDocs call settings for this workflow (do not deviate) ---
- Tool: call `chat` (synchronous) or `chat_async` with `approval_mode="approve_all"` — this command produces new/summary content rather than editing existing binding text, so it applies immediately without a per-change review gate.
- Still show the user the AI's response before exporting, so they can ask for a follow-up edit if something looks off.
- When the work is approved and complete, call `export_document` with format="markdown", options={'filename': 'addendum-conflict-report'}.
- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first (docs.superdocs.app/mcp/mcp-setup) before attempting any of the above.
```
