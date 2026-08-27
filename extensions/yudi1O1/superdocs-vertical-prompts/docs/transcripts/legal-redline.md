# `/legal:redline`

Real output from `session.get_prompt("redline", ...)` against the actual running server
(`python -m vertical_prompts.server --pack packs/legal/pack.yaml`) — captured, not hand-written.
Regenerate with `python scripts/capture_transcripts.py`.

**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):

```
/legal:redline
  contract_description: 'the vendor MSA currently open in this session'
  focus_areas: 'limitation of liability and indemnification'
  negotiating_position: "our standard playbook favors mutual indemnification capped at 12 months' fees"
```

**Rendered prompt message the assistant receives:**

```
Redline the vendor MSA currently open in this session, focusing on: limitation of liability and indemnification.

Negotiate toward this position: our standard playbook favors mutual indemnification capped at 12 months' fees

For each clause that conflicts with the position above, propose a
specific replacement — don't just flag the issue, draft the language.
Where the current text already matches the position, leave it alone
rather than proposing a cosmetic rewrite.


--- SuperDocs call settings for this workflow (do not deviate) ---
- Tool: call `chat_async` (not `chat`) with `approval_mode="ask_every_time"` — HITL review requires the async workflow.
- Poll with `get_job` until status is `awaiting_approval`, then show the user every entry in `metadata.pending_changes` (old vs. new content, per change) and get an explicit yes/no on each one BEFORE calling `approve_change`. Do not auto-approve on this command — that defeats the point of a redline/edit workflow.
- If the user rejects a change, pass `approved=false` with their `feedback` on that `change_id` so the AI can revise just that item; keep polling through further `awaiting_approval` rounds until `status` is `completed`.
- When the work is approved and complete, call `export_document` with format="docx", options={'filename': 'redline-draft'}.
- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first (docs.superdocs.app/mcp/mcp-setup) before attempting any of the above.
```
