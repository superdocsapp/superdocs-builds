# `/real_estate:draft_disclosure`

Real output from `session.get_prompt("draft_disclosure", ...)` against the actual running server
(`python -m vertical_prompts.server --pack packs/real_estate/pack.yaml`) — captured, not hand-written.
Regenerate with `python scripts/capture_transcripts.py`.

**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):

```
/real_estate:draft_disclosure
  property_description: '123 Maple St., built 1974, known history of a basement water issue repaired in 2019'
  disclosure_type: 'material defect disclosure (water intrusion)'
  jurisdiction: 'California'
```

**Rendered prompt message the assistant receives:**

```
Add a material defect disclosure (water intrusion) disclosure to the open document for this property:
123 Maple St., built 1974, known history of a basement water issue repaired in 2019.

Use the disclosure language and format required in California for
this disclosure type. If you are not certain the jurisdiction's exact
required wording is captured correctly, say so explicitly in your
response and flag it for the transaction coordinator to verify against
their state's official disclosure form — do not present an uncertain
wording as settled.


--- SuperDocs call settings for this workflow (do not deviate) ---
- Tool: call `chat_async` (not `chat`) with `approval_mode="ask_every_time"` — HITL review requires the async workflow.
- Poll with `get_job` until status is `awaiting_approval`, then show the user every entry in `metadata.pending_changes` (old vs. new content, per change) and get an explicit yes/no on each one BEFORE calling `approve_change`. Do not auto-approve on this command — that defeats the point of a redline/edit workflow.
- If the user rejects a change, pass `approved=false` with their `feedback` on that `change_id` so the AI can revise just that item; keep polling through further `awaiting_approval` rounds until `status` is `completed`.
- When the work is approved and complete, call `export_document` with format="docx", options={'filename': 'disclosure-draft'}.
- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first (docs.superdocs.app/mcp/mcp-setup) before attempting any of the above.
```
