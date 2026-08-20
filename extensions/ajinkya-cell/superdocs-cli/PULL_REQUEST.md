# ⚡ feat(extensions): Node.js Developer CLI Assistant for Superdocs

### 👤 Contributor Information
- **Full Name**: Ajinkya Dharkar
- **GitHub Handle**: [@ajinkya-cell](https://github.com/ajinkya-cell)
- **NPM Package**: [`@ajinkya-cell/superdocs-cli`](https://www.npmjs.com/package/@ajinkya-cell/superdocs-cli)
- **Attribution**: Built for the SuperDocs Task.

---

### 📦 NPM Package & Instant Run

This extension is published and distributed on the NPM registry as [`@ajinkya-cell/superdocs-cli`](https://www.npmjs.com/package/@ajinkya-cell/superdocs-cli).

```bash
# ⚡ Run instantly with npx (No install required)
npx @ajinkya-cell/superdocs-cli --help

# Or install globally
npm install -g @ajinkya-cell/superdocs-cli
superdocs --help
```

---

### 📖 Summary & Motivation

`@ajinkya-cell/superdocs-cli` brings the power of **[SuperDocs](https://superdocs.app)** AI document intelligence and precision in-document editing straight to the terminal and agentic workflows.

Unlike standard conversational AI chat interfaces that force developers into tedious copy-pasting and break document structure:
- **Surgical In-Document Edits**: Performs localized, context-aware mutations while preserving headings, formatting, tables, and surrounding text.
- **Visual Terminal Unified Diffs**: Generates color-coded Git-style terminal diffs (`+additions` / `-deletions`) powered by the Myers diff algorithm.
- **Interactive Approval Gates**: Changes are held in a staged sandbox (`PendingVersion`) until explicitly accepted or rejected.
- **Multi-Format Ingestion & Compilation**: Ingest `.md`, `.txt`, `.docx`, or `.pdf` files, edit via streaming AI, and compile directly to clean `.md`, `.pdf`, `.docx`, or `.html`.

---

### 🛠️ Key Features & Architecture

```
┌────────────────────────────┐      ┌───────────────────────────┐      ┌────────────────────────────┐
│      Raw Document          │ ───► │   SuperDocs In-Document   │ ───► │   Terminal Diff Review &   │
│  (.md, .pdf, .docx, .txt)  │      │     Surgical AI Stream    │      │  Multi-Format Compilation  │
└────────────────────────────┘      └───────────────────────────┘      └────────────────────────────┘
```

- 🚀 **4 Core Contract Operations**:
  1. `superdocs upload <file>`: Multi-format document ingestion (`.md`, `.txt`, `.docx`, `.pdf`).
  2. `superdocs edit --prompt "<instruction>"`: Streaming AI surgical edits with real-time reasoning progress.
  3. `superdocs approve`: Interactive terminal visual diff review with one-click server lock or `--ci` Markdown PR comment output.
  4. `superdocs export --format <pdf|docx|md|html>`: Compile and download finalized documents.
- 💬 **Interactive Chat REPL** (`superdocs chat`): Continuous conversational refinement loop with inline slash commands (`/diff`, `/approve`, `/export`, `/status`, `/exit`).
- 🤖 **Automated Agent Onboarding** (`superdocs init --signup`): Integrates with `POST /v1/agents/signup` for instant credential provisioning.
- 🔌 **Model Context Protocol (MCP)**: Native MCP adapter exposing 6 SuperDocs tools to Claude Desktop, Cursor IDE, and agentic workflows.
- 🧪 **Offline Simulation / Mock Engine**: Built-in mock mode (`--mock` or `SUPERDOCS_MOCK=true`) for testing without active network credentials.
- 🔒 **Persistent Session & Config**: Powered by `conf` to maintain active document context across terminal sessions.

---

### 💻 Complete CLI Command Reference

```bash
# 1. Initialize credentials, agent signup, or offline mock mode
superdocs init
superdocs init --signup          # Auto-provisions API key via POST /v1/agents/signup
superdocs init --mock            # Offline simulation mode (no API key needed)

# 2. Ingest document and bind active session
superdocs upload ./specs/architecture.md
superdocs upload ./resume.pdf

# 3. Surgical AI edit via streaming prompts
superdocs edit -p "Add error handling status codes table and rate limiting documentation"

# 4. Review visual terminal diff and approve/reject
superdocs approve                # Interactive terminal diff review
superdocs approve --write-file   # Sync approved changes back to local disk
superdocs approve --ci           # Non-interactive GitHub PR Markdown diff output

# 5. Export finalized document to target format
superdocs export --format pdf --out ./dist/api.pdf
superdocs export --format docx --out ./dist/api.docx
superdocs export --format md --out ./dist/api.md

# 6. Interactive Chat REPL Mode
superdocs chat

# 7. Check session state, active document, and edit history
superdocs status
```

---

### 🤖 Model Context Protocol (MCP) Tools

`@ajinkya-cell/superdocs-cli` exports 6 MCP-compliant tools in `src/client/mcp-adapter.ts` for Claude Desktop, Cursor, and AI agents:

| MCP Tool | Description | Parameters |
| :--- | :--- | :--- |
| `superdocs_signup` | Automatically provision agent credentials | `agent_name` (optional) |
| `superdocs_upload` | Ingest local documents into active workspace session | `filePath` (required), `content` (optional) |
| `superdocs_edit` | Execute natural language edits with streaming diffs | `prompt` (required) |
| `superdocs_approve` | Commit or reject pending diffs | `accept` (boolean, required) |
| `superdocs_export` | Export compiled document to disk in target format | `format` (required), `outputPath` (required) |
| `superdocs_get_status` | Inspect active document session and configuration | `{}` |

---

### 🧪 Test & Run Instructions

```bash
# 1. Navigate to directory & install dependencies
cd extensions/superdocs-cli
npm install

# 2. Build TypeScript to dist/
npm run build

# 3. Run the automated test suite (11 unit tests passing)
npm test

# 4. Quick smoke test in offline simulation mode
node dist/bin/index.js init --mock
node dist/bin/index.js upload README.md
node dist/bin/index.js edit -p "Add troubleshooting guide"
node dist/bin/index.js approve
node dist/bin/index.js status
```

#### Test Suite Verification:
```
▶ SuperDocs CLI Test Suite
  ✔ Diff Generator (accurately calculates line additions and deletions)
  ✔ Diff Generator (handles identical documents gracefully)
  ✔ Persistent State & Session (persists and updates configuration correctly)
  ✔ Persistent State & Session (persists active document session and history)
  ✔ SuperDocs Client Engine (performs mock agent signup)
  ✔ SuperDocs Client Engine (uploads document and generates session payload)
  ✔ SuperDocs Client Engine (streams AI surgical edits with progress callbacks)
  ✔ SuperDocs Client Engine (approves and commits proposed versions)
  ✔ SuperDocs Client Engine (exports documents in target formats)
  ✔ MCP Adapter (exposes all required MCP tools)
  ✔ MCP Adapter (executes end-to-end workflow through MCP calls)
✔ SuperDocs CLI Test Suite (11 passed, 0 failed)
```

---

### 📁 Extension Directory Structure

```
extensions/superdocs-cli/
├── bin/
│   └── index.ts               # CLI executable entrypoint
├── src/
│   ├── client/
│   │   ├── mcp-adapter.ts     # Model Context Protocol tools & dispatcher
│   │   └── superdocs.ts       # SuperDocs REST/SSE client & mock engine
│   ├── commands/
│   │   ├── approve.ts         # Visual diff review & commit command
│   │   ├── chat.ts            # Interactive terminal REPL chat engine
│   │   ├── edit.ts            # Surgical AI streaming edit command
│   │   ├── export.ts          # Multi-format document exporter
│   │   ├── init.ts            # Setup, onboarding, and agent signup
│   │   ├── status.ts          # Session inspector & history viewer
│   │   └── upload.ts          # Multi-format document ingestion command
│   ├── utils/
│   │   ├── diff.ts            # Myers line-by-line diff computation
│   │   ├── logger.ts          # Terminal UI box formatting & logging
│   │   └── state.ts           # Conf-backed persistent state manager
│   ├── index.ts               # Commander program root definition
│   └── types.ts               # Global TypeScript interfaces & schemas
├── test/
│   └── superdocs.test.ts      # Native Node.js test suite
├── package.json
├── tsconfig.json
└── README.md
```

---
*Built for the SuperDocs Task.*
