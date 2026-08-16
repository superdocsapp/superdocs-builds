---
trigger: model_decision
description: Route document edits (docx, pdf, html) through SuperDocs MCP tools instead of touching the file directly
---

# Route document edits through SuperDocs

When the user asks to create, revise, redline, or otherwise edit a `.docx`, `.pdf`, or `.html` file in this workspace, do NOT open, parse, or write that file directly with filesystem or shell tools. Route it through the `superdocs` MCP server instead:

1. Load the file into SuperDocs: call `upload_document_base64` for small files, or `request_upload_url` followed by `process_uploaded_document` for anything over roughly 100KB (avoids inflating this context with a large base64 blob).
2. Make the requested change: call `chat` for a quick, synchronous edit, or `chat_async` for a large or long-running one.
3. If the response includes `pending_changes` (SuperDocs' Review mode), do not assume approval. Show the proposed changes to the user in plain language and call `approve_change` only after they confirm -- or after you've applied your own judgment for a low-risk, clearly-requested change, exactly as you would for any other tool call with side effects.
4. Call `export_document` to produce the finished file in its original format, and write that result back to the workspace path the user expects.

Only fall back to editing the file directly if the `superdocs` MCP server is unreachable (a tool call errors or times out) -- and say so explicitly to the user before doing it. Never silently fall back.

This rule does not apply to plain-text formats (`.md`, `.txt`, code files) -- those are fine to edit directly as usual.

## Gotchas (from SuperDocs' own MCP-server-advertised guide, docs.superdocs.app/skill.md)

- **Reuse one stable `session_id` per document conversation.** Do not generate a fresh one per turn -- the server keeps the document between turns, so re-sending it wastes context and can desync from what SuperDocs actually has.
- **Don't resend the full document HTML on every turn.** Only pass `document_html` again if the file changed *outside* the chat (e.g. a human edited it directly) since your last message.
- **Verify with `get_document_detail` (structure only), not a full export.** Checking `structure.headings`/`section_count`/`block_count` costs nothing and is enough to sanity-check an edit landed; exporting just to check wastes a round trip (exports themselves are free, but the check should happen before you decide you even need one).
- **Never strip `data-chunk-id` attributes** if you're inspecting or re-serializing HTML you got back -- that's how SuperDocs targets edits to a specific section on the next turn.
- **A failed or already-satisfied edit costs nothing.** If SuperDocs reports it couldn't make a change (or the document already matched the request), no operation was billed -- don't treat that as something to retry differently by default, just relay it to the user.
