# `/legal:fallback_clause`

Real output from `session.get_prompt("fallback_clause", ...)` against the actual running server
(`python -m vertical_prompts.server --pack packs/legal/pack.yaml`) — captured, not hand-written.
Regenerate with `python scripts/capture_transcripts.py`.

**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):

```
/legal:fallback_clause
  clause_name: 'the limitation of liability clause (Section 9.1)'
  primary_position: "cap liability at 12 months' fees, mutual"
  fallback_position: "raise the cap to 24 months' fees but keep the mutual carve-out for gross negligence"
```

**Rendered prompt message the assistant receives:**

```
Draft a fallback version of the limitation of liability clause (Section 9.1).

Primary position (already rejected by the counterparty): cap liability at 12 months' fees, mutual

Fallback position to draft instead: raise the cap to 24 months' fees but keep the mutual carve-out for gross negligence

Propose the fallback as a replacement for the current clause text, and
in your response explain in one sentence what concession this fallback
makes relative to the primary position, so the reviewing attorney can
see the trade-off at a glance.


--- SuperDocs call settings for this workflow (do not deviate) ---
- Tool: call `chat_async` (not `chat`) with `approval_mode="ask_every_time"` — HITL review requires the async workflow.
- Poll with `get_job` until status is `awaiting_approval`, then show the user every entry in `metadata.pending_changes` (old vs. new content, per change) and get an explicit yes/no on each one BEFORE calling `approve_change`. Do not auto-approve on this command — that defeats the point of a redline/edit workflow.
- If the user rejects a change, pass `approved=false` with their `feedback` on that `change_id` so the AI can revise just that item; keep polling through further `awaiting_approval` rounds until `status` is `completed`.
- When the work is approved and complete, call `export_document` with format="docx", options={'filename': 'fallback-clause-draft'}.
- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first (docs.superdocs.app/mcp/mcp-setup) before attempting any of the above.
```
