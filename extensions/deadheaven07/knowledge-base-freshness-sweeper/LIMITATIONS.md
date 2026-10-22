# Honest Limitations & Scope Boundaries (LIMITATIONS.md)

> **SuperDocs Knowledge-Base Freshness Sweeper (Task 2.3)**  
> Clear and explicit documentation of what this system does NOT do, architectural boundaries, and known edge cases.

---

### 1. Cross-Document Logical Contradictions Without Change Anchor
* **What it does**: Detects contradictions when numbers (quotas, limits, sizes) or retired plan names directly clash across articles.
* **What it does NOT do**: It does not infer complex semantic contradictions where two documents express subtly differing domain philosophies unless anchored by a concrete change event or numerical threshold.

### 2. Generative Image & Vector Asset Synthesis
* **What it does**: Scans OCR text, captions, and surrounding context to flag stale UI screenshots requiring replacement.
* **What it does NOT do**: It does not synthesize new PNG/JPEG screenshot assets or automatically re-render browser UI canvases. Replacement of visual assets is routed to human designers or automated visual regression pipelines.

### 3. Complex Markdown Table Reflow with Merged Cells
* **What it does**: Surgically updates table cell values (e.g. `| Pro | 10,000 |` $\rightarrow$ `| Pro | 25,000 |`) while preserving column alignment.
* **What it does NOT do**: It does not restructure multi-row merged HTML tables or dynamically recalculate summary columns spanning multiple rows.

### 4. Video & Audio Tutorial Transcription
* **What it does**: Analyzes markdown text, embedded images, and code snippets.
* **What it does NOT do**: It does not transcribe embedded MP4 video walkthroughs or audio podcasts to identify outdated spoken instructions.

### 5. Multi-Tenant Role-Based Access Control (RBAC) Enforcement
* **What it does**: Provides Human-In-The-Loop review gates and audit logging via SQLite and MCP.
* **What it does NOT do**: It does not manage fine-grained multi-tenant organizational permissions or SSO identity federation.

### 6. Fully Autonomous Unsupervised Production Publishing
* **What it does**: Generates high-confidence proposals and provides a resumable gate interrupt.
* **What it does NOT do**: By design, it does not bypass the human review gate to push direct unreviewed edits to production knowledge bases without human approval.
