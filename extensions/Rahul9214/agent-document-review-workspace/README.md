# SuperDocs Agent Review Workspace

A compact VS Code review panel for agent-driven document changes. It is based directly on the SuperDocs Open Task List entry **“Agent document workspace for coding tools.”**

## What it demonstrates

1. **Agent activity stream** grouped by turn and document.
2. **Before / after document diff** for each proposed change.
3. **Approve / reject decisions** that apply independently per change.
4. **Revert** of an approved or applied change, restoring only that section’s original content.
5. **Claim-vs-actual verification** that catches an agent claiming an edit that is not present in the artifact.
6. **Multiple agent clients** represented through one neutral review model (Cursor Agent + Claude Code fixtures).
7. **Evidence + DOCX export** after review, with reviewer decision, actual artifact state, and reverted state preserved.

This is intentionally a **human control surface**, not another chat UI and not a SuperDocs clone.

## Run locally

```bash
npm ci
npm run build
npm test
```

Open **this project folder** in VS Code (or Cursor) and press **F5** to launch an Extension Development Host. Then run:

**SuperDocs: Open Agent Review Workspace**

The browser demo is the fastest review path:

```powershell
.\run-demo.ps1
```

Open `http://localhost:8031`.

## Demo scenario

Use the synthetic `vendor-agreement.docx` review queue:

- approve the requested renewal-notice change;
- revert that applied change and confirm sibling review states stay put;
- approve the concise support paragraph;
- reject the unrelated payment-term mutation;
- inspect a second agent turn where the agent claims an edit happened but the artifact contains no corresponding change;
- export the evidence JSON;
- export the reviewed DOCX.

## Evidence to capture

Use the files listed under **Evidence** below. Do not include API keys, tokens, or private documents.

Keep the terminal output for:

```bash
npm ci
npm run build
npm test
```

## Integration boundary

The demo uses deterministic synthetic agent events so every reviewer sees the same failure/review states. The review model is agent-neutral and shaped to accept real agent/SuperDocs events later. No claim is made here that the synthetic fixtures are live SuperDocs MCP calls.


## Evidence

The deterministic demo scenarios show the core review invariants:

- `01-initial-review-state` — four agent-proposed changes awaiting explicit human review.
- `02-claimed-vs-actual-mismatch` — verification catches an unrelated payment-term change that the agent did not disclose.
- `03-independent-revert` — one approved change is reverted without disturbing another approved change.
- `04-completed-human-review` — every proposed change receives a human decision; detected mismatches are rejected.
- `05-build-and-tests` — clean install, TypeScript build, and deterministic test suite pass.

Machine-readable review artifacts are included under `evidence/exports/`.

The fixture scenarios are synthetic and deterministic for repeatable review testing. They are not presented as live SuperDocs MCP traffic.