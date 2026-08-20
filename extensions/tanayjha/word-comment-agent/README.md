# Word Comment-Driven Agent for SuperDocs

> **Credit Line**: *built this for the SuperDocs engineering task*

An MCP extension that reads unresolved Word (`.docx`) comments, maps each comment to its exact anchored text range in OpenXML, sends scoped edit instructions to the SuperDocs REST API, presents proposed revisions for Human-in-the-Loop review (approve/reject/override), and surgically writes approved edits back into the original `.docx` file while resolving comment threads.

---

## 🎯 Why This Extension Exists

Editorial and legal workflows live in Word comment threads. When reviewers leave comments like *"Make this more concise"* or *"Clarify that these are contract drivers"*, existing AI tools typically rewrite the entire document or convert to HTML/Markdown and back — destroying surrounding styles, tracked changes, footnotes, and un-commented sections.

The **Word Comment-Driven Agent** solves this by establishing a surgical, human-gated workflow:
* **Exact Anchor Scoping**: Comment instructions are isolated to their specific XML text range (`w:commentRangeStart` to `w:commentRangeEnd`), even when anchor spans cross multiple formatting runs.
* **Option B Architectural Ownership**: SuperDocs AI provides document intelligence; our local `docx_writer.py` performs in-place OpenXML range replacements directly on the source `.docx`. Un-commented document text, headers, footers, and styles remain **100% byte-for-byte untouched**.
* **Honors "No Change Needed"**: Evaluates reviewer comments like *"No change needed — confirmed accurate"* or *"LGTM"* and skips AI calls automatically without modifying text.
* **Strict Human-in-the-Loop Gate**: Edits are never applied without explicit approval. Rejected comments remain unmodified and unresolved.
* **Thread Resolution**: Approved comments update their anchor text and mark the thread resolved (`w:done="1"` in `word/comments.xml`).

---

## 🏗️ System Architecture

```text
       Original .docx (with unresolved comments)
                         │
                         ▼
        ┌───────────────────────────────────┐
        │       inspect_word_comments       │  (docx_parser.py)
        │ • Reads word/comments.xml         │
        │ • Maps comment ID ➔ anchor range   │
        │ • Detects "no change needed"      │
        └─────────────────┬─────────────────┘
                          │
                          ▼
        ┌───────────────────────────────────┐
        │       propose_comment_edits       │  (superdocs_client.py)
        │ • Uploads doc / isolated session  │
        │ • Scoped async edit instructions  │
        │ • Progressive polling backoff     │
        │ • Generates review_id + proposals │
        └─────────────────┬─────────────────┘
                          │
                          ▼
        ┌───────────────────────────────────┐
        │      review_comment_changes       │  (Human Review Gate)
        │ • Accepts approve / reject list   │
        │ • Supports human override text    │
        │ • Notifies SuperDocs /approve     │
        └─────────────────┬─────────────────┘
                          │
                          ▼
        ┌───────────────────────────────────┐
        │       export_word_document        │  (docx_writer.py)
        │ • Stale review session protection │
        │ • Trims echoed prefix/suffix      │
        │ • Neutralizes unwanted bold bleed │
        │ • In-place OpenXML range mutation │
        │ • Sets w:done="1" on comments     │
        │ • Post-export verification oracle │
        └─────────────────┬─────────────────┘
                          │
                          ▼
             Final Processed .docx
```

---

## 🚀 Quickstart & Setup

### 1. Installation (One Documented Command)

From a fresh clone:

```bash
cd extensions/tanayjha/word-comment-agent
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

### 2. Configure Environment

Set your SuperDocs API key (never commit credentials to git):

```bash
export SUPERDOCS_API_KEY="sk_your_api_key_here"
```

> **Offline Mock Mode**: If `SUPERDOCS_API_KEY` is omitted or set to `"mock"`, the extension automatically switches to offline mock mode, allowing full local development and testing without a live API key.

### 3. Run the MCP Server

Run over STDIO (standard for MCP clients):

```bash
source .venv/bin/activate && python -m src.mcp_server
```

Or run hosted over SSE / HTTP on a port:

```bash
export MCP_TRANSPORT="sse"
export PORT=8000
python -m src.mcp_server
```

---

## 🔌 Connecting to MCP Clients (Cursor, Windsurf, Claude Desktop)

Add the server to your `mcp.json` / Claude Desktop configuration:

```json
{
  "mcpServers": {
    "superdocs-word-comment-agent": {
      "command": "/absolute/path/to/extensions/tanayjha/word-comment-agent/.venv/bin/python",
      "args": ["-m", "src.mcp_server"],
      "env": {
        "SUPERDOCS_API_KEY": "sk_your_api_key_here",
        "PYTHONPATH": "/absolute/path/to/extensions/tanayjha/word-comment-agent"
      }
    }
  }
}
```

---

## 🛠️ MCP Tools Reference

The server exposes 4 domain-specific FastMCP tools:

### 1. `inspect_word_comments`
* **Purpose**: Parses `.docx` XML to extract all unresolved comments and their exact anchor text.
* **Arguments**:
  * `file_path` (*string*): Absolute path to the Word `.docx` file.
* **Returns**: Document path, unresolved count, and structured comment objects (`comment_id`, `author`, `instruction`, `anchor_text`, `no_change_needed`).

### 2. `propose_comment_edits`
* **Purpose**: Sends scoped edit instructions to SuperDocs AI, polls for results, and returns proposed revisions mapped to comment IDs.
* **Arguments**:
  * `file_path` (*string*): Path to the Word `.docx` file.
  * `comment_ids` (*optional list*): Subset of comment IDs to propose edits for.
* **Returns**: `review_id`, proposals count, and proposal list with original anchor text and AI-proposed revisions. Auto-skips comments requesting no changes.

### 3. `review_comment_changes`
* **Purpose**: Records human approve/reject decisions (and optional override text) for a review session.
* **Arguments**:
  * `review_id` (*string*): Review ID returned by `propose_comment_edits`.
  * `decisions` (*list*): Array of decisions: `[{"comment_id": "0", "approved": true, "override_text": "Optional final text"}]`.
* **Returns**: Approved comment IDs, rejected comment IDs, and status.

### 4. `export_word_document`
* **Purpose**: Surgically writes approved edit replacements to target anchor ranges in the original `.docx` and marks comment threads resolved (`w:done="1"`).
* **Arguments**:
  * `review_id` (*string*): Active review session ID.
  * `output_path` (*string*): Output path for the updated `.docx` file.
* **Returns**: Applied edits count, resolved comments count, `verified: true`, and `verification_status: "success"`.

---

## 💡 Example Workflow

```python
# 1. Inspect unresolved comments in document
comments = inspect_word_comments(file_path="vendor_overview.docx")

