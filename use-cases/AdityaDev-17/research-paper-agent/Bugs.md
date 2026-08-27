# Bugs encountered during development

A log of real issues hit while building this project, root cause, and how each was resolved. Kept for the record and in case any of these are useful to report upstream to SuperDocs.

---

## 1. Empty `<p></p>` placeholder silently stripped on document load
**Symptom:** Every drafted section's content vanished on export — only headings survived, no body text, despite drafting and verification both reporting success.
**Root cause:** The initial document skeleton used `<h2>Title</h2><p></p>` (empty paragraph placeholder). SuperDocs' HTML parser silently discards truly empty `<p></p>` elements on load, leaving no addressable chunk under the heading for later edits to target.
**Fix:** Skeleton paragraphs now contain non-empty placeholder text (`[Placeholder: content for the X section will be added here.]`), giving every section a real, addressable chunk from the start.
**Status:** Fixed — confirmed via isolated diagnostic script before re-running the full pipeline.

## 2. `chat` edits silently pending approval, never applied
**Symptom:** `edit_section` calls returned successfully (no error) but content still never appeared in the exported document.
**Root cause:** Not a SuperDocs bug — working as designed. `chat` can return `document_changes.requires_approval: true` with the actual edit sitting in `pending_changes`, waiting for a human-in-the-loop decision via `approve_change`, rather than applying immediately. The client code only handled the direct-apply case.
**Fix:** `SuperDocsMCPClient._resolve_html` now detects `requires_approval`, auto-approves every pending change (our own retrieval + verification pipeline already vetted the content before it reached SuperDocs), then polls `get_job` until `status == "completed"` and pulls the final HTML from `result.document_changes.updated_html`.
**Status:** Fixed.

## 3. `anyio` cancel-scope crash on client shutdown
**Symptom:** `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in`, thrown during `SuperDocsMCPClient.close()` — after the actual pipeline work had already completed successfully.
**Root cause:** The MCP connection was opened in one `asyncio.run_until_complete()` call and closed in a separate one. Each call runs as its own top-level asyncio Task, but `anyio`'s cancel-scope machinery (used internally by `httpx2` and the streamable HTTP transport) requires a context manager to be entered and exited within the same task.
**Fix:** Rewrote the client to run its entire connection lifetime (open, every call, close) as one continuous coroutine on a dedicated background thread, with individual calls dispatched into that persistent task via `run_coroutine_threadsafe` rather than started as separate top-level runs.
**Status:** Fixed.

## 4. `mcp` SDK v1 → v2 breaking changes
**Symptom:** Multiple `AttributeError`s (`'Tool' object has no attribute 'inputSchema'`, `'CallToolResult' object has no attribute 'isError'`) and a `TypeError` on `streamablehttp_client(..., headers=...)`.
**Root cause:** `requirements.txt` didn't pin an `mcp` version; `uv pip install` picked up v2.1.0, which reworked the client API (new `Client` class replacing `ClientSession`, snake_case field names, header auth moved to a separate `httpx2.AsyncClient`) relative to the v1 documentation patterns initially assumed.
**Fix:** Rewrote the client against the real installed version's API, confirmed via `uv pip show mcp` and the official v2 SDK docs.
**Status:** Fixed. `requirements.txt` still doesn't pin an exact version — worth revisiting if `mcp` ships a v3.

## 5. `get_job` polling timeout too short for real content
**Symptom:** `TimeoutError: Job ... did not complete within 30.0 seconds` — only in the Streamlit app, never in the small isolated diagnostic test.
**Root cause:** The isolated test used one short sentence; real sections (2000+ characters, 10-15 citations) take SuperDocs longer to process through the approval pipeline than the original 30-second budget allowed.
**Fix:** Raised the poll budget to 90 attempts × 2s (180s total), and the timeout error now reports the job's last known status for easier future debugging.
**Status:** Fixed.

## 6. `faiss-cpu` missing from `requirements.txt`
**Symptom:** None visible at first — `faiss` imported fine anyway, because a transitive dependency (likely `langchain-community`) happened to pull it in.
**Root cause:** Listed in the design doc but never actually added to the real `requirements.txt`.
**Fix:** Added as an explicit, direct dependency rather than relying on an indirect one that could disappear if an unrelated package's dependency tree changes.
**Status:** Fixed.

## 7. Word (.docx) export — `PermissionError` on repeated export
**Symptom:** `PermissionError: [Errno 13] Permission denied: 'exports\SuperDocs Document.docx'` on export.
**Root cause:** SuperDocs names every export `SuperDocs Document.<ext>` regardless of session — re-exporting docx while a previous copy of that exact filename is open in Word (or locked by antivirus scanning) causes Windows to deny the overwrite. Not a SuperDocs or pipeline bug — a local file-locking collision from reusing a fixed filename.
**Fix:** Word export removed from the app entirely (HTML and PDF cover the needed formats and never hit this issue, since neither is typically held open by another program the way a docx tends to be).
**Status:** Worked around, not fixed at the root — reintroducing docx export later would need either a unique filename per export or an explicit overwrite-retry/close-handle step.

## 8. Script-relative imports (`ModuleNotFoundError: No module named 'src'`)
**Symptom:** Running any `scripts\*.py` file directly failed to import from `src/`, even though `pytest` never had this problem.
**Root cause:** Running `python scripts\foo.py` only adds `scripts\` to `sys.path`, not the project root — `pytest` handles rootdir discovery itself, masking this for the test suite.
**Fix:** Every standalone script explicitly inserts the project root onto `sys.path` at the top, before importing anything from `src`.
**Status:** Fixed.