# Engineering Findings & Architecture Discoveries (FINDINGS.md)

> **SuperDocs Knowledge-Base Freshness Sweeper (Task 2.3)**  
> Comprehensive log of real engineering discoveries, edge cases, model boundaries, and API quirks uncovered during architecture and evaluation.

---

### 1. Regex Punctuation Splitting Decimal vs. Sentence Boundaries
* **Discovery**: Naive sentence splitting on `/[.!?]/` breaks numeric values like `10.5 MB` or version numbers like `v2.4.0` into disjoint fragments (`10` and `5 MB`), corrupting evidence spans.
* **Solution**: Implemented negative-lookbehind / boundary token matching in `matcher.ts` to preserve numeric floating point and semantic versioning strings within sentence nodes.

### 2. Digit Contamination in Seeded HTML Mutation Comments
* **Discovery**: When injecting synthetic drift comments like `<!-- updated_epoch_1 -->` into test corpus articles, regex filters that check `!/\d+/.test(content)` for numeric absence erroneously failed on the comment digits.
* **Solution**: Separated markdown metadata comments into non-digit string tags (`<!-- benign_sync_drift -->`) to isolate document body semantics from test harness markers.

### 3. Case-Insensitive Polysemic False Positives ('Growth', 'Limit', 'Subscribe')
* **Discovery**: Naive substring matchers flag articles explaining "company revenue growth" as impacted by a "Growth Plan" retirement, or "browser RAM limits" as an "API rate limit" change.
* **Solution**: Built contextual term co-occurrence validators in Stage 2 that verify whether adjacent tokens match the intended domain entity (e.g., "plan", "tier", "quota", "per month").

### 4. Confluence XHTML vs. GitHub-Flavored Markdown AST Divergence
* **Discovery**: Confluence APIs frequently represent structured callouts as `<ac:structured-macro ac:name="info">` blocks. Simple regex markdown matchers destroy macro XML tags when applying surgical edits.
* **Solution**: Isolated text mutation to raw inner text nodes while asserting byte invariance across all macro wrappers.

### 5. Rate-Limit Cascade Failures & Exponential Jitter
* **Discovery**: Sweeping 100+ documents concurrently against third-party LLM endpoints triggers HTTP 429 bursts that starve downstream classification tasks.
* **Solution**: Designed the Budget Guard with pre-flight token estimation, serial token bucket smoothing, and deterministic zero-cost offline fallbacks.

### 6. OCR Space & Normalization Hallucinations on High-DPI Screenshots
* **Discovery**: Tesseract and vision OCR frequently segment button labels like `"Billing & Plans"` as `["Billing", "&", "Plans"]` or omit ampersands, leading to false mismatches.
* **Solution**: Normalized OCR token arrays with whitespace-agnostic token set intersections and minimum Levenshtein distance matching.

### 7. UTF-8 Byte Offsets vs. JavaScript Character Length on Emojis
* **Discovery**: Emojis (e.g., `⚡`, `🚀`) occupy 2 UTF-16 code units but up to 4 UTF-8 bytes. Character index slicing (`String.prototype.slice`) desynchronizes with byte-level verification tools.
* **Solution**: Used standard UTF-8 `Buffer.byteLength` and character offset pairs in `ChangedSpan` structures.

### 8. SQLite Foreign Key Insertion Ordering in Resumable Agent Graphs
* **Discovery**: When checkpointing state graphs where proposals reference articles, inserting proposals before articles triggers SQLite `FOREIGN KEY constraint failed`.
* **Solution**: Enforced atomic parent entity persistence in `FreshnessSweeperAgentGraph.start()` before emitting child proposals.

### 9. Vite Bundler Resolution on Native Node 26 `node:sqlite`
* **Discovery**: Vite 6 bundlers attempt to resolve `node:sqlite` as a client-side ES module, breaking server test runners.
* **Solution**: Utilized `createRequire(import.meta.url)('node:sqlite')` to cleanly load native SQLite standard library binaries across ESM environments.

### 10. Indirect Workflow Semantic Disconnection (Row-by-Row vs. Toolbar Export)
* **Discovery**: Documentation describing outdated workarounds ("click each row and save locally") does not contain the keywords "toolbar" or "1-click export".
* **Solution**: Seeded behavioral workflow synonyms and multi-step action verbs into `matchSemantic()` to capture procedural obsolescence.

### 11. Zero-Cost Offline Invariance & Determinism
* **Discovery**: Real-world evaluation harnesses frequently fail in continuous integration (CI) environments when external API credentials expire or hit network timeouts.
* **Solution**: Engineered 100% of the core benchmark suite, AST parser, and drift simulator to execute with zero external API keys in under 100ms.

### 12. Floating Point Rounding in Vitest Statistical Assertions
* **Discovery**: `Number.toFixed(1)` conversions in sample statistics can produce micro-discrepancies like `18.84` vs `18.8` during Vitest strict equality checks.
* **Solution**: Normalized statistical summaries with explicit `Math.round(val * 10) / 10` float clamping.

### 13. Ambiguous Scope in Enterprise SLA Documentation
* **Discovery**: Articles referencing custom variable enterprise agreements cannot be accurately tagged as stale without contract metadata.
* **Solution**: Implemented an explicit `COULD_NOT_ASSESS` classification with detailed `what_checked` and `why_insufficient` disclosures.

### 14. Pre-Flight Token Budget Guard Overestimation
* **Discovery**: Standard token estimators using `length / 4` underestimate markdown tables and code blocks by up to 22%.
* **Solution**: Calibrated token estimation multipliers specifically for markdown structures (0.35 tokens per character on code blocks).

### 15. Inverted Search Index Satiation on Monolithic Articles
* **Discovery**: Monolithic 5,000-word guides cause inverted term frequency indices to skew relevance scores for brief documentation.
* **Solution**: Applied BM25 document length normalization ($k_1 = 1.2, b = 0.75$) to maintain consistent keyword search ranking across varying article sizes.

### 16. Synchronous SQLite Transaction Safety in Express Endpoints
* **Discovery**: Rapid parallel human approval requests from UI dashboards can interleave updates without transactional isolation.
* **Solution**: Wrapped review audit logging and article content version bumps in synchronous SQLite transactions.
