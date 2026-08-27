# `/legal:obligation_summary`

Real output from `session.get_prompt("obligation_summary", ...)` against the actual running server
(`python -m vertical_prompts.server --pack packs/legal/pack.yaml`) — captured, not hand-written.
Regenerate with `python scripts/capture_transcripts.py`.

**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):

```
/legal:obligation_summary
  contract_description: 'the vendor MSA currently open in this session'
```

**Rendered prompt message the assistant receives:**

```
Read the vendor MSA currently open in this session and produce an obligation register as a new
document: one row per obligation, with columns Party | Obligation |
Trigger/Deadline | Source Clause.

Include every obligation you find, not just payment and delivery terms —
notice periods, audit rights, insurance requirements, and reporting
obligations count too. If the contract genuinely has no obligation of a
kind you'd expect (e.g. no indemnification clause at all), say so
explicitly in the response rather than leaving it silently absent from
the register — an honest "not present" is the correct answer, not a gap
to paper over.


--- SuperDocs call settings for this workflow (do not deviate) ---
- Tool: call `chat` (synchronous) or `chat_async` with `approval_mode="approve_all"` — this command produces new/summary content rather than editing existing binding text, so it applies immediately without a per-change review gate.
- Still show the user the AI's response before exporting, so they can ask for a follow-up edit if something looks off.
- When the work is approved and complete, call `export_document` with format="markdown", options={'filename': 'obligation-register'}.
- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first (docs.superdocs.app/mcp/mcp-setup) before attempting any of the above.
```
