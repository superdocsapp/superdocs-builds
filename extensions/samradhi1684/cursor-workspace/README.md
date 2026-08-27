## One-minute quick start

1. Set `SUPERDOCS_API_KEY` in your environment.
2. Open this folder in Cursor.
3. Open the document you want to edit.
4. Ask Cursor what you want changed in plain English.

For example:

> Change Section 4 so that the contract term is three years. Preserve the existing formatting and leave all other sections unchanged.

You do not need to specify SuperDocs tools or chunk IDs. The workspace rules guide Cursor toward the appropriate SuperDocs workflow.


# SuperDocs Cursor Workspace

This workspace is a minimal example showing how an AI coding agent can use the SuperDocs MCP server to edit documents while preserving document structure and formatting.

## Purpose

The workspace demonstrates an end-to-end document-editing workflow:

1. Connect Cursor to the SuperDocs MCP server.
2. Load a document into a SuperDocs session.
3. Make a targeted natural-language edit.
4. Review the proposed change.
5. Apply the approved change.
6. Verify that only the intended content changed.
7. Export the document when needed.

## Workspace structure

```text
cursor-workspace/
├── .cursor/
│   ├── mcp.json
│   └── rules/
│       └── superdocs.mdc
├── docs/
│   └── README.md
└── README.md
```

## MCP configuration

The `.cursor/mcp.json` file connects Cursor to the SuperDocs MCP server.

The API key is supplied through the `SUPERDOCS_API_KEY` environment variable rather than being committed to the repository.

Before using the workflow, verify that:

- `SUPERDOCS_API_KEY` is available to the Cursor process.
- the SuperDocs MCP server is connected;
- SuperDocs tools are visible in the agent/tool environment.

Example request:

> Change the annual leave allowance from 20 days to 25 days. Do not change anything else.

For sensitive edits, the agent should use SuperDocs human-in-the-loop approval and verify the resulting document afterward.

## What this demonstrates

This example is designed to demonstrate:

- MCP server connectivity
- natural-language document editing
- targeted rather than whole-document rewriting
- approval before applying a sensitive change
- post-edit verification
- preservation of unrelated document content

## Testing

A successful test should show:

- the SuperDocs MCP server is authenticated;
- the document is loaded into a SuperDocs session;
- the requested sentence is changed;
- unrelated sections remain unchanged;
- the final local document contains the expected edit.

Do not commit API keys or other credentials to this repository.

## SuperDocs

SuperDocs provides MCP tools for creating, editing, restructuring, and exporting formatted documents.
