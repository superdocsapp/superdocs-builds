# Document Test Fixtures

This directory contains documentation and test fixtures used to demonstrate the SuperDocs MCP workflow.

## Purpose

The `docs` directory provides a dedicated location for documents that an AI coding agent may need to inspect, edit, or use as reference material through SuperDocs.

Typical workflows include:

1. Identify the document relevant to the user's request.
2. Load or process the document through SuperDocs.
3. Identify the exact section or content that needs to change.
4. Make a targeted edit while preserving unrelated content and formatting.
5. Review or approve the proposed change when required.
6. Verify that the intended change was applied correctly.
7. Export the document when an output file is required.

## Document handling

Use SuperDocs when working with documents where structure or formatting matters, including:

- `.docx` documents
- PDFs
- HTML documents
- Long or heavily formatted documents
- Documents containing tables, borders, shading, or other formatting
- Documents requiring structured or targeted edits

For simple Markdown or plain-text documentation that does not require document-aware processing, normal local editing is sufficient.

## Testing principles

Document-editing workflows should verify that:

- the correct document was selected;
- the requested content was changed;
- unrelated content was preserved;
- document structure and formatting were preserved where applicable;
- sensitive changes received appropriate approval;
- the final result matches the user's request.

This directory is intended for test and demonstration material rather than production document storage.