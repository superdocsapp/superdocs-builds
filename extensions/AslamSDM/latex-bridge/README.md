# LaTeX Bridge for SuperDocs

A Visual Studio Code extension that connects a LaTeX project to the SuperDocs AI document
editor, with human-in-the-loop review before anything touches your sources.

The full loop:

1. **Upload** — pick a LaTeX project folder; the extension finds the root file (`main.tex`,
   a `% !TEX root` directive, or a single `.tex` file), zips it, and uploads it to SuperDocs
   as a document.
2. **Chat edit** — ask for a change in natural language (e.g. "expand the abstract to two
   sentences"). SuperDocs proposes section-precise edits.
3. **Human-in-the-loop review** — every proposed change is shown as a diff card; you
   accept or deny each one, with optional feedback on denied changes. Nothing is applied
   without your approval.
4. **Export** — export the edited document as `.docx` (A4, Word-native math, footnotes,
   citations preserved).
5. **Write back** — approved edits are written back into your `.tex` sources as
   byte-exact patches: only the changed paragraph ranges are replaced, everything else
   stays untouched.
6. **Co-author round trip** — import a `.docx` with tracked changes (`w:ins` / `w:del`),
   review each change, and apply the accepted ones to your `.tex` sources with the same
   byte-exact patching.

## How to run

### Prerequisites

- VS Code 1.90+
- Node.js 18+ and npm
- A SuperDocs API key (`sk_...`). Get one at <https://use.superdocs.app> or via
  `POST /v1/agents/signup`.

### Setup

```bash
npm install
npm run build
```

### Install locally

```bash
code --install-extension latex-bridge-0.1.0.vsix
```

(Produce the `.vsix` with `npx @vscode/vsce package`.)

### Commands

| Command | What it does |
| --- | --- |
| `LaTeX Bridge: Open SuperDocs Session` | Focuses the LaTeX Bridge chat sidebar (project picker, chat edit, review, export). |
| `LaTeX Bridge: Focus Chat` | Focuses the LaTeX Bridge chat sidebar. |
| `LaTeX Bridge: Upload Project to SuperDocs` | Uploads the current project folder without opening the panel. |
| `LaTeX Bridge: Export Word Document` | Exports the session document as `.docx`. |
| `LaTeX Bridge: Write Approved Edits Back to .tex` | Applies accepted edits to the `.tex` sources. |
| `LaTeX Bridge: Import Co-author Tracked Changes (.docx)` | Reads `w:ins`/`w:del` from a `.docx`, reviews, applies. |
| `LaTeX Bridge: Set API Key` / `Clear API Key` | Manages the API key (stored in VS Code SecretStorage). |

On first use you are prompted for your API key; it is stored in VS Code secret storage,
never in the repository.

### Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `latexBridge.opBudgetPerSession` | `10` | Max AI chat-edit operations per session before pausing. |
| `latexBridge.pollIntervalMs` | `2000` | Job poll interval. Approval deadlines are short, keep this low. |

### Tests

```bash
npm test        # unit + UI tests (fixture-driven, no live API calls)
npm run typecheck
npm run build
```

Tests cover the API client, zip/root discovery, HITL session, write-back patching,
tracked-changes import, the React webview (jsdom, fixture payloads), and a real
extension-host boot check (`@vscode/test-electron`) that activates the extension and
asserts every command is registered. The live smoke tests are opt-in with
`SUPERDOCS_LIVE_SMOKE=1`.

## What SuperDocs features it uses

- **Chat editing** with `approval_mode: "ask_every_time"` — every proposed change
  (`proposed_change_batch`) waits for per-change decisions via the approve endpoint.
- **Document ingestion** — `POST /v1/uploads` (presigned upload) + `/process` with
  `parse_mode: "document"`.
- **Word export** — `POST /v1/documents/export` producing native `.docx` (oMath,
  footnotes, citations), A4 paper size.
- **REST API only** — no MCP, no web SDK; the client is a thin TypeScript wrapper around
  the SuperDocs HTTP API.

## How write-back works

- The project's `.tex` files are split into blank-line-separated segments with
  byte-accurate offsets.
- Each approved change's original HTML is converted to normalized visible text and
  matched to the best segment (ordered-subsequence score ≥ 0.7, positional fallback).
- Edits become **surgical span patches**: the changed text run inside the segment is
  located via whitespace-insensitive byte mapping and only that run is replaced.
- AI rewrites that *append* a whole new block are inserted after the aligned segment,
  so the original bytes are preserved exactly.
- Math (`data-latex`), citations (`\cite{...}`), footnotes (`\footnote{...}`) and
  section headings are serialized back to LaTeX losslessly.

## License

MIT

## Demo

Try it with the ready-made sample project in this folder (`samples/math-paper`) or clone
the demo repo: **<https://github.com/AslamSDM/latex-bridge-demo>** — it contains the extension
source, a prebuilt `.vsix`, a sample LaTeX project, and a step-by-step testing walkthrough.
