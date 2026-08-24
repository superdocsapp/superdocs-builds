# Task 2B: Living Changelog Maintainer

## Overview
This project demonstrates maintaining a public-facing changelog document across software releases. It leverages the SuperDocs MCP integration to implement a "living document" workflow, intelligently inserting new release updates at the correct section without blindly regenerating the entire historical document.

## Why a Living Changelog is Useful
A living changelog allows multiple contributors, AI assistants, and integration tools to continually refine a document while preserving its structure and legacy context. Blindly regenerating documents is risky, loses manual edits, and costs more tokens/time. A smart AI editor acting on a living document ensures stability.

## Architecture
- **Targeted Release Updates:** The script leverages targeted updates for incoming releases, inserting new releases right under the main document header. This ensures that historical releases (Releases 1 through N-1) are preserved **byte-identical**, minimizing drift and preserving manual edits.
- **Offline Generator** (`changelog_generator.py`): Generates a deterministic markdown changelog from mock release data, complete with duplicate detection.
- **Data Models** (`models.py`): Dataclasses mapping standard software release schemas (version, date, added, improved, fixed).
- **Mock Data** (`mock_data.py`): Contains historical release chunks.
- **Tests** (`tests/test_changelog.py`): Validates ordering, duplication protection, targeted byte-identical insertions, and stopping rules.
- **Live Workflow**: Uses SuperDocs MCP to ingest the generated markdown, start a session, propose an update (with human-in-the-loop approval), and export the updated file.

## Execution Rules & Protections

### Preview / No-Spend Mode
The script has an explicit preview mode (run with `python changelog_generator.py --preview`). In preview mode, the maintainer:
- Uses only local/mock data.
- Shows the proposed changelog operation diff.
- Performs **ZERO** SuperDocs MCP operations and **ZERO** remote model calls.
- Never uploads, chats, approves, or exports data.

### Stopping Condition
The maintainer strictly implements an explicit stopping rule: it will only process **one release per invocation** and then stop. It does not implement an infinite polling loop.

### Self-Trigger Protection
To prevent infinite loops, the exported/published changelog is strictly separated from the source changelog.
- Source data resides in `source/changelog.md`
- Exported artifacts reside in `export/changelog.md`
This prevents the updated changelog from automatically becoming a new input release on the next run.

### SuperDocs MCP Workflow (Live)
When run without `--preview`, the script natively executes the SuperDocs MCP orchestration over the HTTP REST API endpoints using Python `requests`:
1. **Upload**: Base64 encodes the `export/changelog.md` and initializes a session.
2. **Chat**: Prompts the AI model via `chat_async` to insert the new release chunk.
3. **Approve**: Polls the job status and issues `approve_change` to commit the AI's byte-identical insertion.
4. **Export**: Polls for completion and runs `export_document` to fetch the DOCX/PDF download URL.

## Human Approval (HITL)
By supplying `approval_mode="ask_every_time"`, the AI does not immediately apply changes. A human operator reviews the `proposed_change_batch` block, confirming that the new version `v2.4.0` is properly categorized (Added, Improved, Fixed) and inserted before the older versions. Only upon an explicit `approve_change` call does the document version advance.

## Export Workflow
The final artifact is retrieved using `export_document`, obtaining a short-lived signed URL to download the finished document (e.g. `Product Changelog.docx`).



## Environment Variables
- Standard SuperDocs environment variables (`SUPERDOCS_API_KEY`, etc.) as required by the MCP server running in the background.

## Known Limitations
- The current offline generator relies on strict version string sorting. Advanced semantic versioning libraries may be required for complex edge cases (e.g. `v2.10.0` vs `v2.2.0`).
- The `export_document` currently defaults to DOCX; if Markdown is preferred, the `format` parameter needs to be specified when calling the tool.