# 2. Propose scoped AI revisions via SuperDocs
proposals = propose_comment_edits(file_path="vendor_overview.docx")
review_id = proposals["review_id"]

# 3. Human Review Gate: Approve comments 0 & 1, reject comment 3
review_comment_changes(
    review_id=review_id,
    decisions=[
        {"comment_id": "0", "approved": True},
        {"comment_id": "1", "approved": True},
        {"comment_id": "3", "approved": False}
    ]
)

# 4. Export final document with surgical write-back
result = export_word_document(
    review_id=review_id,
    output_path="vendor_overview_approved.docx"
)
```

---

## ⚡ SuperDocs API Hardening & Quirks Handled

- **Cold-Session Warm-up Retry**: Automatically retries initial requests once upon cold-session failure to handle backend spin-up transparently.
- **Session Isolation (`session_busy` 409 Resolution)**: Scopes edits per comment session (`session_{review_id}_{comment_id}`) so multi-comment batches process in parallel without session conflict errors.
- **Progressive Polling Backoff**: Polls `GET /v1/jobs/{job_id}` with progressive backoff (2s → 5s → 10s) and a 10-minute timeout budget, treating `pending`/`in_progress` as normal processing states.
- **Double JSON Parsing**: Double-parses stringified JSON diff card strings returned by the API into structured objects.
- **Mandatory Approval Field**: Enforces top-level `"approved": true` in approval payload schemas (`POST /v1/chat/{session_id}/approve`) to prevent HTTP 422 errors.
- **HTML Sanitization**: Strips wrapper `<p data-chunk-id="...">` and `<span data-comment-ref="...">` tags from API diffs before writing clean plain text to Word runs.

---

## 🛡️ Edge Case Hardening & Defenses

1. **Stale Review Session Protection**: `LATEST_REVIEW_PER_COMMENT` tracks the active `review_id` for every comment. If a comment is re-proposed and an agent attempts to export a superseded `review_id`, execution is rejected with a clear `ValueError`.
2. **Context Duplication Prevention**: If an AI proposal echoes surrounding paragraph context (e.g. paragraph prefix or suffix), `docx_writer.py` inspects preceding and following text nodes and strips duplicates before write-back.
3. **Run-Level Style Bleed Prevention**: When anchor text is not bold in the original document, unwanted `<w:b/>` tags on the target run are removed and `<w:b w:val="0"/>` is appended to prevent style bleed.
4. **Post-Export Verification Oracle**: After saving the output `.docx`, the writer re-parses `word/document.xml` to verify character-for-character range accuracy against human approval, returning `verified: true`.

---

## 🧪 Automated Testing

Run the complete pytest suite (runs 100% offline without live API keys):

```bash
source .venv/bin/activate && PYTHONPATH=. pytest -v tests/test_agent.py
```

### Verified Test Cases:
* `test_post_export_verification`: Validates character-for-character verification oracle.
* `test_p4_stale_text_regression`: Proposes, re-proposes, and verifies the latest proposal is exported.
* `test_stale_review_id_rejection`: Confirms attempting to export a superseded review ID raises `ValueError`.
* `test_override_text_in_review`: Validates that human override text updates proposal text prior to export.
* `test_no_text_duplication`: Asserts mid-run anchor replacements do not duplicate surrounding paragraph text.
* `test_formatting_preservation`: Asserts unwanted bolding is not introduced on unbolded anchor runs.

---

## 📋 Trade-offs & Limitations (Defended Cut & Boundaries)

- **Defended Cut — Inline Formatting Directives**: Formatting-only instructions (e.g. "make this bold" or "italicize this phrase") represent a small fraction of real editorial comments. We cut natural language style parsing to prioritize range-precision and human-gate correctness. The writer preserves existing base document styling and anchor formatting without inventing new formatting rules from comment text.
- **Contiguous Ranges**: Current implementation targets contiguous comment anchor ranges. Overlapping or nested comment ranges return clear errors rather than mutating text ambiguously.
- **OpenXML Resolution**: Uses standard OpenXML `w:done="1"` attribute on `<w:comment>` elements in `word/comments.xml` to resolve threads.

---

*Built for the SuperDocs engineering task.*
