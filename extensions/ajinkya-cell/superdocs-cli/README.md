# ⚡ @ajinkya-cell/superdocs-cli

> **Interactive Terminal Developer Assistant & MCP Server for SuperDocs AI-Powered In-Document Intelligence & Surgical Editing.**

[![npm version](https://img.shields.io/npm/v/@ajinkya-cell/superdocs-cli.svg?color=cb3837&style=flat-square)](https://www.npmjs.com/package/@ajinkya-cell/superdocs-cli)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.5-3178c6.svg?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![SuperDocs API](https://img.shields.io/badge/SuperDocs%20API-v1-10b981.svg?style=flat-square)](https://superdocs.app)
[![MCP Ready](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-8b5cf6.svg?style=flat-square)](https://modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Node.js](https://img.shields.io/badge/Node.js-%3E%3D18.0.0-43853d.svg?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org)

---

## 📑 Table of Contents

1. [Executive Summary & Motivation](#-executive-summary--motivation)
2. [Key Capabilities & Differentiators](#-key-capabilities--differentiators)
3. [Deep System Architecture](#-deep-system-architecture)
   - [High-Level Component Architecture](#high-level-component-architecture)
   - [End-to-End Workflow Pipeline](#end-to-end-workflow-pipeline)
   - [Document Session & State Machine](#document-session--state-machine)
   - [Subsystem Technical Deep-Dive](#subsystem-technical-deep-dive)
4. [Installation & Rapid Onboarding](#-installation--rapid-onboarding)
5. [Complete CLI Command Reference](#-complete-cli-command-reference)
   - [`superdocs init`](#superdocs-init)
   - [`superdocs upload <path>`](#superdocs-upload-path)
   - [`superdocs edit [options]`](#superdocs-edit-options)
   - [`superdocs approve [options]`](#superdocs-approve-options)
   - [`superdocs export`](#superdocs-export)
   - [`superdocs status`](#superdocs-status)
6. [Interactive Terminal REPL Mode](#-interactive-terminal-repl-mode)
7. [Model Context Protocol (MCP) Integration](#-model-context-protocol-mcp-integration)
   - [Claude Desktop Configuration](#claude-desktop-configuration)
   - [Cursor IDE Configuration](#cursor-ide-configuration)
   - [Exposed MCP Tools Specification](#exposed-mcp-tools-specification)
8. [CI/CD Automation & GitHub Actions](#-cicd-automation--github-actions)
9. [Wire Protocol & API Endpoints](#-wire-protocol--api-endpoints)
10. [Offline Simulation Engine (Mock Mode)](#-offline-simulation-engine-mock-mode)
11. [Configuration & Storage Internals](#-configuration--storage-internals)
12. [Developer Guide & Testing](#-developer-guide--testing)
13. [License & Attribution](#-license--attribution)

---

## 📖 Executive Summary & Motivation

Traditional AI coding and writing workflows suffer from a fundamental disconnect: **context fracturing**. When developers use standard conversational LLM interfaces to update documentation, API specifications, resumes, or whitepapers:
- Text is generated in an isolated chat sidebar.
- Developers must manually copy, paste, and reconcile code blocks, losing formatting and structure.
- There is no automated visual diff preview or verification step before files on disk are overwritten.
- Multi-format ingestion (PDF, Word DOCX, Markdown) requires external conversion tools.

**`@ajinkya-cell/superdocs-cli`** bridges this gap by bringing the full power of the **[SuperDocs](https://superdocs.app)** document intelligence engine straight to the developer's terminal and agentic toolchain. It transforms document maintenance from a manual copy-paste chore into a precision-engineered, version-controlled, and stream-diffed workflow.

```
┌────────────────────────────┐      ┌───────────────────────────┐      ┌────────────────────────────┐
│      Raw Document          │ ───► │  SuperDocs In-Document    │ ───► │   Terminal Diff Review &   │
│  (.md, .pdf, .docx, .txt)  │      │     Surgical AI Stream    │      │  Multi-Format Compilation  │
└────────────────────────────┘      └───────────────────────────┘      └────────────────────────────┘
```

---

## ✨ Key Capabilities & Differentiators

- 🎯 **Surgical In-Document Editing**: Instead of rewriting entire files from scratch, the underlying AI performs localized, context-aware mutations while preserving surrounding structures, tables, headings, and formatting.
- 🌈 **Visual Terminal Diff Engine**: Computes line-by-line Myers unified diffs with high-visibility ANSI terminal coloring and change metrics (`+additions` / `-deletions`).
- 🛡️ **Interactive Approval Gates**: Changes are held in a staged version sandbox (`PendingVersion`). Developers inspect the diff before committing updates to the document or syncing to disk.
- 🔌 **Native Model Context Protocol (MCP)**: Exposes SuperDocs primitives as MCP tools for instant integration with Claude Desktop, Cursor, and autonomous agent loops.
- 🤖 **Zero-Friction Agent Onboarding**: Integrates with `POST /v1/agents/signup` to automatically provision API keys without leaving the terminal.
- 📦 **Universal Multi-Format Export**: Ingest Markdown, Word, or PDF, edit via streaming AI, and compile directly to clean `.md`, `.pdf`, `.docx`, or `.html`.
- 🧪 **High-Fidelity Offline Mock Engine**: Full local simulation mode (`--mock` or `SUPERDOCS_MOCK=true`) for isolated development, testing, and offline usage.

---

## 🏗️ Deep System Architecture

The CLI is engineered as a modular, layered Node.js/TypeScript architecture built on ES Modules (ESM). It cleanly separates presentation, business logic, remote transport, state persistence, and protocol adapters.

### High-Level Component Architecture

```mermaid
flowchart TD
    subgraph UserInterfaces [User & Agent Interfaces]
        CLI[Terminal CLI / Bin<br/><code>superdocs</code>]
        MCP_CLIENTS[Claude Desktop / Cursor / Agents]
    end

    subgraph Presentation [Command & Presentation Layer]
        CMD_INIT[init]
        CMD_UPLOAD[upload]
        CMD_EDIT[edit]
        CMD_APPROVE[approve]
        CMD_EXPORT[export]
        CMD_STATUS[status]
        LOGGER[Logger & Visual UI Box Engine<br/><code>src/utils/logger.ts</code>]
        DIFF_ENGINE[Myers Diff & Patch Subsystem<br/><code>src/utils/diff.ts</code>]
    end

    subgraph Adapters [Protocol Adapter Layer]
        MCP_ADAPTER[MCP Tool Registry & Dispatcher<br/><code>src/client/mcp-adapter.ts</code>]
    end

    subgraph CoreEngine [Core Client Engine]
        SD_CLIENT[SuperDocs Client<br/><code>src/client/superdocs.ts</code>]
        MOCK_SIM[High-Fidelity Mock Simulator]
    end

    subgraph StatePersistence [Persistent Storage Layer]
        CONF_STORE[OS Isolated Config Store<br/><code>superdocs-cli/config.json</code>]
        SESSION_STORE[Active Session & History Store<br/><code>superdocs-cli/session.json</code>]
    end

    subgraph RemoteBackend [SuperDocs Cloud Platform]
        API_AUTH[POST /v1/agents/signup]
        API_UPLOAD[POST /v1/documents/upload]
        API_CHAT[POST /v1/chat]
        API_APPROVE[POST /v1/chat/:id/approve]
        API_EXPORT[POST /v1/documents/export]
    end

    %% Wiring
    CLI --> CMD_INIT & CMD_UPLOAD & CMD_EDIT & CMD_APPROVE & CMD_EXPORT & CMD_STATUS & REPL
    MCP_CLIENTS --> MCP_ADAPTER
    MCP_ADAPTER --> SD_CLIENT
    MCP_ADAPTER --> DIFF_ENGINE
    
    CMD_EDIT & CMD_APPROVE & REPL --> DIFF_ENGINE
    CMD_INIT & CMD_UPLOAD & CMD_EDIT & CMD_APPROVE & CMD_EXPORT & CMD_STATUS & REPL --> LOGGER

    CMD_INIT & CMD_UPLOAD & CMD_EDIT & CMD_APPROVE & CMD_EXPORT & REPL --> SD_CLIENT
    CMD_INIT & CMD_UPLOAD & CMD_EDIT & CMD_APPROVE & CMD_EXPORT & CMD_STATUS & REPL --> CONF_STORE & SESSION_STORE
    
    SD_CLIENT --> CONF_STORE
    SD_CLIENT -.-> MOCK_SIM
    SD_CLIENT ==> RemoteBackend
```

---

### End-to-End Workflow Pipeline

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer / Agent
    participant CLI as SuperDocs CLI
    participant State as State Store (conf)
    participant Engine as SuperDocs Client
    participant Remote as SuperDocs Remote API
    
    Note over Dev,Remote: Step 1: Document Ingestion & Session Initialization
    Dev->>CLI: superdocs upload document.md
    CLI->>Engine: uploadDocument(path, content)
    Engine->>Remote: POST /v1/sessions/init
    Remote-->>Engine: { session_id: "session_123" }
    Engine->>Remote: POST /v1/documents/upload (multipart form)
    Remote-->>Engine: { document_id: "doc_abc", html: "...", content: "..." }
    Engine-->>CLI: Upload response payload
    CLI->>State: saveSession({ activeDocumentId, content, html, history: [] })
    CLI-->>Dev: ✔ Active document session established

    Note over Dev,Remote: Step 2: Surgical AI In-Document Editing
    Dev->>CLI: superdocs edit -p "Add API rate limiting section"
    CLI->>State: getSession()
    CLI->>Engine: streamEdit({ documentId, prompt, currentContent, currentHtml })
    Engine->>Remote: POST /v1/chat (session_id, prompt, document_html)
    Remote-->>Engine: Streaming AI reasoning & updated_html
    Engine->>Remote: POST /v1/documents/export (format: markdown)
    Remote-->>Engine: Parsed updated markdown
    Engine-->>CLI: PendingVersion { id, content, html, reasoning }
    CLI->>CLI: createDiff(currentContent, pendingContent)
    CLI->>State: saveSession({ pendingVersion })
    CLI-->>Dev: Diff summary (+14 / -2 lines) & pending approval status

    Note over Dev,Remote: Step 3: Interactive Diff Approval Gate
    Dev->>CLI: superdocs approve [--write-file]
    CLI->>State: getSession()
    CLI->>Dev: Render Colorized ANSI Unified Diff (+++ / ---)
    Dev->>CLI: Confirm approval (Y/n)
    CLI->>Engine: approveEdits(documentId, versionId)
    Engine->>Remote: POST /v1/chat/:id/approve
    Remote-->>Engine: { status: "approved" }
    CLI->>State: saveSession({ currentContent: pending.content, pendingVersion: null, history: +1 })
    opt If --write-file specified
        CLI->>Dev: Overwrite source file on disk
    end
    CLI-->>Dev: ✔ Changes locked and recorded in history

    Note over Dev,Remote: Step 4: Multi-Format Document Export
    Dev->>CLI: superdocs export --format pdf --out ./output.pdf
    CLI->>Engine: exportDocument(documentId, "pdf", currentContent, currentHtml)
    Engine->>Remote: POST /v1/documents/export { format: "pdf", html: "..." }
    Remote-->>Engine: Binary ArrayBuffer (PDF binary)
    Engine-->>CLI: Buffer
    CLI->>Dev: Save binary to disk (output.pdf)
```

---

### Document Session & State Machine

```mermaid
stateDiagram-v2
    [*] --> Uninitialized

    Uninitialized --> Initialized: superdocs init / signup
    Initialized --> ActiveSession: superdocs upload <file>
    
    state ActiveSession {
        [*] --> Ready: Session Stored
        Ready --> Editing: superdocs edit -p "..."
        Editing --> PendingDiff: Stream Finished & Diff Computed
        
        state PendingDiff {
            [*] --> DiffAwaitingReview
            DiffAwaitingReview --> Approved: superdocs approve (Accept)
            DiffAwaitingReview --> Rejected: superdocs approve (Reject)
        }
        
        Approved --> Ready: Content Updated & History Appended
        Rejected --> Ready: Version Discarded & State Reverted
    }

    Ready --> ActiveSession: superdocs export --format <fmt>
    Ready --> [*]: superdocs init --reset
```

---

### Subsystem Technical Deep-Dive

#### 1. Core Client Engine (`src/client/superdocs.ts`)
The `SuperDocsClient` class manages all HTTP and streaming interactions with the SuperDocs platform.
- **Dynamic Axios Factory**: Configures dynamic request headers with Bearer authentication and configurable request timeouts (120s) to support large document synthesis.
- **Bi-Directional HTML/Markdown Conversion**: Converts ingested binary formats (PDF, DOCX) into rich HTML AST structures for remote processing, and automatically down-converts updated server ASTs into clean Markdown for local terminal diff inspection.
- **Fallback Resilience**: Handles offline environments seamlessly by routing calls to the local mock simulator if `mockMode: true` is configured.

#### 2. Diff & Patch Subsystem (`src/utils/diff.ts`)
Implements an optimized unified diff generator built on the **Myers diff algorithm** (`diff` package).
- **Line Categorization**: Distinguishes added, deleted, and unchanged context lines.
- **Dual Representation Output**: Generates both an **ANSI-colorized terminal representation** (`chalk.green`, `chalk.red`, `chalk.dim`) and a **standard Markdown diff fenced block** (` ```diff ... ````) for automated GitHub PR integration.
- **Statistical Aggregation**: Computes additions count, deletions count, and unchanged baseline lines for quick inspection.

#### 3. Persistent State Subsystem (`src/utils/state.ts`)
State management is handled via `conf`, storing application configuration and active document state in user-space JSON files:
- **`config.json`**: Stores `apiKey`, `baseUrl`, `mockMode`, and `defaultExportFormat`.
- **`session.json`**: Stores `activeDocumentId`, `documentName`, `originalPath`, `originalContent`, `currentContent`, `currentHtml`, `pendingVersion`, and `history[]`.
- **Atomic Isolation**: Deep copies and cleans undefined values prior to disk writes to prevent storage corruption.

#### 4. Model Context Protocol (MCP) Adapter (`src/client/mcp-adapter.ts`)
Exposes 6 strongly typed MCP tools adhering to the Model Context Protocol specification:
- `superdocs_signup`
- `superdocs_upload`
- `superdocs_edit`
- `superdocs_approve`
- `superdocs_export`
- `superdocs_get_status`

---

## 📦 Installation & Rapid Onboarding

### Run Instantly with `npx` (No installation needed)
```bash
npx @ajinkya-cell/superdocs-cli --help
```

### Global Installation via NPM
```bash
npm install -g @ajinkya-cell/superdocs-cli
```

### Alternative Package Managers
```bash
# Yarn
yarn global add @ajinkya-cell/superdocs-cli

# PNPM
pnpm add -g @ajinkya-cell/superdocs-cli

# Bun
bun add -g @ajinkya-cell/superdocs-cli
```

---

## 💻 Complete CLI Command Reference

### `superdocs init`
Initializes credentials, custom API endpoints, default export formats, or automated agent accounts.

```bash
# Interactive Guided Setup Wizard
superdocs init

# Fast Non-Interactive Configuration
superdocs init --key "sd_live_your_api_key_here" --live

# Automated Agent Registration (Calls POST /v1/agents/signup)
superdocs init --signup

# Activate Offline Mock Simulation Mode
superdocs init --mock

# Reset all configurations to factory defaults
superdocs init --reset
```

#### Flags & Options:
| Flag | Long Flag | Description | Default |
| :--- | :--- | :--- | :--- |
| `-k` | `--key <key>` | SuperDocs API Bearer token | `undefined` |
| `-u` | `--url <url>` | Custom SuperDocs API base endpoint | `https://api.superdocs.app/v1` |
| `-s` | `--signup` | Automatically provision a new agent credential | `false` |
| `-m` | `--mock` | Enable offline mock simulation mode | `false` |
| `-l` | `--live` | Force live API mode (disables mock) | `false` |
| `-f` | `--format <type>` | Default export format (`pdf`, `docx`, `md`, `html`) | `md` |
| | `--reset` | Clear all saved configuration & session stores | `false` |

---

### `superdocs upload <path>`
Ingests a document from disk, parses its contents, initializes an active editing session, and stores the state locally.

```bash
# Upload a Markdown specification
superdocs upload ./docs/architecture.md

# Upload a PDF document
superdocs upload ./resume.pdf

# Upload a Microsoft Word document
superdocs upload ./contracts/service-agreement.docx
```

#### Supported Ingestion Formats:
- **Markdown** (`.md`, `.markdown`)
- **Plain Text** (`.txt`)
- **Adobe PDF** (`.pdf`)
- **Microsoft Word** (`.docx`)

---

### `superdocs edit [options]`
Executes streaming, surgical in-document edits against the currently active document.

```bash
# Interactive Prompt Entry (Prompts for instruction via Inquirer)
superdocs edit

# Direct Instruction via CLI Flag
superdocs edit -p "Add a troubleshooting section covering 401 Unauthorized and 429 Rate Limits"
```

#### What happens during `superdocs edit`:
1. Validates that an active document session exists.
2. Streams real-time reasoning feedback from the SuperDocs AI engine.
3. Computes unified line additions and deletions against the baseline content.
4. Stores the result in the `pendingVersion` state sandbox without overwriting the base document.
5. Displays a summary of proposed modifications and prompts the developer to review.

---

### `superdocs approve [options]`
Inspects the staged `pendingVersion` diff. For short documents, displays a high-visibility terminal comparison with context folding; for large documents or multi-page PDFs (>350 words / >50 lines), automatically launches a high-fidelity **HTML Visual Diff** in your default browser.

```bash
# Interactive Diff Review (Auto-detects document size and launches Web Diff for large files)
superdocs approve

# Force opening the HTML visual diff in your default browser
superdocs approve --web

# Disable automatic browser launch for large documents and force terminal diff
superdocs approve --no-web

# Write approved changes directly back to the original source file on disk
superdocs approve --write-file

# Output GitHub PR-compatible Markdown diff (Non-interactive CI mode)
superdocs approve --ci
```

#### Flags & Options:
| Flag | Long Flag | Description | Default |
| :--- | :--- | :--- | :--- |
| | `--web` | Force opening the HTML visual diff in default browser | `false` |
| | `--no-web` | Force terminal diff view even for large multi-page documents | `false` |
| | `--write-file`| Automatically sync approved content to local source file on disk | `false` |
| | `--ci` | Output diff in GitHub PR-compatible Markdown format | `false` |

#### Terminal Diff Output Preview:
```diff
SuperDocs Proposed Diff Inspection:
+12 -2 (unchanged: 84)
──────────────────────────────────────────────────────────────────────
--- a/architecture.md (current)
+++ b/architecture.md (proposed)
   ## API Reference
   All requests must include the authorization header.
-  Authorization: Bearer <token>
+  Authorization: Bearer sd_live_your_api_key_here
+
+  ### Rate Limiting
+  Standard accounts are limited to 60 requests per minute.
──────────────────────────────────────────────────────────────────────
? Approve and lock these edits on SuperDocs server? (Y/n)
```

---

### `superdocs export [options]`
Compiles and downloads the latest approved document version from the SuperDocs server into the requested output format.

```bash
# Export as Adobe PDF
superdocs export --format pdf --out ./dist/architecture-v1.pdf

# Export as Microsoft Word DOCX
superdocs export --format docx --out ./dist/architecture-v1.docx

# Export as clean Markdown
superdocs export --format md --out ./dist/architecture-v1.md

# Export as HTML
superdocs export --format html --out ./dist/architecture-v1.html
```

#### Flags & Options:
| Flag | Long Flag | Description |
| :--- | :--- | :--- |
| `-f` | `--format <type>` | Target export format: `pdf`, `docx`, `md`, `html`, `txt` |
| `-o` | `--out <path>` | Destination file path on local disk |

---

### `superdocs status`
Prints a comprehensive summary of the current SuperDocs environment, active document ID, source file path, character/word metrics, pending diff status, and applied edit history.

```bash
superdocs status
```

#### Example Status Output:
```
┌─ SuperDocs Configuration ────────────────────────────────────────┐
│ Base URL:       https://api.superdocs.app/v1                     │
│ API Key:        Configured (sd_live_325...)                      │
│ Mock Mode:      DISABLED (Live API)                              │
│ Default Format: md                                               │
└──────────────────────────────────────────────────────────────────┘
┌─ Active Document Session ────────────────────────────────────────┐
│ Document ID:    session_1724148920192                            │
│ Document Name:  architecture.md                                  │
│ Source Path:    C:/projects/docs/architecture.md                 │
│ Length:         4820 chars (142 lines)                           │
│ Applied Edits:  3                                                │
│ Pending Edit:   None                                             │
└──────────────────────────────────────────────────────────────────┘

Recent Edit History:
  1. [14:22:10] "Add authentication section" (ver_9xk2l1)
  2. [14:24:45] "Insert error status codes table" (ver_4mm89q)
  3. [14:28:12] "Format mermaid architecture diagram" (ver_1aa02p)
```

---

## 🤖 Model Context Protocol (MCP) Integration

`@ajinkya-cell/superdocs-cli` implements a full **Model Context Protocol (MCP)** adapter layer (`src/client/mcp-adapter.ts`), enabling AI agents running in **Claude Desktop**, **Cursor IDE**, or custom agentic workflows to natively orchestrate SuperDocs operations.

### Claude Desktop Configuration

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "superdocs": {
      "command": "npx",
      "args": ["-y", "@ajinkya-cell/superdocs-cli"]
    }
  }
}
```

### Cursor IDE Configuration

Add the following to your project's `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "superdocs": {
      "command": "node",
      "args": ["./node_modules/@ajinkya-cell/superdocs-cli/dist/bin/index.js"],
      "env": {
        "SUPERDOCS_API_KEY": "sd_live_your_api_key"
      }
    }
  }
}
```

---

### Exposed MCP Tools Specification

```mermaid
classDiagram
    class MCP_Tools {
        +superdocs_signup(agent_name)
        +superdocs_upload(filePath, content)
        +superdocs_edit(prompt)
        +superdocs_approve(accept)
        +superdocs_export(format, outputPath)
        +superdocs_get_status()
    }
```

#### 1. `superdocs_signup`
- **Description**: Instantly provisions an agent API credential on the SuperDocs platform.
- **Parameters**: `agent_name` (string, optional).

#### 2. `superdocs_upload`
- **Description**: Ingests a local file into the SuperDocs workspace and sets it as the active session.
- **Parameters**: `filePath` (string, required), `content` (string, optional).

#### 3. `superdocs_edit`
- **Description**: Applies surgical, context-aware AI modifications to the active document based on an instruction prompt.
- **Parameters**: `prompt` (string, required).
- **Returns**: `versionId`, `additions`, `deletions`, and standard Markdown `diff`.

#### 4. `superdocs_approve`
- **Description**: Commits or rejects the staged modifications in the pending sandbox.
- **Parameters**: `accept` (boolean, required).

#### 5. `superdocs_export`
- **Description**: Compiles and outputs the active document to disk in a specified target format.
- **Parameters**: `format` (`pdf` | `docx` | `md` | `html` | `txt`, required), `outputPath` (string, required).

#### 6. `superdocs_get_status`
- **Description**: Returns active document metadata, session ID, pending diff state, and history count.

---

## 🔄 CI/CD Automation & GitHub Actions

You can integrate `superdocs-cli` directly into your GitHub Pull Request review pipeline using the `--ci` flag on `superdocs approve` to generate automated markdown diff reviews.

### Example Workflow: `.github/workflows/docs-review.yml`

```yaml
name: SuperDocs Automated Documentation Review

on:
  pull_request:
    paths:
      - 'docs/**'
      - 'README.md'

jobs:
  doc-review:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install SuperDocs CLI
        run: npm install -g @ajinkya-cell/superdocs-cli

      - name: Configure SuperDocs Agent Credentials
        env:
          SUPERDOCS_API_KEY: ${{ secrets.SUPERDOCS_API_KEY }}
        run: superdocs init --key "$SUPERDOCS_API_KEY" --live

      - name: Ingest & Apply Quality Enhancements
        run: |
          superdocs upload ./README.md
          superdocs edit --prompt "Check for broken links, fix spelling errors, and ensure consistent markdown headings."

      - name: Generate PR Markdown Diff Comment
        id: diff_gen
        run: |
          DIFF_OUTPUT=$(superdocs approve --ci)
          echo "diff<<EOF" >> $GITHUB_OUTPUT
          echo "$DIFF_OUTPUT" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT

      - name: Post PR Diff Comment
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `### ⚡ SuperDocs Automated Documentation Review\n\n${{ steps.diff_gen.outputs.diff }}`
            });
```

---

## 📡 Wire Protocol & API Endpoints

The SuperDocs CLI communicates with the SuperDocs REST & SSE endpoints:

| Method | Endpoint | Description | Request Payload | Response |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/v1/agents/signup` | Automatic Agent Provisioning | `{ terms_accepted: true, agent_name: string }` | `{ api_key: string, agent_name: string }` |
| `GET` | `/v1/agents/whoami` | Verify Auth & Quota | Headers: `Authorization: Bearer <KEY>` | `{ account_id: string, tier: string, quota: { remaining: number } }` |
| `POST` | `/v1/sessions/init` | Allocate Document Session | `{}` | `{ session_id: string }` |
| `POST` | `/v1/documents/upload` | Ingest Multi-Format Document | Multipart `FormData` (`file`) | `{ document_id: string, html: string, filename: string }` |
| `POST` | `/v1/chat` | Streaming In-Document Surgical Edit | `{ session_id, message, document_html, model_tier, response_mode }` | `{ response: string, document_changes: { updated_html: string } }` |
| `POST` | `/v1/chat/:id/approve`| Commit & Lock Edit Version | `{ approved: true, version_id: string }` | `{ status: "approved" }` |
| `POST` | `/v1/documents/export` | Server-Side Document Compilation | `{ session_id, html, format: "pdf" \| "docx" \| "markdown" }` | `ArrayBuffer` (Binary file stream) |

---

## 🧪 Offline Simulation Engine (Mock Mode)

For local development, CI pipelines without external internet access, or headless unit testing, `superdocs-cli` includes a full **Mock Simulation Engine**.

### Activating Mock Mode
```bash
# Via CLI command
superdocs init --mock

# Or via Environment Variable
export SUPERDOCS_MOCK=true
```

### Simulated Behaviors:
- **Synthetic Key Generation**: Provisions mock keys matching `sd_mock_[random]`.
- **Progressive Streaming Delays**: Simulates realistic AI reasoning latency (step-by-step token generation).
- **Context-Aware Intent Detection**:
  - Prompting for `"error handling"` generates an error table.
  - Prompting for `"authentication"` injects an authorization guide.
  - Prompting for `"table of contents"` compiles a dynamic markdown TOC.
- **Binary Stream Synthesis**: Generates valid `%PDF-1.4` headers and DOCX binary buffers.

---

## 💾 Configuration & Storage Internals

Configuration and session data are stored using isolated OS-level user preference directories:

### Storage Locations:
- **Windows**: `%APPDATA%\superdocs-cli\config.json` and `session.json`
- **macOS**: `~/Library/Preferences/superdocs-cli/config.json` and `session.json`
- **Linux**: `~/.config/superdocs-cli/config.json` and `session.json`

### Environment Variable Overrides:
| Variable | Description |
| :--- | :--- |
| `SUPERDOCS_API_KEY` | Overrides the stored Bearer API key |
| `SUPERDOCS_API_URL` | Overrides the target API base URL (Default: `https://api.superdocs.app/v1`) |
| `SUPERDOCS_MOCK` | When set to `true`, forces offline mock mode across all commands |

---

## 🛠️ Developer Guide & Testing

### Project Structure
```
superdocs-cli/
├── bin/
│   └── index.ts               # CLI executable entrypoint
├── src/
│   ├── client/
│   │   ├── mcp-adapter.ts     # Model Context Protocol tools & dispatcher
│   │   └── superdocs.ts       # SuperDocs REST/SSE client & mock engine
│   ├── commands/
│   │   ├── approve.ts         # Visual diff review & commit command
│   │   ├── edit.ts            # Surgical AI streaming edit command
│   │   ├── export.ts          # Multi-format document exporter
│   │   ├── init.ts            # Setup, onboarding, and agent signup
│   │   ├── status.ts          # Session inspector & history viewer
│   │   └── upload.ts          # Multi-format document ingestion command
│   ├── utils/
│   │   ├── diff.ts            # Myers line-by-line diff computation
│   │   ├── logger.ts          # Terminal UI box formatting & logging
│   │   ├── pdf.ts             # ASCII85/Flate PDF parser & Adobe PDF generator
│   │   └── state.ts           # Conf-backed persistent state manager
│   ├── index.ts               # Commander program root definition
│   └── types.ts               # Global TypeScript interfaces & schemas
├── test/
│   └── superdocs.test.ts      # Native Node.js test suite
├── package.json
└── tsconfig.json
```

### Local Development Setup
```bash
# 1. Clone the repository
git clone https://github.com/ajinkya-cell/superdocs-cli.git
cd superdocs-cli

# 2. Install dependencies
npm install

# 3. Build TypeScript to dist/
npm run build

# 4. Watch mode for live development
npm run watch

# 5. Run the native test suite
npm test
```

---

## 👤 License & Attribution

- **Author**: [Ajinkya Dharkar (ajinkya-cell)](https://github.com/ajinkya-cell)
- **Attribution**: Built for the SuperDocs Task.
- **Project**: [SuperDocs App](https://superdocs.app)
- **License**: [MIT License](https://opensource.org/licenses/MIT) © 2026 Ajinkya Dharkar.
