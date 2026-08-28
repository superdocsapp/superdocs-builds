# Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        VS Code Extension Host                        │
│                                                                     │
│  src/extension.ts  (activate: commands, wiring, state)              │
│    ├─ latex-bridge.open / uploadProject / exportDocx / writeBack    │
│    ├─ latex-bridge.importTrackChanges / setKey / clearKey          │
│    └─ src/keychain.ts  ── SecretStorage (API key, never on disk)    │
│                                                                     │
│  ┌─────────────── Webview (React) ───────────────┐                  │
│  │ src/webview/app.tsx  phase machine UI:        │                  │
│  │  ready→uploading→uploaded→editing→awaiting→   │                  │
│  │  completed→exporting; review cards per change  │                  │
│  │ src/webview/panel.ts  postMessage bridge      │                  │
│  └───────────────▲──────────────────────────────┘                  │
│                  │ vscode.postMessage (JSON)                       │
└──────────────────┼──────────────────────────────────────────────────┘
                   │
┌──────────────────┴──────────────────────────────────────────────────┐
│  src/core/  (framework-free, unit-tested)                           │
│                                                                     │
│  client.ts      SuperDocsClient — thin REST wrapper:                │
│                 upload(URL presign→PUT→process) / chatAsync /        │
│                 poll(2s, onAwaitingApproval) / approve / export    │
│                                                                     │
│  session.ts     BridgeSession — state machine: op budget guard,     │
│                 poll loop pauses on awaiting_approval, waits for    │
│                 submitDecisions, approves instantly (deadline!)     │
│                                                                     │
│  zip.ts         findLaTeXRoot (main.tex / %!TEX root / single) +   │
│                 buildProjectZip (excludes .aux/.log/.pdf/...)        │
│                                                                     │
│  writeback.ts   segmentize (.tex → blank-line segments w/ byte      │
│                 offsets) · normalize · htmlToLatex (math/cite/       │
│                 footnote → LaTeX, placeholder tokens)                │
│                                                                     │
│  align.ts       buildAlignment (chunk→segment map) · planPatches    │
│                 (subsequence-score match, span patches via          │
│                 collapseWithMap byte map, append detection) ·       │
│                 applyPatches (byte-exact, untouched spans identical)│
│                                                                     │
│  trackchanges.ts parseDocxTrackChanges (w:ins/w:del ordered scan,   │
│                 w:br→space) → toChange() → same planner             │
│                                                                     │
│  writeback-cli.ts writeBackToProject — orchestrates segmentize→      │
│                 align→plan→apply, returns applied/unresolved         │
└─────────────────────────────────────────────────────────────────────┘
                   │
        HTTPS (REST, no MCP)
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  api.superdocs.app                                                   │
│  POST /v1/uploads → PUT presigned → POST /process (parse_mode=doc)  │
│  POST /v1/chat/async (approval_mode=ask_every_time)                 │
│  GET  /v1/jobs/{id}  (awaiting_approval → pending_changes)          │
│  POST /v1/chat/{session}/approve  (top-level approved:true)          │
│  POST /v1/documents/export (docx, A4)                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Data flow

**Chat edit round trip:** project folder → `zip.ts` → upload → `session.ts` polls →
webview renders review cards → decisions → `approve` → approved changes →
`writeback-cli.ts` → `align.ts` patches `.tex` byte-exactly.

**Co-author round trip:** identical, except the change source is `trackchanges.ts`
(docx `w:ins`/`w:del`) instead of the chat job.

## Key design points

- Everything in `src/core/` is framework-free (no vscode imports) so vitest runs it
  headless with recorded fixtures.
- The webview is a thin shell; all logic lives in the core layer.
- The poll loop pauses on `awaiting_approval` and blocks until the user decides;
  approvals expire in seconds, so the client approves immediately on decision.
- Write-back is byte-exact: only the changed paragraph ranges are replaced, untouched
  spans stay identical (asserted by tests).
