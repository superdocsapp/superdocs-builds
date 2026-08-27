# `/legal:draft_from_playbook`

Real output from `session.get_prompt("draft_from_playbook", ...)` against the actual running server
(`python -m vertical_prompts.server --pack packs/legal/pack.yaml`) — captured, not hand-written.
Regenerate with `python scripts/capture_transcripts.py`.

**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):

```
/legal:draft_from_playbook
  document_type: 'a mutual NDA'
  counterparty: 'Northwind Logistics GmbH'
  key_terms: '2-year term, mutual confidentiality, Delaware law, 30-day termination for convenience'
```

**Rendered prompt message the assistant receives:**

```
Draft a mutual NDA with Northwind Logistics GmbH, using the firm's own saved
template as the starting point.

Key terms to incorporate: 2-year term, mutual confidentiality, Delaware law, 30-day termination for convenience

Fill in the template's existing structure rather than restructuring it —
the house template's clause order, defined terms, and formatting are
deliberate. Where the template has a placeholder or bracketed field the
key terms above don't cover, leave the bracket visibly in place for the
attorney to complete; do not quietly pick a value for it.


--- SuperDocs call settings for this workflow (do not deviate) ---
- Templates: call `list_user_templates` FIRST and draft from the user's own saved template. Match on document type (NDA, MSA, SOW) and prefer the firm's most recent version of it. If no saved template matches, say so and offer to have them upload one with `upload_template_base64` — do NOT invent house-standard language to fill the gap. Drafting a clause the organisation never approved, in a document that looks like theirs, is worse than an honest 'you have no template for this yet'.
- Tool: call `chat` (synchronous) or `chat_async` with `approval_mode="approve_all"` — this command produces new/summary content rather than editing existing binding text, so it applies immediately without a per-change review gate.
- Still show the user the AI's response before exporting, so they can ask for a follow-up edit if something looks off.
- When the work is approved and complete, call `export_document` with format="docx", options={'filename': 'draft-from-template'}.
- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first (docs.superdocs.app/mcp/mcp-setup) before attempting any of the above.
```
